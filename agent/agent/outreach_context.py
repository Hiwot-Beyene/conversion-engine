"""
Builds signal-grounded outreach variables for the email composer.

Grounded in `tenacious_sales_data/seed/` (ICP, bench_summary.json, email_sequences, style_guide)
and the challenge brief: honesty constraints, segment-specific pitch language, no bench over-commitment.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.agent.insights import CompetitorGapBrief
from agent.enrichment import HiringSignalBrief
from agent.paths import REPO_ROOT

logger = logging.getLogger(__name__)

_BENCH_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "bench_summary.json"
_STYLE_GUIDE_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "style_guide.md"
_COLD_SEQ_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "email_sequences" / "cold.md"
_ICP_DEF_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "icp_definition.md"
_PRICING_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "pricing_sheet.md"

_style_cache: Dict[str, Tuple[float, str]] = {}


def _load_bench_summary() -> Optional[Dict[str, Any]]:
    if not _BENCH_PATH.is_file():
        logger.warning("bench_summary.json missing at %s — omit numeric capacity claims", _BENCH_PATH)
        return None
    try:
        with open(_BENCH_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Could not read bench summary: %s", e)
        return None


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _cached_file(path: Path) -> str:
    try:
        mt = path.stat().st_mtime
    except OSError:
        return ""
    key = str(path)
    old = _style_cache.get(key)
    if old and old[0] == mt:
        return old[1]
    body = _read_text(path)
    _style_cache[key] = (mt, body)
    return body


def _load_style_constraints() -> str:
    text = _cached_file(_STYLE_GUIDE_PATH)
    if not text:
        return ""
    excerpt = text[:6000].strip()
    return "FULL STYLE GUIDE (excerpt; follow literally):\n" + excerpt


def _load_icp_doc_excerpt() -> str:
    return _cached_file(_ICP_DEF_PATH)[:8000]


def _load_pricing_excerpt() -> str:
    t = _cached_file(_PRICING_PATH)
    if not t:
        return "Pricing: confirm ACV on a live call — do not quote specific dollars in Email 1."
    lines = [ln for ln in t.splitlines() if ln.strip()][:12]
    return "Pricing excerpt (do not invent numbers beyond this):\n" + "\n".join(lines)


def _load_subject_patterns() -> str:
    text = _read_text(_COLD_SEQ_PATH)
    if not text:
        return ""
    patterns = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("- `") and s.endswith("`"):
            patterns.append(s.replace("- `", "").replace("`", ""))
        if len(patterns) >= 4:
            break
    if not patterns:
        return ""
    return "Preferred subject patterns from seed cold sequence: " + " | ".join(patterns)


def _format_bench_snapshot(bench: Optional[Dict[str, Any]]) -> str:
    if not bench:
        return (
            "Internal capacity snapshot not loaded. Do not quote specific engineer counts; "
            "offer to confirm fit and availability on a short call."
        )
    stacks = bench.get("stacks") or {}
    parts: List[str] = []
    for key in ("python", "data", "ml", "go", "infra", "frontend"):
        block = stacks.get(key)
        if not isinstance(block, dict):
            continue
        n = block.get("available_engineers")
        if n is None:
            continue
        try:
            parts.append(f"{key}: {int(n)} available")
        except (TypeError, ValueError):
            continue
    if not parts:
        return "See bench summary — reference only stacks with non-zero availability; never over-commit."
    return (
        "Current snapshot of available delivery capacity (from weekly bench file; not a guarantee): "
        + "; ".join(parts)
        + ". If the prospect's stack does not match, propose a human handoff — do not invent capacity."
    )


def _clean_role_titles(roles: List[str], company_name: str) -> List[str]:
    """De-dupe scraped titles; drop repeated nav crumbs like the same line 3×."""
    out: List[str] = []
    seen: set[str] = set()
    co = (company_name or "").strip().lower()
    for r in roles:
        t = str(r).strip()
        if len(t) < 6 or len(t) > 90:
            continue
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        if co and co in tl and len(t) < 40:
            continue
        out.append(t)
        if len(out) >= 4:
            break
    return out


def _extract_job_signals(brief: HiringSignalBrief) -> Tuple[int, float, List[str]]:
    jp = brief.signals.get("job_posts")
    if not jp or jp.error:
        return 0, 0.0, []
    data = jp.data or {}
    count = int(data.get("job_count") or 0)
    vel = _safe_float(data.get("velocity_60d"), 0.0)
    roles = data.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    raw_titles = [str(r) for r in roles]
    titles = _clean_role_titles(raw_titles, brief.company_name)
    return count, vel, titles


def _geo_allowed(country: Optional[str]) -> bool:
    if not country:
        return False
    c = str(country).strip().upper()
    allowed = {"US", "USA", "GB", "UK", "DE", "FR", "IE", "NO", "SE", "FI", "DK", "NL", "CH", "AT"}
    return c in allowed


_SECTOR_ACRONYMS = frozenset(
    {"SEO", "API", "ML", "AI", "BI", "B2B", "SaaS", "SSP", "DSP", "CRM", "ERP", "IT"}
)


def _pretty_sector_label(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    s = str(raw).strip().replace("/", " / ")
    tok = s.split()[0] if s else ""
    if tok.upper() in _SECTOR_ACRONYMS:
        return s[:88].strip()
    if len(s) <= 5 and s.isupper():
        s = s.title()
    return s[:88].strip()


def _firmographics_digest_sentence(company: str, d: Dict[str, Any]) -> str:
    """One human sentence; omit absurd Crunchbase ODM headcounts."""
    sec = _pretty_sector_label(d.get("sector") or d.get("categories"))
    ec_raw = d.get("employee_count")
    ec: Optional[int] = None
    if ec_raw is not None:
        try:
            ec = int(ec_raw)
        except (TypeError, ValueError):
            ec = None
    if not sec and ec is None:
        return ""
    if ec is not None and ec >= 15:
        if sec:
            return f"Public firmographics list {company} as about a {ec}-person team in {sec}."
        return f"Public firmographics list about {ec} people at {company}."
    if ec is not None and 2 <= ec < 15:
        if sec:
            return (
                f"Public data suggests {company} is still a smaller team in {sec} "
                f"(~{ec} people in our Crunchbase sample — treat as directional)."
            )
        return f"Public data suggests a small team at {company} (~{ec} in our sample — directional only)."
    if ec is not None and ec <= 1:
        if sec:
            return (
                f"Firmographics in our sample are sparse for {company} ({sec}); "
                f"we are not leaning on headcount — the hiring snapshot matters more."
            )
        return f"Firmographics in our sample are sparse for {company}; we are leaning on hiring signals, not headcount."
    if sec:
        return f"Public data associates {company} with {sec} (headcount not reliable in our sample)."
    return ""


def _tenacious_value_sentence(segment_key: str, ai_score: int, *, job_count: int) -> str:
    """
    One prospect-facing sentence for Email 1 (cold.md sentence 3).
    Never internal instructions — safe to paste into templates and prompts.
    """
    if segment_key == "segment_1_series_a_b":
        if ai_score >= 2:
            return (
                "Tenacious embeds small senior engineering squads with US/EU time-zone overlap so roadmap "
                "and AI work keeps shipping while you hire — managed delivery, not staff aug."
            )
        return (
            "Tenacious places managed engineering pods with clear ownership when recruiting is what slows "
            "the roadmap — we typically embed in about two weeks for the right fit."
        )
    if segment_key == "segment_2_mid_market_restructure":
        return (
            "Tenacious helps teams keep delivery predictable through restructuring — dedicated pods led by "
            "a delivery manager, not a loose contractor list."
        )
    if segment_key == "segment_3_leadership_transition":
        return (
            "Tenacious is an option for dedicated offshore engineering when new technical leaders refresh "
            "how work gets staffed — we keep a first touch to a short conversation, not a deck parade."
        )
    if segment_key == "segment_4_specialized_capability":
        return (
            "Tenacious takes on specialist ML, platform, and data work as scoped projects or embedded squads "
            "once we confirm fit — higher-trust than throwing bodies at a JD."
        )
    if job_count > 0:
        return (
            "Tenacious works with B2B product teams that want accountable engineering capacity without the "
            "traditional agency experience — if that resonates, 15 minutes is enough to see if we are in the ballpark."
        )
    return (
        "Tenacious partners with B2B teams on managed engineering and project consulting — we use a short call "
        "to sanity-check fit before anyone commits calendar to a formal process."
    )


def _classify_icp(
    brief: HiringSignalBrief,
) -> Tuple[str, float, str, str, str]:
    """
    ICP precedence per seed/icp_definition.md (approximation — ODM lacks precise funding dates).
    Low confidence (<0.6) collapses to abstain for grading/schema alignment.
    """
    cb = brief.signals.get("crunchbase")
    lay = brief.signals.get("layoffs")
    ld = brief.signals.get("leadership")

    ai_score = brief.ai_maturity.integer_score if brief.ai_maturity else 0
    ai_conf = brief.ai_maturity.overall_confidence if brief.ai_maturity else 0.0

    job_count, _, roles = _extract_job_signals(brief)

    has_layoffs = bool(lay and not lay.error and lay.data.get("has_layoffs"))
    lay_pct: Optional[float] = None
    laid_off = int((lay.data or {}).get("laid_off_count") or 0) if lay and not lay.error else 0

    leadership_change = bool(ld and not ld.error and ld.data.get("recent_change"))

    funding_usd = 0.0
    employee_count: Optional[int] = None
    country: Optional[str] = None
    funding_marker = False
    sector = "Technology"
    if cb and not cb.error:
        d = cb.data or {}
        funding_usd = _safe_float(d.get("funding_amount_usd"), 0.0)
        employee_count = d.get("employee_count")
        if employee_count is not None:
            try:
                employee_count = int(employee_count)
            except (TypeError, ValueError):
                employee_count = None
        country = d.get("country")
        fr = str(d.get("funding_round") or "").lower()
        funding_marker = funding_usd > 0 or any(x in fr for x in ("series", "seed", "ipo"))
        sector = d.get("sector") or sector
        if employee_count and employee_count > 0 and laid_off > 0:
            lay_pct = min(100.0, (laid_off / max(employee_count, 1)) * 100.0)

    role_blob = " ".join(str(r).lower() for r in roles)
    specialist_keywords = (
        "ml engineer",
        "machine learning",
        "llm",
        "mlops",
        "ai engineer",
        "data scientist",
        "platform engineer",
        "vector",
        "agent",
    )
    specialist_signal = any(k in role_blob for k in specialist_keywords)
    open_specialist_roles = sum(1 for r in roles if any(k in str(r).lower() for k in specialist_keywords))
    specialist_persist = specialist_signal and open_specialist_roles >= 1 and job_count >= 3

    funded_band = 5_000_000 <= funding_usd <= 30_000_000
    headcount_s1 = employee_count is not None and 15 <= employee_count <= 80
    headcount_s2 = employee_count is not None and 200 <= employee_count <= 2000
    headcount_s3 = employee_count is not None and 50 <= employee_count <= 500
    strong_hiring = job_count >= 5
    post_layoff_hiring = job_count >= 3
    geo_ok = _geo_allowed(country)

    # 1) Layoff + funding marker => Segment 2 (cost pressure dominates)
    if has_layoffs and funding_marker and (lay_pct is None or lay_pct <= 40):
        conf = 0.72 if post_layoff_hiring else 0.45
        seg = "segment_2_mid_market_restructure"
        label = "Segment 2 — Mid-market / restructuring"
        if conf < 0.6:
            return (
                "abstain",
                conf,
                "Abstain — restructuring signal weak (post-layoff hiring not verified)",
                "Note: public workforce update",
                _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
            )
        return (
            seg,
            conf,
            label,
            "Note on public workforce update",
            _tenacious_value_sentence(seg, ai_score, job_count=job_count),
        )

    # 2) Layoffs-only mid-market proxy
    if has_layoffs and headcount_s2 and (lay_pct is None or lay_pct <= 40):
        conf = 0.68 if post_layoff_hiring else 0.5
        seg = "segment_2_mid_market_restructure"
        if conf < 0.6:
            return (
                "abstain",
                conf,
                "Abstain — Segment 2 signals incomplete",
                "Note: delivery through change",
                _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
            )
        return (
            seg,
            conf,
            "Segment 2 — Mid-market / restructuring",
            "Note on public workforce update",
            _tenacious_value_sentence(seg, ai_score, job_count=job_count),
        )

    # 3) Leadership transition
    if leadership_change and headcount_s3:
        conf = 0.75 if job_count >= 3 else 0.55
        seg = "segment_3_leadership_transition"
        if conf < 0.6:
            return (
                "abstain",
                conf,
                "Abstain — leadership signal weak",
                "Context: engineering plans",
                _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
            )
        return (
            seg,
            conf,
            "Segment 3 — Engineering leadership transition",
            "Congrats on the leadership change",
            _tenacious_value_sentence(seg, ai_score, job_count=job_count),
        )

    # 4) Specialized capability (AI ≥2 + persistent specialist hiring proxy)
    if ai_score >= 2 and specialist_persist:
        conf = min(0.88, 0.55 + 0.12 * ai_conf + (0.05 if job_count >= 5 else 0.0))
        seg = "segment_4_specialized_capability"
        if conf < 0.6:
            return (
                "abstain",
                conf,
                "Abstain — specialist signal low confidence",
                "Question: specialist hiring",
                _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
            )
        return (
            seg,
            conf,
            "Segment 4 — Specialized capability gap",
            "Question on specialist hiring",
            _tenacious_value_sentence(seg, ai_score, job_count=job_count),
        )

    # 5) Recently funded / scaling (ODM: funding amount + geo + hiring proxy)
    if (funded_band or funding_marker) and strong_hiring and headcount_s1 and geo_ok:
        conf = 0.74 if funded_band and strong_hiring else 0.52
        seg = "segment_1_series_a_b"
        if conf < 0.6:
            return (
                "abstain",
                conf,
                "Abstain — funding/hiring fit uncertain",
                "Context: hiring and growth signals",
                _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
            )
        return (
            seg,
            conf,
            "Segment 1 — Recently funded / scaling startup",
            "Context: hiring and growth signals",
            _tenacious_value_sentence(seg, ai_score, job_count=job_count),
        )

    # 6) Exploratory abstention
    return (
        "abstain",
        max(0.35, min(0.55, brief.overall_confidence * 0.55)),
        "Abstain — generic exploratory",
        "Context: public hiring snapshot",
        _tenacious_value_sentence("abstain", ai_score, job_count=job_count),
    )


def _build_email_digest(brief: HiringSignalBrief, gap: CompetitorGapBrief) -> str:
    """
    Short prose the model (or fallback template) turns into a real Email 1 — not a labeled dump.
    Aligned with tenacious_sales_data/seed/email_sequences/cold.md (signal-grounded opener).
    """
    company = brief.company_name or "the company"
    job_count, _vel, roles = _extract_job_signals(brief)
    parts: List[str] = []

    jp = brief.signals.get("job_posts")
    jp_data = (jp.data or {}) if (jp and not jp.error) else {}
    urls_attempted = jp_data.get("urls_attempted") or []
    attempted_n = len([u for u in urls_attempted if str(u).strip()])
    listing_quality = str(jp_data.get("listing_quality") or "").lower()
    sector = str(gap.sector or "").strip()

    if job_count > 0:
        if roles:
            one = roles[0]
            parts.append(
                f"Public career pages show about {job_count} engineering-related opening(s) at {company}; "
                f"one listing title is \"{one}\"."
            )
        else:
            parts.append(
                f"Public career pages show about {job_count} engineering-related opening(s) at {company}."
            )
    else:
        if attempted_n > 0:
            src_phrase = (
                f"after checking {attempted_n} public source page(s) (company careers and major job boards)"
            )
        else:
            src_phrase = "in this public crawl pass"
        parts.append(
            f"Public hiring visibility is low for {company} {src_phrase}, so we avoid hard scale claims and use a short verification question instead."
        )
        if listing_quality in ("none", "low", "medium"):
            parts.append(
                "The signal looked thin/noisy rather than absent, so the outreach should validate current priorities instead of asserting hiring pace."
            )

    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        firmo = _firmographics_digest_sentence(company, cb.data or {})
        if firmo:
            parts.append(firmo)

    lay = brief.signals.get("layoffs")
    if lay and not lay.error and lay.data.get("has_layoffs"):
        parts.append(
            "There is a matching workforce event in our public layoff dataset — if you mention it, keep the tone neutral."
        )

    ld = brief.signals.get("leadership")
    if ld and not ld.error and ld.data.get("recent_change"):
        note = (ld.data.get("change_note") or "").strip()
        if note:
            parts.append(f"Leadership signal: {note[:200]}")
        else:
            parts.append("Our enrichment flags a recent leadership change worth verifying before a congrats line.")

    if brief.ai_maturity and brief.ai_maturity.integer_score is not None:
        n = brief.ai_maturity.integer_score
        parts.append(
            f"A coarse read from public listings alone puts AI/engineering depth around {n}/3 — "
            f"enough to ask how they are thinking about it, not enough to imply they are behind peers."
        )

    if sector:
        parts.append(
            f"Current sector tag in our data is {sector}; we can tailor examples only if that still reflects your GTM and team setup."
        )

    if gap.gaps:
        g = gap.gaps[0]
        ev = (g.evidence or "")[:220].strip()
        if ev:
            parts.append(
                f"Sector peers (public signals only): {g.practice_name} — {ev}"
            )

    text = "\n\n".join(parts)
    return text[:1200].strip()


def _signal_narrative(brief: HiringSignalBrief) -> str:
    lines: List[str] = []
    lines.append(f"Company: {brief.company_name}")
    if brief.summary:
        lines.append(f"AI maturity summary: {brief.summary}")

    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        d = cb.data or {}
        if d.get("sector"):
            lines.append(f"Sector (Crunchbase ODM): {d['sector']}")
        if d.get("employee_count") is not None:
            lines.append(f"Public headcount band (approx.): {d['employee_count']}")
        fa = d.get("funding_amount_usd")
        if fa is not None and _safe_float(fa, 0) > 0:
            lines.append(f"Funding total (USD): {_safe_float(fa, 0):,.0f}")
        elif d.get("funding_round"):
            lines.append(f"IPO / funding status field: {d['funding_round']}")

    job_count, velocity, roles = _extract_job_signals(brief)
    lines.append(f"Open engineering-related roles observed: {job_count}")
    if velocity:
        lines.append(f"60d hiring velocity index: {velocity:.2f}")
    if roles:
        preview = roles[:8]
        lines.append("Sample titles: " + "; ".join(preview) + ("…" if len(roles) > 8 else ""))

    lay = brief.signals.get("layoffs")
    if lay and not lay.error and lay.data.get("has_layoffs"):
        lines.append(
            f"Layoffs.fyi snapshot: yes — latest {lay.data.get('latest_layoff_date')}, "
            f"reported {lay.data.get('laid_off_count')} people."
        )
    elif lay and not lay.error:
        lines.append("Layoffs.fyi snapshot: no matching row in sample.")

    if brief.ai_maturity:
        lines.append(
            f"AI maturity score: {brief.ai_maturity.integer_score}/3 "
            f"(normalized {brief.ai_maturity.normalized_score:.2f})."
        )

    return "\n".join(lines)


def _competitor_block(gap: CompetitorGapBrief) -> str:
    lines = [
        f"Peer sample (same sector, public signals): {len(gap.competitors_analyzed)} companies.",
        f"Prospect percentile vs sample: ~{gap.percentile_position:.0%}.",
        f"Sparse sector: {'yes' if gap.is_sparse_sector else 'no'}.",
        "Practice gaps (research framing — use as questions, not accusations):",
    ]
    for g in (gap.gaps or [])[:3]:
        lines.append(f"  • {g.practice_name}: {g.evidence}")
    return "\n".join(lines)


def _honesty_rules(job_count: int, segment_key: str, ai_score: int) -> str:
    rules: List[str] = [
        "Tenacious style: direct, grounded, honest, professional, non-condescending (see style_guide.md).",
        "Every factual claim must trace to the EMAIL DIGEST above (and your general knowledge of Tenacious), not to raw internal tables.",
        "OUTPUT IS A NORMAL OUTBOUND EMAIL: never paste internal labels (e.g. 'Crunchbase ODM', 'Layoffs.fyi snapshot', 'Peer sample', 'Practice gaps', 'AI maturity score:', '60d hiring velocity', 'percentile'). "
        "Translate facts into 3–4 short sentences a CTO would read on their phone.",
        "Never paste meta-instructions to yourself (e.g. 'one grounded observation', 'not to paste', 'research framing only', 'internal rubric'). "
        "Never paste the ANGLE line verbatim if it reads like a checklist — rewrite it as a single conversational Tenacious value sentence.",
        "No bullet lists in the body. At most two numbers. No emojis. Subject ≤ 60 chars. Body ≤ 120 words. One ask.",
        "No 'circling back', 'hope this finds you well', or 'world-class/top talent'. Do not use the word 'bench' — say 'available capacity' or 'engineers ready to deploy'.",
    ]
    if job_count < 5:
        rules.append(
            f"Job-post count is {job_count} (<5): do NOT claim aggressive hiring or rapid scale; ask whether recruiting is pacing with goals."
        )
    if segment_key == "abstain":
        rules.append("ICP abstain: no segment-specific scaling promises; stay curious and light.")
    rules.append(
        "ICP: four fixed segments (Series A/B scaling, mid-market restructure, leadership transition, specialist capability). "
        "Do not name segment codes or paste this rubric into the email."
    )
    rules.append(_load_pricing_excerpt())
    style_hint = _load_style_constraints()
    if style_hint:
        rules.append(style_hint[:4000])
    subj_hint = _load_subject_patterns()
    if subj_hint:
        rules.append(subj_hint)
    return "\n".join(rules)


def _first_digest_paragraph(digest: str, max_chars: int = 420) -> str:
    """First fact block from digest (paragraphs separated by blank lines); avoid mid-sentence truncation."""
    paras = [p.strip() for p in (digest or "").split("\n\n") if p.strip()]
    if not paras:
        return ""
    blob = paras[0]
    if len(blob) <= max_chars:
        return blob
    cut = blob[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _second_digest_paragraph(digest: str, max_chars: int = 300) -> str:
    """Second fact block from digest when available; keeps fallback email from sounding generic."""
    paras = [p.strip() for p in (digest or "").split("\n\n") if p.strip()]
    if len(paras) < 2:
        return ""
    blob = paras[1]
    if len(blob) <= max_chars:
        return blob
    cut = blob[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def _short_company(name: str, max_len: int = 26) -> str:
    n = (name or "").strip()
    if len(n) <= max_len:
        return n
    return n[: max_len - 1] + "…"


def _sector_hook(brief: HiringSignalBrief) -> str:
    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        s = (cb.data or {}).get("sector")
        if s:
            return str(s).split("/")[0].strip()[:22]
    return ""


def suggested_subject_line_for_email1(
    *,
    segment_key: str,
    company: str,
    job_count: int,
    hiring_brief: HiringSignalBrief,
    role_hook: Optional[str] = None,
) -> str:
    """
    Subject seeds aligned with tenacious_sales_data/seed/email_sequences/cold.md
    (Context / Note / Congrats / Question / Request). ≤ 60 chars, concrete hook.
    """
    co = _short_company(company, 22)
    sec = _sector_hook(hiring_brief)
    rh = (role_hook or "").strip()
    if len(rh) > 18:
        rh = rh[:17] + "…"

    if segment_key == "segment_1_series_a_b":
        if job_count > 0:
            return f"Context: {job_count} open roles — {co}"[:60]
        if sec:
            return f"Context: {sec} hiring — {co}"[:60]
        return f"Context: growth signal — {co}"[:60]

    if segment_key == "segment_2_mid_market_restructure":
        return f"Note: delivery through change — {co}"[:60]

    if segment_key == "segment_3_leadership_transition":
        return f"Congrats: quick note — {co}"[:60]

    if segment_key == "segment_4_specialized_capability":
        if rh:
            return f"Question: {rh} — {co}"[:60]
        if job_count > 0:
            return f"Question: specialist hiring — {co}"[:60]
        return f"Question: engineering pattern — {co}"[:60]

    # abstain — still sound like cold.md (Context / Question), not generic "capacity"
    if job_count > 0:
        return f"Context: {job_count} public listings — {co}"[:60]
    if sec:
        return f"Context: {sec} + hiring — {co}"[:60]
    return f"Question: engineering staffing — {co}"[:60]


def build_outreach_prompt_variables(
    hiring_brief: HiringSignalBrief,
    gap_brief: CompetitorGapBrief,
    *,
    salutation_name: str = "",
    scheduling_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Variables for compose_email.txt (str.format). All values are str except metadata dict.
    """
    segment_key, seg_conf, seg_label, subject_hint, pitch_hint = _classify_icp(hiring_brief)
    job_count, _, roles = _extract_job_signals(hiring_brief)
    ai_score = hiring_brief.ai_maturity.integer_score if hiring_brief.ai_maturity else 0
    role_hook = roles[0] if roles else None

    bench = _load_bench_summary()
    bench_line = _format_bench_snapshot(bench)
    email_digest = _build_email_digest(hiring_brief, gap_brief)
    suggested_subj = suggested_subject_line_for_email1(
        segment_key=segment_key,
        company=hiring_brief.company_name or "Prospect",
        job_count=job_count,
        hiring_brief=hiring_brief,
        role_hook=role_hook,
    )

    sched = (scheduling_url or "").strip()
    if sched and sched != "https://cal.com":
        sched_instruction = (
            f"End with a single soft ask for 15 minutes and include this scheduling URL exactly once: {sched}"
        )
    else:
        sched_instruction = (
            "End with a single soft ask for 15 minutes and ask the prospect to share two time windows next week. "
            "Do not include a placeholder or fake calendar URL."
        )

    return {
        "salutation_name": salutation_name or "",
        "company": hiring_brief.company_name,
        "job_count": job_count,
        "ai_maturity_integer": ai_score,
        "email_digest": email_digest,
        "suggested_subject_line": suggested_subj,
        "prospect_sector_public": gap_brief.sector or _sector_hook(hiring_brief) or "—",
        "signal_narrative": _signal_narrative(hiring_brief),
        "icp_segment": f"{seg_label} (confidence ~{seg_conf:.0%})",
        "segment_key": segment_key,
        "segment_confidence": f"{seg_conf:.2f}",
        "subject_line_pattern_hint": subject_hint,
        "segment_pitch_guidance": pitch_hint,
        "competitor_gap_block": _competitor_block(gap_brief),
        "bench_capacity_snapshot": bench_line,
        "honesty_constraints": _honesty_rules(job_count, segment_key, ai_score),
        "scheduling_instruction": sched_instruction,
        "metadata": {
            "icp_segment_key": segment_key,
            "icp_confidence": seg_conf,
            "weak_job_signal": job_count < 5,
            "ai_maturity_integer": ai_score,
        },
    }


