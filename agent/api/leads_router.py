"""
Dashboard REST API: lists prospects from Crunchbase ODM data, runs enrichment,
and exposes channel actions with Tenacious channel priority (email → SMS after reply → voice via Cal.com).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.agent.composer import email_composer
from agent.agent.insights import CompetitorGapBrief, insight_generator
from agent.agent.outreach_context import build_outreach_prompt_variables, render_grounded_fallback_email
from agent.agent.prompt_loader import prompt_loader
from agent.agent.qualifier import reply_qualifier
from agent.channels.cal_client import cal_client, CalError
from agent.channels.email_client import email_client, EmailClientError
from agent.channels.sms_client import sms_client, SMSClientError
from agent.config import Environment, settings
from agent.db.database import get_db, async_session
from agent.db.models import Company, OutboundLog
from agent.enrichment import HiringSignalBrief
from agent.enrichment.crunchbase_odm import get_odm_row_by_id, website_to_display_domain
from agent.enrichment.pipeline import EnrichmentPipeline
from agent.integrations.hubspot_mcp import hubspot_client
from agent.integrations.llm_client import llm_client
from agent.paths import REPO_ROOT, resolve_repo_path
from agent.api.workspace_store import load_all_mirrored, mirror_workspace_row
from agent.agent.schema_validate import (
    build_competitor_gap_schema_instance,
    build_hiring_signal_schema_instance,
    validate_competitor_gap,
    validate_hiring_signal,
)
from agent.agent.discovery_brief import build_discovery_context_markdown, discovery_brief_to_hubspot_html
from agent.agent.sequencer import schedule_sequence_after_e1

logger = logging.getLogger(__name__)

_workspace_rehydrated_count: int = 0
_workspace_rehydrate_model_ok: bool = True

router = APIRouter(prefix="/api", tags=["dashboard"])


def _should_book_discovery(intent: str, inbound: str) -> bool:
    """Align simulate_reply with Tenacious flow: book only when reply shows meeting interest."""
    intent_l = (intent or "").lower().strip()
    if intent_l in ("interested", "interest", "positive", "yes", "booking", "schedule", "scheduling"):
        return True
    blob = (inbound or "").lower()
    if intent_l == "unclear" and any(
        phrase in blob
        for phrase in (
            "interested",
            "book a",
            "schedule",
            "calendar",
            "discovery call",
            "set up a call",
            "find a time",
        )
    ):
        return True
    return False

_workspace: Dict[str, Dict[str, Any]] = {}


def _append_channel_event(st: Dict[str, Any], event_type: str, detail: Dict[str, Any]) -> None:
    events = st.setdefault("channel_state", {}).setdefault("events", [])
    events.append(
        {
            "type": event_type,
            "at": datetime.now(timezone.utc).isoformat(),
            **detail,
        }
    )


async def _mirror(cid: str, st: Dict[str, Any]) -> None:
    await mirror_workspace_row(cid, st)


async def _log_outbound(channel: str, recipient: str, *, suppressed: bool, detail: Dict[str, Any]) -> None:
    try:
        async with async_session() as session:
            session.add(
                OutboundLog(
                    channel=channel,
                    recipient=recipient,
                    suppressed=suppressed,
                    detail=detail,
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug("OutboundLog write failed: %s", e)


async def append_channel_event_by_email(email: str, event_type: str, detail: Dict[str, Any]) -> None:
    """Webhook helper: append timeline events to any workspace row tied to this prospect email."""
    e = (email or "").strip().lower()
    if not e:
        return
    for cid, st in _workspace.items():
        pe = (st.get("prospect_email") or "").strip().lower()
        if pe == e:
            _append_channel_event(st, event_type, detail)
            await _mirror(cid, st)


def _restore_workspace_models(st: Dict[str, Any]) -> bool:
    """Re-build Pydantic briefs after JSON rehydrate. Returns False if enrichment row is unusable."""
    ok = True
    rb = st.get("raw_brief")
    if isinstance(rb, dict):
        try:
            st["raw_brief"] = HiringSignalBrief.model_validate(rb)
        except Exception:
            ok = False
    rg = st.get("raw_gap")
    if isinstance(rg, dict):
        try:
            st["raw_gap"] = CompetitorGapBrief.model_validate(rg)
        except Exception:
            ok = False
    return ok


async def rehydrate_workspace_from_db() -> None:
    """Merge mirrored Postgres state into in-memory workspace (memory wins on key conflicts)."""
    global _workspace_rehydrated_count, _workspace_rehydrate_model_ok
    data = await load_all_mirrored()
    _workspace_rehydrated_count = len(data)
    _workspace_rehydrate_model_ok = True
    for cid, payload in data.items():
        base = dict(payload) if isinstance(payload, dict) else {}
        cur = _workspace.get(cid, {})
        merged: Dict[str, Any] = {**base, **cur}
        _workspace[cid] = merged
        if merged.get("is_enriched") and not _restore_workspace_models(merged):
            _workspace_rehydrate_model_ok = False
            logger.warning("Workspace %s: could not restore brief models from mirror — re-run enrich.", cid)


class EnrichBody(BaseModel):
    company_id: str
    hubspot_email: Optional[str] = None


class OutreachBody(BaseModel):
    company_id: str
    content: Optional[str] = ""
    test_email: str
    test_phone: str = ""
    channel: str = "email"
    message: Optional[str] = None


class ApproveBody(BaseModel):
    company_id: str


def _csv_rows(limit: int) -> List[Dict[str, Any]]:
    path = resolve_repo_path(settings.CRUNCHBASE_CSV_PATH)
    if not path.is_file():
        logger.error(
            "Crunchbase CSV missing at %s (REPO_ROOT=%s, CWD=%s)",
            path,
            REPO_ROOT,
            os.getcwd(),
        )
        return []
    df = pd.read_csv(path, low_memory=False)
    if "name" not in df.columns or "id" not in df.columns:
        return []
    df = df.dropna(subset=["name", "id"])
    rows = []
    for _, row in df.head(limit).iterrows():
        industry = None
        if "industries" in df.columns and pd.notnull(row.get("industries")):
            try:
                import json

                ind = json.loads(str(row["industries"]))
                if isinstance(ind, list) and ind:
                    industry = ind[0].get("value")
            except Exception:
                industry = None
        rows.append(
            {
                "crunchbase_id": str(row["id"]),
                "name": str(row["name"]),
                "industry": industry or "—",
                "domain": str(row["website"]) if pd.notnull(row.get("website")) else None,
            }
        )
    return rows


def _crunchbase_csv_row_count() -> int:
    path = resolve_repo_path(settings.CRUNCHBASE_CSV_PATH)
    if not path.is_file():
        return 0
    try:
        return len(pd.read_csv(path, usecols=["id"], low_memory=False))
    except Exception:
        try:
            return sum(1 for _ in open(path, encoding="utf-8", errors="replace")) - 1
        except OSError:
            return 0


async def _load_companies(db: AsyncSession, limit: int) -> List[Dict[str, Any]]:
    try:
        # Order by name only — many deployments lack `employee_count` (schema drift).
        stmt = (
            select(
                Company.crunchbase_id,
                Company.name,
                Company.domain,
                Company.sector,
            )
            .order_by(Company.name.asc().nullslast())
            .limit(limit)
        )
        res = await db.execute(stmt)
        rows = res.all()
        if rows:
            logger.info("list_leads: using %s companies from database (narrow select)", len(rows))
            return [
                {
                    "crunchbase_id": r.crunchbase_id,
                    "name": r.name,
                    "industry": r.sector or "—",
                    "domain": r.domain,
                }
                for r in rows
            ]
        logger.info("list_leads: database empty, using Crunchbase CSV fallback")
    except ProgrammingError as e:
        logger.warning("Postgres `companies` schema does not match ORM (%s); using ODM CSV.", e)
    except Exception as e:
        logger.warning("DB company list failed, falling back to CSV: %s", e)
    csv_rows = await asyncio.to_thread(_csv_rows, limit)
    if not csv_rows:
        logger.error(
            "list_leads: CSV fallback returned 0 rows — check CRUNCHBASE_CSV_PATH and file at %s",
            resolve_repo_path(settings.CRUNCHBASE_CSV_PATH),
        )
    else:
        logger.info("list_leads: CSV fallback returned %s companies (limit=%s)", len(csv_rows), limit)
    return csv_rows


def _merge_workspace_row(row: Dict[str, Any]) -> Dict[str, Any]:
    cid = row["crunchbase_id"]
    st = _workspace.get(cid, {})
    job_count = 0
    if st.get("raw_brief"):
        jp = st["raw_brief"].signals.get("job_posts")
        if jp and not jp.error:
            job_count = int((jp.data or {}).get("job_count") or 0)
    out = {
        "company": {
            **row,
            "job_count": job_count or st.get("job_count") or 0,
        },
        "is_enriched": bool(st.get("is_enriched")),
    }
    if st.get("is_enriched"):
        out.update(
            {
                "enriched_at": st.get("enriched_at"),
                "draft_email": st.get("draft_email"),
                "draft_metadata": st.get("draft_metadata", {"status": "draft"}),
                "brief": st.get("brief"),
                "research": st.get("research"),
                "outreach_policy": st.get("outreach_policy"),
                "channel_state": st.get("channel_state", {}),
                "schema_validation": st.get("schema_validation"),
                "outreach_blocked": st.get("outreach_blocked"),
                "enrichment_progress": st.get("enrichment_progress", []),
                "hiring_signal_brief": st.get("hiring_signal_brief"),
                "competitor_gap_brief": st.get("competitor_gap_brief"),
            }
        )
    return out


def _outreach_policy_from_meta(meta: Dict[str, Any], hiring_brief: HiringSignalBrief) -> Dict[str, Any]:
    """Tenacious Week 10: segmentation + when Segment-4 / exploratory copy applies."""
    ai = int(meta.get("ai_maturity_integer") if meta.get("ai_maturity_integer") is not None else 0)
    seg = meta.get("icp_segment_key") or "abstain"
    weak = bool(meta.get("weak_job_signal"))
    return {
        "icp_segment_key": seg,
        "icp_confidence": float(meta.get("icp_confidence", 0.0) or 0.0),
        "weak_job_signal": weak,
        "ai_maturity_integer": ai,
        "exploratory_mode": seg == "abstain",
        "segment_4_pitch_allowed": ai >= 2,
        "email_always_generated": True,
        "documentation": (
            "Tenacious challenge: research is the value proposition. A draft Email 1 is produced for every "
            "enriched prospect. Segment 4 (specialized AI/capability gap) language is gated on AI maturity ≥ 2; "
            "at 0–1 we still email, but with softer Segments 1–2 framing or exploratory copy (ICP abstain). "
            "Low public job-post signal implies ask-don't-assert honesty rules."
        ),
    }


def _derive_evidence_strength(label_lower: str, data: Dict[str, Any], meta_evidence: Optional[float]) -> float:
    """
    Claim strength for outreach / ICP (Tenacious honesty): not the same as pipeline success.
    Absence findings (no layoff row, no leadership flag, sparse jobs) stay low — snapshot ≠ ground truth.
    """
    if label_lower == "job velocity":
        jc = int(data.get("job_count") or 0)
        lq = (data.get("listing_quality") or "").lower()
        uniq = int(data.get("unique_title_count") or 0)
        if jc <= 0:
            base = 0.22
        elif jc < 5:
            base = 0.48
        elif jc < 10:
            base = 0.66
        else:
            base = 0.78
        if lq == "low" or (uniq <= 1 and jc >= 2):
            base = min(base, 0.36)
        elif lq == "medium":
            base = min(base, 0.52)
        if meta_evidence is not None and meta_evidence > 0:
            base = min(0.88, max(base, float(meta_evidence) * 0.82))
        return round(base, 3)

    if label_lower == "funding & firmographics":
        base = 0.42
        ec = data.get("employee_count")
        try:
            ec_i = int(ec) if ec is not None else None
        except (TypeError, ValueError):
            ec_i = None
        if ec_i is not None:
            if ec_i <= 2:
                base += 0.04
            elif ec_i <= 20:
                base += 0.08
            else:
                base += 0.12
        if data.get("funding_round"):
            base += 0.06
        if data.get("funding_amount_usd") is not None and float(data.get("funding_amount_usd") or 0) > 0:
            base += 0.14
        if data.get("domain") or data.get("website_url"):
            base += 0.06
        if data.get("description") or data.get("sector"):
            base += 0.06
        if meta_evidence is not None and meta_evidence > 0:
            base = min(0.88, max(base, float(meta_evidence) * 0.82))
        return round(min(0.86, base), 3)

    if label_lower == "layoffs.fyi":
        if data.get("has_layoffs"):
            return 0.88
        return 0.28

    if label_lower == "leadership":
        if data.get("recent_change"):
            return 0.72
        return 0.32

    return 0.45


def _narrative_block(label: str, sig: Any) -> Dict[str, Any]:
    if sig is None:
        return {
            "label": label,
            "narrative": "No signal payload.",
            "source_confidence": 0.0,
            "evidence_strength": 0.0,
            "confidence": 0.0,
        }
    if getattr(sig, "error", None):
        return {
            "label": label,
            "narrative": f"Source error: {sig.error}",
            "source_confidence": 0.0,
            "evidence_strength": 0.0,
            "confidence": 0.0,
        }
    source_conf = float(getattr(sig, "confidence", 0.0) or 0.0)
    data = getattr(sig, "data", None) or {}
    meta_ev: Optional[float] = None
    if getattr(sig, "metadata", None) is not None:
        meta_ev = getattr(sig.metadata, "evidence_strength", None)
        if meta_ev is not None:
            meta_ev = float(meta_ev)
    # Pipeline σ is "fetch succeeded", not "data is strong" — cap when module signals thin evidence.
    if meta_ev is not None:
        source_conf = min(source_conf, max(0.25, meta_ev + 0.12))

    ll = label.lower()
    if ll == "job velocity":
        jc = int(data.get("job_count") or 0)
        vel = float(data.get("velocity_60d") or 0.0)
        note = (data.get("note") or "").strip()
        lq = (data.get("listing_quality") or "").lower()
        if jc <= 0 and note:
            text = note
        else:
            text = (
                f"Public listings snapshot: ~{jc} role(s) passing job-title heuristics; "
                f"60d velocity index {vel:.4f} (enrichment pipeline method)."
            )
            if lq == "low":
                text += " Repeated or thin titles — low reliability."
            elif lq == "medium":
                text += " Single-title pattern — confirm on live careers page before asserting."
    elif ll == "funding & firmographics":
        amt = data.get("funding_amount_usd")
        rnd = data.get("funding_round")
        ec = data.get("employee_count")
        parts = []
        try:
            ec_i = int(ec) if ec is not None else None
        except (TypeError, ValueError):
            ec_i = None
        if ec_i is not None:
            if ec_i <= 2:
                parts.append(
                    f"ODM shows ~{ec_i} employees (often missing/stale in CSV — not a reliable headcount signal)"
                )
            else:
                parts.append(f"~{ec_i} employees (Crunchbase ODM)")
        if rnd:
            parts.append(f"funding / stage marker: {rnd}")
        if amt:
            parts.append(f"raised ~${float(amt):,.0f}")
        text = "; ".join(parts) if parts else "Firmographic match from Crunchbase ODM sample."
    elif ll == "layoffs.fyi":
        if data.get("has_layoffs"):
            text = (
                f"Layoff event on record ({data.get('latest_layoff_date')}), "
                f"~{data.get('laid_off_count')} people affected (public CSV)."
            )
        else:
            text = data.get("note") or "No matching layoff rows in snapshot."
    elif ll == "leadership":
        if data.get("recent_change"):
            text = data.get("change_note") or "Leadership transition signal."
        else:
            text = data.get("change_note") or "No leadership change flagged in window."
    else:
        text = str(data)[:500]

    evidence = _derive_evidence_strength(ll, data, meta_ev)
    caveat = None
    if ll == "layoffs.fyi" and not data.get("has_layoffs"):
        caveat = "Absence in snapshot ≠ proof the firm had no layoffs."
    elif ll == "leadership" and not data.get("recent_change"):
        caveat = "Heuristic only; no press/CRM verification in this pipeline."
    elif ll == "job velocity" and int(data.get("job_count") or 0) < 5:
        caveat = "Weak public hiring signal — use ask-don't-assert in copy."
    elif ll == "funding & firmographics":
        try:
            _ec = int(data.get("employee_count")) if data.get("employee_count") is not None else None
        except (TypeError, ValueError):
            _ec = None
        if _ec is not None and _ec <= 2:
            caveat = "Tiny employee_count in ODM is usually incomplete — do not use as a scale claim."

    out: Dict[str, Any] = {
        "label": label,
        "narrative": text,
        "source_confidence": round(source_conf, 3),
        "evidence_strength": evidence,
        "confidence": evidence,
        "confidence_note": (
            "confidence mirrors evidence_strength (claim-safe). "
            "source_confidence reflects pipeline/module success."
        ),
    }
    if caveat:
        out["evidence_caveat"] = caveat
    return out


def _build_ui_brief(hb: HiringSignalBrief) -> Dict[str, Any]:
    s = hb.signals
    narratives = {
        "job_velocity": _narrative_block("Job velocity", s.get("job_posts")),
        "funding": _narrative_block("Funding & firmographics", s.get("crunchbase")),
        "layoffs": _narrative_block("layoffs.fyi", s.get("layoffs")),
        "leadership": _narrative_block("Leadership", s.get("leadership")),
    }
    am = hb.ai_maturity
    am_ev = round(am.overall_confidence, 3) if am else 0.0
    am_pipe = round(min(1.0, max(0.2, am_ev * 0.92)), 3) if am else 0.0
    narratives["ai_maturity"] = {
        "label": "AI maturity (public signals)",
        "narrative": am.summary if am else "",
        "source_confidence": am_pipe,
        "evidence_strength": am_ev,
        "confidence": am_ev,
        "score": am.integer_score if am else 0,
        "confidence_note": "Pipeline σ follows scorer confidence (never 100% on thin public signal).",
    }
    ev_keys = ("job_velocity", "funding", "layoffs", "leadership", "ai_maturity")
    ev_vals = [float(narratives[k]["evidence_strength"]) for k in ev_keys if k in narratives]
    overall_evidence = round(sum(ev_vals) / len(ev_vals), 3) if ev_vals else 0.0

    return {
        "summary": hb.summary,
        "overall_confidence": round(hb.overall_confidence, 3),
        "overall_evidence_strength": overall_evidence,
        "velocity_60d": hb.velocity_60d,
        "signals": narratives,
        "confidence_model": {
            "source_confidence": "Pipeline succeeded / module-reported certainty on the fetch.",
            "evidence_strength": "Calibrated weight for substantive claims (Tenacious honesty; absence findings capped).",
            "confidence_field": "Alias of evidence_strength for backward-compatible consumers.",
        },
    }


def _research_from_gap(gap: CompetitorGapBrief, hiring_brief: HiringSignalBrief) -> Dict[str, Any]:
    per_signal = []
    for key, sig in hiring_brief.signals.items():
        if sig and not sig.error:
            per_signal.append(
                {
                    "source_key": key,
                    "confidence": round(float(sig.confidence or 0), 3),
                    "evidence_strength": round(float(sig.metadata.evidence_strength or 0), 3)
                    if sig.metadata
                    else None,
                }
            )
    return {
        "key_gaps": [f"{g.practice_name} — {g.evidence}" for g in gap.gaps],
        "gaps_detail": [g.model_dump() for g in gap.gaps],
        "competitors_analyzed": gap.competitors_analyzed,
        "percentile_position": gap.percentile_position,
        "prospect_ai_score": gap.prospect_ai_score,
        "competitor_avg_score": gap.competitor_avg_score,
        "is_sparse_sector": gap.is_sparse_sector,
        "per_signal_confidence": per_signal,
    }


async def _hubspot_push_demo(
    email: str,
    company_name: str,
    crunchbase_id: str,
    domain: Optional[str],
    sector: str,
    gap: CompetitorGapBrief,
    hiring_signal_brief: Dict[str, Any],
    competitor_gap_brief: Dict[str, Any],
):
    """
    HubSpot contact upsert (built-in fields by default) + notes with full schema briefs.
    Set HUBSPOT_SYNC_CUSTOM_PROPERTIES=true after creating Tenacious custom properties in HubSpot.
    """
    import html as html_module

    props = hubspot_client.contact_properties_from_schema_briefs(
        email,
        company_name=company_name,
        domain=domain,
        crunchbase_id=crunchbase_id,
        hiring_signal_brief=hiring_signal_brief,
        competitor_gap_brief=competitor_gap_brief,
        sector=sector or "",
    )
    await hubspot_client.create_or_update_contact(email, props)
    note = hubspot_client.format_enrichment_briefs_note_html(hiring_signal_brief, competitor_gap_brief)
    gap_parts = [
        f"<p><b>{html_module.escape(g.practice_name)}</b>: {html_module.escape((g.evidence or '')[:400])}</p>"
        for g in (gap.gaps or [])[:5]
    ]
    if gap_parts:
        note += "<p><b>Gap highlights</b> (public signals)</p>" + "".join(gap_parts)
    await hubspot_client.append_note_for_contact_email(email, note)


async def _compose_warm_reply(name: str, intent: str, inbound: str) -> str:
    variables = {
        "company": name,
        "intent": intent,
        "reply_text": inbound[:1200],
    }
    try:
        prompt = prompt_loader.load_prompt("compose_warm_reply", variables)
        raw = await llm_client.call(prompt=prompt, model_type="dev", json_mode=False)
    except Exception:
        raw = (
            f"Subject: Re: {name}\n\n"
            "Appreciate the reply. Happy to tailor this to your current priorities and share a short, "
            "signal-grounded outline your team can react to. If useful, send 2-3 constraints and I'll map "
            "a practical next step."
        )
    return raw.strip()


@router.get("/leads")
async def list_leads(
    limit: int = Query(500, ge=1, le=5000, description="Max companies to return (ODM has ~1001 rows)."),
    db: AsyncSession = Depends(get_db),
):
    rows = await _load_companies(db, limit)
    return [_merge_workspace_row(r) for r in rows]


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    try:
        total = await db.scalar(select(func.count()).select_from(Company))
    except Exception:
        total = None
    if not total:
        total = await asyncio.to_thread(_crunchbase_csv_row_count)
    job_signals = 0
    for st in _workspace.values():
        rb = st.get("raw_brief")
        if not rb:
            continue
        jp = rb.signals.get("job_posts")
        if jp and not jp.error:
            job_signals += int((jp.data or {}).get("job_count") or 0)
    outreach = sum(1 for st in _workspace.values() if st.get("channel_state", {}).get("email_sent_at"))
    booked = sum(1 for st in _workspace.values() if st.get("channel_state", {}).get("discovery_booked"))
    return {
        "total_companies": int(total or 0),
        "total_jobs": job_signals,
        "active_outreach": outreach,
        "booked_calls": booked,
        "kill_switch": settings.KILL_SWITCH,
        "live_outreach": settings.LIVE_OUTREACH,
        "outbound_suppressed": settings.outbound_is_suppressed(),
        "workspace_rows": len(_workspace),
        "workspace_rehydrated_mirrors": _workspace_rehydrated_count,
        "require_human_approval": settings.REQUIRE_HUMAN_APPROVAL,
        "enforce_json_schema": settings.ENFORCE_JSON_SCHEMA,
        "workspace_persisted": (_workspace_rehydrated_count == 0) or _workspace_rehydrate_model_ok,
        "workspace_mirror_rows": _workspace_rehydrated_count,
    }


@router.get("/leads/enrich/stream/{company_id}")
async def enrich_stream(company_id: str):
    """SSE-style polling stream of enrichment_progress for a company (dashboard)."""

    async def gen():
        for _ in range(240):
            await asyncio.sleep(1)
            st = _workspace.get(company_id) or {}
            payload = {
                "progress": st.get("enrichment_progress", []),
                "done": bool(st.get("is_enriched")),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if st.get("is_enriched"):
                break

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/leads/enrich")
async def enrich_lead(body: EnrichBody, db: AsyncSession = Depends(get_db)):
    cid = body.company_id
    row = get_odm_row_by_id(cid)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown Crunchbase ODM id — not found in sample CSV (check `id` column).",
        )
    name = str(row["name"])
    wu = row.get("website")
    website_url: Optional[str] = None
    if wu is not None and not (isinstance(wu, float) and pd.isna(wu)):
        website_url = str(wu).strip() or None
    domain = website_to_display_domain(wu)

    _workspace.setdefault(cid, {})
    prog: List[Dict[str, Any]] = []

    async def _progress(stage: str) -> None:
        prog.append({"stage": stage, "at": datetime.now(timezone.utc).isoformat()})
        _workspace[cid]["enrichment_progress"] = list(prog)

    pipeline = EnrichmentPipeline(db)
    hiring_brief = await pipeline.run(
        company_name=name,
        domain=domain,
        crunchbase_id=cid,
        website_url=website_url,
        progress_callback=_progress,
    )

    cb = hiring_brief.signals.get("crunchbase")
    sector = "Technology"
    if cb and not cb.error:
        sector = cb.data.get("sector") or sector

    gap = await insight_generator.generate_competitor_gap_brief(
        lead_name=name,
        sector=sector,
        prospect_signals=hiring_brief.signals,
    )
    await _progress("compose")

    # Email 1 has no Cal link — booking happens only after reply + qualify (see /api/outreach/book-discovery).
    draft_meta: Dict[str, Any] = {
        "status": "draft",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenacious_seed": "tenacious_sales_data/seed + challenge brief",
    }
    outreach_policy: Dict[str, Any] = {}
    try:
        email, out_meta = await email_composer.compose_personalized(
            hiring_brief=hiring_brief,
            gap_brief=gap,
            salutation_name="",
            scheduling_url="",
        )
        draft_body = f"{email['subject']}\n\n{email['body']}"
        draft_meta.update(out_meta)
        outreach_policy = _outreach_policy_from_meta(out_meta, hiring_brief)
    except Exception as e:
        logger.exception("LLM compose failed; using grounded fallback draft")
        pack = build_outreach_prompt_variables(
            hiring_brief,
            gap,
            scheduling_url="",
        )
        fb_meta = dict(pack.pop("metadata", None) or {})
        fb = render_grounded_fallback_email(pack, scheduling_url="")
        draft_body = f"{fb['subject']}\n\n{fb['body']}\n\n(Compose fallback: {e})"
        draft_meta.update(fb_meta)
        outreach_policy = _outreach_policy_from_meta(fb_meta, hiring_brief)

    ui_brief = _build_ui_brief(hiring_brief)
    research = _research_from_gap(gap, hiring_brief)

    seg_key = str((draft_meta or {}).get("icp_segment_key") or "abstain")
    seg_conf = float((draft_meta or {}).get("icp_confidence") or 0.0)
    dom = domain or ""
    hi_inst = build_hiring_signal_schema_instance(
        hiring_brief,
        prospect_domain=dom,
        primary_segment_match=seg_key,
        segment_confidence=seg_conf,
    )
    ok_h, err_h = validate_hiring_signal(hi_inst)
    cg_inst = build_competitor_gap_schema_instance(
        gap, hiring_brief, prospect_domain=dom, primary_segment_match=seg_key
    )
    ok_c, err_c = validate_competitor_gap(cg_inst)
    schema_validation = {
        "hiring_signal_ok": ok_h,
        "hiring_signal_error": err_h,
        "competitor_gap_ok": ok_c,
        "competitor_gap_error": err_c,
    }

    jp = hiring_brief.signals.get("job_posts")
    jc = 0
    if jp and not jp.error:
        jc = int((jp.data or {}).get("job_count") or 0)

    prev_ch = _workspace.get(cid, {}).get("channel_state", {})
    pe = (body.hubspot_email or "").strip()
    _workspace[cid] = {
        "is_enriched": True,
        "enriched_at": datetime.now(timezone.utc).isoformat(),
        "company_name": name,
        "domain": domain,
        "job_count": jc,
        "draft_email": draft_body,
        "draft_metadata": draft_meta,
        "outreach_policy": outreach_policy,
        "brief": ui_brief,
        "research": research,
        "raw_brief": hiring_brief,
        "raw_gap": gap,
        "channel_state": prev_ch,
        "enrichment_progress": _workspace[cid].get("enrichment_progress", prog),
        "schema_validation": schema_validation,
        "outreach_blocked": settings.ENFORCE_JSON_SCHEMA and not (ok_h and ok_c),
        "prospect_email": pe or _workspace.get(cid, {}).get("prospect_email"),
        "hiring_signal_brief": hi_inst,
        "competitor_gap_brief": cg_inst,
    }

    hub_email = body.hubspot_email
    if hub_email:
        try:
            await _hubspot_push_demo(
                hub_email,
                name,
                cid,
                domain,
                sector,
                gap,
                hi_inst,
                cg_inst,
            )
            st = _workspace.get(cid, {})
            _append_channel_event(
                st,
                "hubspot_synced",
                {"phase": "enrich", "email": hub_email},
            )
        except Exception as e:
            logger.warning("HubSpot sync during enrich failed (non-fatal): %s", e)

    await mirror_workspace_row(cid, _workspace[cid])

    return _merge_workspace_row(
        {
            "crunchbase_id": cid,
            "name": name,
            "industry": sector,
            "domain": domain,
        }
    )


@router.post("/outreach/approve")
async def outreach_approve(body: ApproveBody):
    st = _workspace.get(body.company_id)
    if not st or not st.get("is_enriched"):
        raise HTTPException(status_code=400, detail="Enrich this company first")
    st.setdefault("channel_state", {})["outreach_approved"] = True
    _append_channel_event(st, "outreach_approved", {})
    if str(st.get("channel_state", {}).get("last_intent") or "").lower() == "interested":
        _append_channel_event(
            st,
            "voice_handoff_requested",
            {"reason": "human_approved_interested_intent"},
        )
    await mirror_workspace_row(body.company_id, st)
    return {"ok": True, "channel_state": st.get("channel_state", {})}


@router.post("/outreach/send")
async def outreach_send(body: OutreachBody):
    st = _workspace.get(body.company_id)
    if not st or not st.get("is_enriched"):
        raise HTTPException(status_code=400, detail="Enrich this company before outreach")

    if st.get("outreach_blocked") and settings.ENFORCE_JSON_SCHEMA:
        raise HTTPException(
            status_code=400,
            detail="Brief JSON Schema validation failed — check schema_validation on the lead or set ENFORCE_JSON_SCHEMA=false.",
        )

    channel = (body.channel or "email").lower()
    if channel not in ("email", "sms"):
        raise HTTPException(status_code=400, detail="channel must be email or sms")

    if channel == "sms":
        if not st.get("channel_state", {}).get("prospect_replied"):
            raise HTTPException(
                status_code=400,
                detail="SMS is gated: prospect must reply on email first (Tenacious policy).",
            )

    st["prospect_email"] = (body.test_email or "").strip() or st.get("prospect_email")

    if channel == "email" and settings.REQUIRE_HUMAN_APPROVAL:
        if not st.get("channel_state", {}).get("outreach_approved"):
            return {
                "ok": True,
                "needs_approval": True,
                "message": "Human approval required — POST /api/outreach/approve for this company_id first.",
                "draft_email": st.get("draft_email"),
                "channel_state": st.get("channel_state", {}),
            }

    if settings.outbound_is_suppressed():
        logger.info("Kill switch: suppressing real %s send for demo", channel)
        _append_channel_event(
            st,
            "outbound_suppressed",
            {"channel": channel, "reason": "kill_switch"},
        )
        await _log_outbound(
            channel,
            body.test_email if channel == "email" else body.test_phone,
            suppressed=True,
            detail={"reason": "kill_switch", "company_id": body.company_id},
        )
        await mirror_workspace_row(body.company_id, st)
        return {
            "ok": True,
            "suppressed": True,
            "channel": channel,
            "reason": "KILL_SWITCH is enabled — configure outbound routing before production.",
            "env_hint": "Set KILL_SWITCH=false in .env for live sends. In development only, LIVE_OUTREACH=true also delivers while KILL_SWITCH stays true.",
            "channel_state": st.get("channel_state", {}),
        }

    if settings.KILL_SWITCH and settings.ENVIRONMENT == Environment.DEVELOPMENT and settings.LIVE_OUTREACH:
        logger.warning("LIVE_OUTREACH: sending real %s despite KILL_SWITCH (development only)", channel)

    text = (body.content or st.get("draft_email") or "").strip()
    if channel == "email":
        lines = text.split("\n", 1)
        subject = lines[0].replace("Subject:", "").strip() if lines else "Tenacious — signal-grounded note"
        html_body = lines[1].strip() if len(lines) > 1 else text
        try:
            await email_client.send_email(to=body.test_email, subject=subject, html=html_body.replace("\n", "<br/>"))
        except EmailClientError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        st.setdefault("channel_state", {})["email_sent_at"] = datetime.now(timezone.utc).isoformat()
        _append_channel_event(
            st,
            "email_sent",
            {"to": body.test_email, "subject": subject[:180]},
        )
        try:
            await schedule_sequence_after_e1(body.company_id, body.test_email)
        except Exception as e:
            logger.warning("Sequence schedule after E1 failed (non-fatal): %s", e)
        await _log_outbound(
            "email",
            body.test_email,
            suppressed=False,
            detail={"subject": subject[:180], "company_id": body.company_id},
        )
        await mirror_workspace_row(body.company_id, st)
        return {"ok": True, "channel": "email", "suppressed": False, "channel_state": st.get("channel_state", {})}

    # SMS — warm lead only; no Cal link here (scheduling after explicit book-discovery / API booking).
    phone = sms_client.normalize_recipient(body.test_phone)
    if not phone:
        raise HTTPException(
            status_code=400,
            detail="test_phone is required for SMS (E.164, e.g. +254711082XXX).",
        )
    sms_res: Dict[str, Any] = {}
    try:
        base = (text or st.get("draft_email") or "").replace("\n", " ").strip()
        sms_text = (base[:240] if base else f"Tenacious: quick follow-up re {st.get('company_name', 'our note')}.")
        if len(sms_text) > 300:
            sms_text = sms_text[:297] + "…"
        sms_res = await sms_client.send_warm_lead_sms(to=phone, message=sms_text)
    except SMSClientError as e:
        logger.warning("SMS send failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e)) from e

    if sms_res.get("suppressed"):
        _append_channel_event(st, "outbound_suppressed", {"channel": "sms", "reason": "kill_switch"})
        await _log_outbound(
            "sms",
            phone,
            suppressed=True,
            detail={"reason": "kill_switch", "company_id": body.company_id},
        )
        await mirror_workspace_row(body.company_id, st)
        return {
            "ok": True,
            "suppressed": True,
            "channel": "sms",
            "reason": "KILL_SWITCH enabled",
            "channel_state": st.get("channel_state", {}),
        }

    st.setdefault("channel_state", {})["sms_sent_at"] = datetime.now(timezone.utc).isoformat()
    _append_channel_event(
        st,
        "sms_sent",
        {"to": phone, "preview": sms_text[:200]},
    )
    await _log_outbound(
        "sms",
        phone,
        suppressed=False,
        detail={"preview": sms_text[:180], "company_id": body.company_id},
    )
    await mirror_workspace_row(body.company_id, st)
    return {"ok": True, "channel": "sms", "suppressed": False, "channel_state": st.get("channel_state", {})}


@router.post("/simulate/reply")
async def simulate_reply(body: OutreachBody):
    st = _workspace.get(body.company_id)
    if not st or not st.get("is_enriched"):
        raise HTTPException(status_code=400, detail="Enrich first")

    st["prospect_email"] = (body.test_email or "").strip() or st.get("prospect_email")

    inbound = body.message or body.content or "Interested — send times for a discovery call."
    q = await reply_qualifier.qualify(inbound)
    intent = (q.get("intent") or "unclear").lower()

    st.setdefault("channel_state", {})["prospect_replied"] = True
    st["channel_state"]["last_inbound_preview"] = inbound[:500]
    st["channel_state"]["last_intent"] = intent
    _append_channel_event(
        st,
        "reply_received",
        {"intent": intent, "message_preview": inbound[:240]},
    )

    hb: HiringSignalBrief = st["raw_brief"]
    name = st.get("company_name") or "Prospect"

    qualified = _should_book_discovery(intent, inbound)
    st["channel_state"]["qualified_for_discovery"] = qualified

    if qualified:
        _append_channel_event(
            st,
            "qualified_for_discovery",
            {"intent": intent, "message_preview": inbound[:240]},
        )
        booking_link = cal_client.get_booking_link(body.test_email, name=name)
        st["channel_state"]["cal_booking_link"] = booking_link
        if settings.REQUIRE_HUMAN_APPROVAL or not booking_link:
            st["draft_email"] = await _compose_warm_reply(name, intent, inbound)
            _append_channel_event(
                st,
                "warm_reply_draft_ready",
                {"reason": "human_approval_or_no_booking_link"},
            )
    else:
        _append_channel_event(
            st,
            "qualified_no_booking",
            {"intent": intent, "reason": "intent_not_meeting_ready"},
        )
        st["channel_state"].pop("cal_booking_link", None)

    await mirror_workspace_row(body.company_id, st)

    return {
        "ok": True,
        "intent": intent,
        "qualifier": q,
        "qualified_for_discovery": qualified,
        "channel_state": st["channel_state"],
        "voice_note": "After qualify, use Book discovery (Cal.com) to create the API booking. Voice = human discovery on that call.",
    }


@router.post("/outreach/book-discovery")
async def book_discovery(body: OutreachBody):
    """Create Cal.com booking after enrich + simulate reply qualifies the lead (dashboard demo)."""
    st = _workspace.get(body.company_id)
    if not st or not st.get("is_enriched"):
        raise HTTPException(status_code=400, detail="Enrich first")
    if not st.get("channel_state", {}).get("email_sent_at"):
        raise HTTPException(status_code=400, detail="Send Email 1 first (channel ladder).")
    if not st.get("channel_state", {}).get("prospect_replied"):
        raise HTTPException(status_code=400, detail="Simulate a reply first")
    if not st.get("channel_state", {}).get("qualified_for_discovery"):
        raise HTTPException(
            status_code=400,
            detail="Reply does not qualify for discovery booking — use an interested / scheduling reply.",
        )
    if st.get("channel_state", {}).get("discovery_booked"):
        return {
            "ok": True,
            "already_booked": True,
            "channel_state": st["channel_state"],
        }

    st["prospect_email"] = (body.test_email or "").strip() or st.get("prospect_email")

    hb: HiringSignalBrief = st["raw_brief"]
    name = st.get("company_name") or "Prospect"
    start_time = await cal_client.resolve_booking_start_time(horizon_days=21)
    if not start_time:
        booking = {
            "success": False,
            "error": "No Cal.com availability in the next 21 days — check CALCOM_EVENT_TYPE_ID and host calendar.",
        }
    else:
        try:
            booking = await cal_client.book_meeting(
                name=name,
                email=body.test_email,
                start_time=start_time,
                booking_title=name,
            )
        except CalError as e:
            booking = {"success": False, "error": str(e)}
    st["channel_state"]["discovery_booked"] = bool(booking.get("success"))
    st["channel_state"]["booking_payload"] = {k: booking.get(k) for k in ("booking_id", "status", "error", "raw") if k in booking}
    _append_channel_event(
        st,
        "cal.booking_confirmed" if booking.get("success") else "cal.booking_failed",
        {"booked": bool(booking.get("success")), "booking_id": booking.get("booking_id"), "error": booking.get("error")},
    )

    if body.test_email and booking.get("success"):
        try:
            gap = st["raw_gap"]
            dom = (st.get("domain") or "") or ""
            dm = st.get("draft_metadata") or {}
            seg_key = str(dm.get("icp_segment_key") or "abstain")
            seg_conf = float(dm.get("icp_confidence") or 0.0)
            hi_inst = st.get("hiring_signal_brief")
            cg_inst = st.get("competitor_gap_brief")
            if not hi_inst or not cg_inst:
                hi_inst = build_hiring_signal_schema_instance(
                    hb,
                    prospect_domain=dom,
                    primary_segment_match=seg_key,
                    segment_confidence=seg_conf,
                )
                cg_inst = build_competitor_gap_schema_instance(
                    gap, hb, prospect_domain=dom, primary_segment_match=seg_key
                )
            cb = hb.signals.get("crunchbase")
            sec = "Technology"
            if cb and not cb.error:
                sec = str(cb.data.get("sector") or sec)
            await _hubspot_push_demo(
                body.test_email,
                name,
                body.company_id,
                dom,
                sec,
                gap,
                hi_inst,
                cg_inst,
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            await hubspot_client.create_or_update_contact(
                body.test_email,
                {"lifecyclestage": "opportunity"},
            )
            await hubspot_client.log_event(
                body.test_email,
                "Discovery booked",
                f"discovery_booked:{now} (Cal.com)",
            )
            md = build_discovery_context_markdown(
                name,
                (st.get("brief") or {}).get("summary") or hb.summary or "",
                st.get("research", {}).get("key_gaps") or [],
                test_email=body.test_email,
            )
            await hubspot_client.append_note_for_contact_email(
                body.test_email,
                discovery_brief_to_hubspot_html(md),
            )
            _append_channel_event(st, "hubspot_synced", {"phase": "book_discovery"})
        except Exception as e:
            logger.warning("HubSpot update on book_discovery failed: %s", e)

    await mirror_workspace_row(body.company_id, st)

    return {
        "ok": True,
        "booking": booking,
        "channel_state": st["channel_state"],
    }


@router.get("/crm/hubspot-preview")
async def hubspot_preview(email: str):
    try:
        data = await hubspot_client.get_contact_for_dashboard(email)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if not data:
        raise HTTPException(status_code=404, detail="Contact not found — run enrich with hubspot_email or send outreach first")
    return data
