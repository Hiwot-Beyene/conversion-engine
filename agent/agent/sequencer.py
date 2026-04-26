"""
Cold sequence E2/E3 + re-engagement — uses mirrored workspace payloads in Postgres.
Hourly tick from APScheduler in main.py.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agent.agent.prompt_loader import prompt_loader
from agent.channels.email_client import email_client
from agent.config import settings
from agent.db.database import async_session
from agent.db.models import OutboundSequenceState, ProspectWorkspace
from agent.enrichment import HiringSignalBrief
from agent.agent.insights import CompetitorGapBrief
from agent.integrations.llm_client import llm_client

logger = logging.getLogger(__name__)


async def _load_payload(cid: str) -> Dict[str, Any]:
    async with async_session() as session:
        row = await session.get(ProspectWorkspace, cid)
        if not row:
            return {}
        return dict(row.payload or {})


async def run_sequence_tick() -> None:
    """Send follow-up emails when due (best-effort; skips if kill switch or missing data)."""
    if settings.outbound_is_suppressed():
        logger.debug("Sequence tick: outbound suppressed")
        return

    now = datetime.now(timezone.utc)
    async with async_session() as session:
        res = await session.execute(select(OutboundSequenceState))
        rows = res.scalars().all()

    for st in rows:
        cid = st.crunchbase_id
        email_to = (st.prospect_email or "").strip()
        if not email_to:
            continue

        payload = await _load_payload(cid)
        if not payload.get("is_enriched"):
            continue

        try:
            hb = HiringSignalBrief.model_validate(payload["raw_brief"])
            gap = CompetitorGapBrief.model_validate(payload["raw_gap"])
        except Exception as e:
            logger.debug("Sequence skip %s: cannot restore briefs %s", cid, e)
            continue

        company = payload.get("company_name") or hb.company_name

        async with async_session() as session:
            row = await session.get(OutboundSequenceState, cid)
            if not row:
                continue

            if (
                row.e2_scheduled_at
                and row.e2_scheduled_at <= now
                and not row.e2_sent_at
            ):
                body = await _compose_followup(hb, gap, stage="e2")
                await email_client.send_email(to=email_to, subject=body["subject"], html=body["html"])
                row.e2_sent_at = now
                session.add(row)
                await session.commit()
                logger.info("Sequence E2 sent for %s", cid)

            elif (
                row.e3_scheduled_at
                and row.e3_scheduled_at <= now
                and not row.e3_sent_at
                and row.e2_sent_at
            ):
                body = await _compose_followup(hb, gap, stage="e3")
                await email_client.send_email(to=email_to, subject=body["subject"], html=body["html"])
                row.e3_sent_at = now
                row.reengage_scheduled_at = now + timedelta(days=max(1, settings.SEQUENCE_REENGAGE_DELAY_DAYS))
                session.add(row)
                await session.commit()
                logger.info("Sequence E3 sent for %s", cid)

            elif (
                row.reengage_scheduled_at
                and row.reengage_scheduled_at <= now
                and not row.reengage_sent_at
                and row.e3_sent_at
            ):
                body = await _compose_followup(hb, gap, stage="reengage")
                await email_client.send_email(to=email_to, subject=body["subject"], html=body["html"])
                row.reengage_sent_at = now
                session.add(row)
                await session.commit()
                logger.info("Sequence re-engagement sent for %s", cid)


async def _compose_followup(hb: HiringSignalBrief, gap: CompetitorGapBrief, *, stage: str) -> Dict[str, str]:
    name = hb.company_name
    sector = gap.sector
    variables = {
        "company": name,
        "sector": sector,
        "signal_summary": (hb.summary or "")[:1200],
        "gap_summary": "\n".join(f"- {g.practice_name}: {g.evidence}" for g in (gap.gaps or [])[:3]),
        "stage": stage,
    }
    try:
        prompt = prompt_loader.load_prompt(f"compose_email_{stage}", variables)
    except Exception:
        prompt = (
            f"Write a short professional follow-up email ({stage}) for {name} in {sector}. "
            f"Context:\n{variables['signal_summary']}\n\nGaps:\n{variables['gap_summary']}\n\n"
            "Subject: line then body. No calendar URL. Under 100 words."
        )
    raw = await llm_client.call(prompt=prompt, model_type="dev", json_mode=False)
    lines = raw.strip().split("\n")
    subject = lines[0].replace("Subject:", "").strip() or f"Follow-up — {name}"
    body_txt = "\n".join(lines[1:]).strip() if len(lines) > 1 else raw
    return {"subject": subject[:120], "html": body_txt.replace("\n", "<br/>")}


async def schedule_sequence_after_e1(crunchbase_id: str, prospect_email: str) -> None:
    """Call after Email 1 send to queue E2/E3."""
    now = datetime.now(timezone.utc)
    e2 = now + timedelta(days=max(1, settings.SEQUENCE_E2_DELAY_DAYS))
    e3 = e2 + timedelta(days=max(1, settings.SEQUENCE_E3_DELAY_DAYS))
    async with async_session() as session:
        stmt = (
            insert(OutboundSequenceState)
            .values(
                crunchbase_id=crunchbase_id,
                prospect_email=prospect_email,
                stage="e1_sent",
                e1_sent_at=now,
                e2_scheduled_at=e2,
                e3_scheduled_at=e3,
            )
            .on_conflict_do_update(
                index_elements=[OutboundSequenceState.crunchbase_id],
                set_={
                    "prospect_email": prospect_email,
                    "e1_sent_at": now,
                    "e2_scheduled_at": e2,
                    "e3_scheduled_at": e3,
                    "e2_sent_at": None,
                    "e3_sent_at": None,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()