def render_grounded_fallback_email(
    variables: Dict[str, Any],
    *,
    scheduling_url: str = "",
) -> Dict[str, str]:
    """
    Cold Email 1 shape per tenacious_sales_data/seed/email_sequences/cold.md — never dump raw brief fields.
    """
    company = variables.get("company", "your team")
    seg = variables.get("segment_key", "abstain")
    digest = (variables.get("email_digest") or "").strip()
    sal = (variables.get("salutation_name") or "").strip()
    greet = f"{sal}," if sal else "Hello,"
    jc = int(variables.get("job_count") or 0)
    ai = int(variables.get("ai_maturity_integer") or 0)

    sub_seed = (variables.get("suggested_subject_line") or "").strip()
    subject = sub_seed or {
        "segment_1_series_a_b": f"Context: hiring signals — {_short_company(company)}",
        "segment_2_mid_market_restructure": f"Note: delivery through change — {_short_company(company)}",
        "segment_3_leadership_transition": f"Congrats: quick note — {_short_company(company)}",
        "segment_4_specialized_capability": f"Question: engineering hiring — {_short_company(company)}",
        "abstain": f"Question: engineering staffing — {_short_company(company)}",
    }.get(seg, f"Question: engineering staffing — {_short_company(company)}")
    subject = subject[:60]

    # Four sentences + ask + signature (cold.md body structure).
    s1 = _first_digest_paragraph(digest) or f"We took a quick pass at public listings for {company}."
    if not s1.endswith((".", "?", "!")):
        s1 += "."
    if seg == "abstain":
        s2 = _second_digest_paragraph(digest) or (
            "Rather than guess from thin public signal, we use a quick verification question and then map capacity options only if timing is real."
        )
    elif seg == "segment_2_mid_market_restructure":
        s2 = (
            "After workforce headlines, many teams still need predictable delivery — we often discuss how to keep roadmaps "
            "moving without locking in fixed headcount too early."
        )
    elif seg == "segment_3_leadership_transition":
        s2 = "In the first months after a leadership change, engineering vendor mix and delivery model often get a fresh look."
    elif seg == "segment_4_specialized_capability":
        s2 = (
            "Peer companies sometimes separate generalist hiring from specialized ML/platform roles — we wanted to ask how you are thinking about that split."
        )
    else:
        s2 = (
            "At this stage, recruiting throughput is often what constrains the roadmap — not whether there is budget to hire."
        )

    tenacious_line = _tenacious_value_sentence(str(seg), ai, job_count=jc).rstrip(".") + "."

    sched = (scheduling_url or "").strip()
    if sched and sched != "https://cal.com":
        ask = f"Worth 15 minutes next week? You can grab time here: {sched}"
    else:
        ask = f"If useful, does Tuesday or Wednesday next week work for a 15-minute call about {company}?"

    body = "\n".join(
        [
            greet,
            "",
            s1,
            "",
            s2,
            "",
            tenacious_line,
            "",
            ask,
            "",
            "Research Partner",
            "Tenacious Intelligence Corporation",
            "gettenacious.com",
        ]
    )
    return {"subject": subject[:60], "body": body}
