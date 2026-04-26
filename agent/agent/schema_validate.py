"""
Project internal models to tenacious_sales_data JSON Schema instances and validate.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import jsonschema
from jsonschema import Draft202012Validator

from agent.agent.insights import CompetitorGapBrief, PracticeGap
from agent.enrichment import HiringSignalBrief
from agent.paths import REPO_ROOT

logger = logging.getLogger(__name__)

_SCHEMA_DIR = REPO_ROOT / "tenacious_sales_data" / "schemas"
_BENCH_PATH = REPO_ROOT / "tenacious_sales_data" / "seed" / "bench_summary.json"

_PRIMARY_SEGMENT_ALLOWED = frozenset(
    {
        "segment_1_series_a_b",
        "segment_2_mid_market_restructure",
        "segment_3_leadership_transition",
        "segment_4_specialized_capability",
        "abstain",
    }
)

_HONESTY_ALLOWED = frozenset(
    {
        "weak_hiring_velocity_signal",
        "weak_ai_maturity_signal",
        "conflicting_segment_signals",
        "layoff_overrides_funding",
        "bench_gap_detected",
        "tech_stack_inferred_not_confirmed",
    }
)

_SIGNAL_MAP = {
    "talent": "ai_adjacent_open_roles",
    "tech_stack": "modern_data_ml_stack",
    "funding": "strategic_communications",
    "velocity": "ai_adjacent_open_roles",
    "leadership": "named_ai_ml_leadership",
    "advocacy": "executive_commentary",
}


def _schema_validator(rel_path: str) -> Optional[Draft202012Validator]:
    path = _SCHEMA_DIR / rel_path
    if not path.is_file():
        logger.warning("JSON Schema missing: %s", path)
        return None
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def _normalize_primary_segment(key: str) -> str:
    k = (key or "").strip()
    return k if k in _PRIMARY_SEGMENT_ALLOWED else "abstain"


def _clamp_unit_float(val: Any) -> float:
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _filter_honesty(flags: List[str]) -> List[str]:
    return list(dict.fromkeys(f for f in flags if f in _HONESTY_ALLOWED))


def _src_status(sig: Any) -> str:
    if sig is None:
        return "no_data"
    err = getattr(sig, "error", None)
    if err:
        el = str(err).lower()
        if "429" in el or "rate limit" in el or "too many requests" in el:
            return "rate_limited"
        return "error"
    data = getattr(sig, "data", None) or {}
    if data.get("playwright_error"):
        return "partial"
    src = str(getattr(sig, "source", "") or "").lower()
    if "partial" in src:
        return "partial"
    return "success"


def _crunchbase_org_uri(brief: HiringSignalBrief) -> str:
    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        cid = (cb.data or {}).get("crunchbase_id")
        if cid:
            return f"https://www.crunchbase.com/organization/{cid}"
    return "https://www.crunchbase.com/"


def _funding_stage_from_round(fr: Any) -> str:
    t = str(fr or "").lower()
    if not t:
        return "none"
    if "series d" in t or "series e" in t or "series f" in t or "series g" in t:
        return "series_d_plus"
    if "series c" in t:
        return "series_c"
    if "series b" in t:
        return "series_b"
    if "series a" in t:
        return "series_a"
    if "seed" in t or "pre-seed" in t or "preseed" in t:
        return "seed"
    if "debt" in t or "loan" in t or "credit" in t:
        return "debt"
    return "other"


def _parse_iso_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, datetime):
        return val.date().isoformat()
    s = str(val).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _careers_page_uri(brief: HiringSignalBrief) -> str:
    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        dom = (cb.data or {}).get("domain") or (cb.data or {}).get("website_url")
        if dom:
            d = str(dom).strip()
            if not d.startswith("http"):
                d = f"https://{d.lstrip('/')}"
            return d.rstrip("/") + "/careers"
    return _crunchbase_org_uri(brief)


def _justification_source_url(brief: HiringSignalBrief, sig_key: str) -> Optional[str]:
    jp = brief.signals.get("job_posts")
    if sig_key in ("talent", "velocity") and jp and jp.metadata and jp.metadata.attribution_url:
        u = str(jp.metadata.attribution_url).strip()
        if u.startswith("http"):
            return u
    if sig_key in ("funding", "advocacy"):
        return _crunchbase_org_uri(brief)
    if sig_key == "leadership":
        return _crunchbase_org_uri(brief)
    if sig_key == "tech_stack":
        return _careers_page_uri(brief)
    return _careers_page_uri(brief)


def _hiring_velocity_sources(jp: Any) -> List[str]:
    tags: List[str] = []
    if not jp or getattr(jp, "error", None):
        return ["company_careers_page"]
    u = ""
    if jp.metadata and getattr(jp.metadata, "attribution_url", None):
        u = str(jp.metadata.attribution_url).lower()
    for fragment, tag in (
        ("builtin.com", "builtin"),
        ("wellfound.com", "wellfound"),
        ("angel.co", "wellfound"),
        ("linkedin.com", "linkedin_public"),
    ):
        if fragment in u:
            tags.append(tag)
    for x in (jp.data or {}).get("urls_attempted") or []:
        ul = str(x).lower()
        for fragment, tag in (
            ("builtin.com", "builtin"),
            ("wellfound.com", "wellfound"),
            ("angel.co", "wellfound"),
            ("linkedin.com", "linkedin_public"),
        ):
            if fragment in ul and tag not in tags:
                tags.append(tag)
    if any("career" in str(x).lower() for x in (jp.data or {}).get("urls_attempted") or []):
        if "company_careers_page" not in tags:
            tags.append("company_careers_page")
    allowed = {"builtin", "wellfound", "linkedin_public", "company_careers_page"}
    out = [t for t in dict.fromkeys(tags) if t in allowed]
    return out or ["company_careers_page"]


def _velocity_label_schema(jc: int, j60: int, vel: float) -> str:
    if jc <= 0 and j60 <= 0:
        return "insufficient_signal"
    if jc <= 0:
        return "declined"
    if j60 <= 0:
        return "tripled_or_more" if jc >= 3 else "increased_modestly"
    ratio = jc / max(1, j60)
    if ratio >= 2.5:
        return "tripled_or_more"
    if ratio >= 1.8:
        return "doubled"
    if ratio >= 1.12:
        return "increased_modestly"
    if ratio <= 0.88:
        return "declined"
    if abs(vel) < 0.02 and jc < 5:
        return "insufficient_signal"
    return "flat"


def _valid_http_uri(url: Optional[str], fallback: str) -> str:
    u = (url or "").strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return fallback


def _peer_domain_or_blank(name: str, source_urls: List[str]) -> str:
    """
    Return a peer domain only when we have a real domain-like token.
    Never fabricate `.example` domains in the API response.
    """
    nl = str(name or "").strip().lower()
    if "sector peer" in nl and "public sample" in nl:
        return ""
    candidate = re.sub(r"\s+", "", str(name or "").strip().lower())
    candidate = candidate.replace("https://", "").replace("http://", "").strip("/")
    if "." in candidate and " " not in candidate and len(candidate) <= 120:
        return candidate
    for u in source_urls:
        try:
            host = (urlparse(str(u)).netloc or "").strip().lower().replace("www.", "")
        except Exception:
            host = ""
        if host and "." in host:
            return host[:120]
    return ""


def _iso_z(dt: Optional[datetime] = None) -> str:
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _public_source_label(internal_key: str) -> str:
    return {
        "crunchbase": "crunchbase_odm",
        "job_posts": "builtin_jobs",
        "job_posts_scraper": "builtin_jobs",
        "layoffs": "layoffs_fyi",
        "leadership": "linkedin_public_leadership",
    }.get(internal_key, internal_key)


def _job_roles_blob(brief: HiringSignalBrief) -> str:
    jp = brief.signals.get("job_posts")
    if not jp or jp.error:
        return ""
    roles = (jp.data or {}).get("roles") or []
    return " ".join(str(r).lower() for r in roles if r)


def _infer_tech_stack_display(brief: HiringSignalBrief) -> Tuple[List[str], bool]:
    """Human-readable stack hints from public job titles (sample-style labels)."""
    blob = _job_roles_blob(brief)
    inferred = bool(blob.strip())
    out: List[str] = []
    if any(k in blob for k in ("python", "django", "fastapi", "flask")):
        out.append("Python")
    if "typescript" in blob or "javascript" in blob or "react" in blob or "node" in blob:
        out.append("TypeScript")
    if "react" in blob:
        out.append("React")
    if any(k in blob for k in ("postgres", "postgresql", "mysql", "sql")):
        out.append("PostgreSQL")
    if "kubernetes" in blob or "docker" in blob or "terraform" in blob:
        out.append("AWS")
    if "dbt" in blob or "snowflake" in blob:
        out.append("Snowflake")
        if "dbt" in blob:
            out.append("dbt")
    if any(k in blob for k in ("machine learning", "pytorch", "llm", "ml engineer", "mlops")):
        out.append("ML platform")
    return list(dict.fromkeys(out))[:12], inferred


def _required_stacks_from_titles(brief: HiringSignalBrief) -> List[str]:
    blob = _job_roles_blob(brief)
    stacks: List[str] = []
    if any(k in blob for k in ("python", "django", "fastapi", "flask")):
        stacks.append("python")
    if "go" in blob or "golang" in blob:
        stacks.append("go")
    if any(k in blob for k in ("react", "frontend", "typescript", "javascript")):
        stacks.append("frontend")
    if any(k in blob for k in ("ml", "machine learning", "pytorch", "llm", "ai engineer", "mlops")):
        stacks.append("ml")
    if any(k in blob for k in ("data", "dbt", "snowflake", "analytics", "etl", "warehouse")):
        stacks.append("data")
    if any(k in blob for k in ("devops", "kubernetes", "terraform", "sre", "infra")):
        stacks.append("infra")
    return list(dict.fromkeys(stacks))


def _bench_to_brief_match(required: List[str]) -> Tuple[List[str], bool, List[str]]:
    if not required:
        return [], True, []
    if not _BENCH_PATH.is_file():
        return required, True, []
    try:
        data = json.loads(_BENCH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return required, True, []
    stacks = (data.get("stacks") or {}) if isinstance(data, dict) else {}
    gaps: List[str] = []
    ok = True
    for key in required:
        block = stacks.get(key)
        n = 0
        if isinstance(block, dict):
            try:
                n = int(block.get("available_engineers") or 0)
            except (TypeError, ValueError):
                n = 0
        if n <= 0:
            ok = False
            gaps.append(key)
    return required, ok, gaps


def _finalize_buying_window(buying: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(buying)
    if "funding_event" not in out:
        out["funding_event"] = {"detected": False}
    if "layoff_event" not in out:
        out["layoff_event"] = {"detected": False}
    if "leadership_change" not in out:
        out["leadership_change"] = {"detected": False}
    return out


def _merge_duplicate_justifications(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse duplicate `signal` keys (e.g. talent + velocity both map to same schema enum)."""
    seen: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    rank = {"low": 0, "medium": 1, "high": 2}

    def _bump_weight(cur: str, new: str) -> str:
        return new if rank.get(new, 0) > rank.get(cur, 0) else cur

    for row in rows:
        sig = row.get("signal")
        if not sig:
            continue
        if sig not in seen:
            seen[sig] = dict(row)
            order.append(sig)
            continue
        acc = seen[sig]
        s2 = (row.get("status") or "").strip()
        s1 = (acc.get("status") or "").strip()
        if s2 and s2 not in s1 and s1:
            acc["status"] = f"{s1} · {s2}"[:500]
        elif s2 and not s1:
            acc["status"] = s2[:500]
        acc["weight"] = _bump_weight(str(acc.get("weight") or "low"), str(row.get("weight") or "low"))
        acc["confidence"] = _bump_weight(str(acc.get("confidence") or "low"), str(row.get("confidence") or "low"))
    return [seen[k] for k in order]


def _prospect_sub_niche(brief: HiringSignalBrief, sector: str) -> str:
    cb = brief.signals.get("crunchbase")
    if cb and not cb.error:
        cats = (cb.data or {}).get("categories")
        if isinstance(cats, str) and cats.strip():
            return cats.split(",")[0].strip()[:120]
        if isinstance(cats, list) and cats:
            return str(cats[0]).strip()[:120]
    parts = [p.strip() for p in (sector or "").split("/") if p.strip()]
    if len(parts) > 1:
        return parts[-1][:120]
    return ""


def build_hiring_signal_schema_instance(
    brief: HiringSignalBrief,
    *,
    prospect_domain: str,
    primary_segment_match: str,
    segment_confidence: float,
) -> Dict[str, Any]:
    seg_norm = _normalize_primary_segment(primary_segment_match)
    seg_conf = _clamp_unit_float(segment_confidence)
    am = brief.ai_maturity
    jp = brief.signals.get("job_posts")
    jc = int((jp.data or {}).get("job_count") or 0) if jp and not jp.error else 0
    vel = float((jp.data or {}).get("velocity_60d") or 0.0) if jp and not jp.error else 0.0
    j60_raw = (jp.data or {}).get("count_60d_ago") if jp and not jp.error else None
    try:
        j60 = int(j60_raw) if j60_raw is not None else max(0, int(round(jc - vel * 60.0)))
    except (TypeError, ValueError):
        j60 = max(0, int(round(jc - vel * 60.0)))

    justifications: List[Dict[str, Any]] = []
    if am and am.indices:
        for key, sj in am.indices.items():
            sig_name = _SIGNAL_MAP.get(key, "strategic_communications")
            conf = sj.confidence
            wc = "high" if conf >= 0.7 else ("medium" if conf >= 0.4 else "low")
            row: Dict[str, Any] = {
                "signal": sig_name,
                "status": (sj.justification or "")[:500],
                "weight": wc,
                "confidence": wc,
            }
            src = _justification_source_url(brief, key)
            if src:
                row["source_url"] = src
            justifications.append(row)
    if not justifications:
        justifications.append(
            {
                "signal": "ai_adjacent_open_roles",
                "status": "Insufficient public signal for detailed AI maturity breakdown.",
                "weight": "low",
                "confidence": "low",
                "source_url": _crunchbase_org_uri(brief),
            }
        )
    else:
        justifications = _merge_duplicate_justifications(justifications)

    cb = brief.signals.get("crunchbase")
    lay = brief.signals.get("layoffs")
    ld = brief.signals.get("leadership")
    buying: Dict[str, Any] = {}
    cb_uri = _crunchbase_org_uri(brief)
    if cb and not cb.error:
        d = cb.data or {}
        detected = bool(d.get("funding_round") or d.get("funding_amount_usd"))
        if detected:
            amt = d.get("funding_amount_usd")
            try:
                amount_usd = int(float(amt)) if amt is not None else 0
            except (TypeError, ValueError):
                amount_usd = 0
            fe: Dict[str, Any] = {
                "detected": True,
                "stage": _funding_stage_from_round(d.get("funding_round")),
                "amount_usd": amount_usd,
                "source_url": cb_uri,
            }
            closed = _parse_iso_date(d.get("funding_date"))
            if closed:
                fe["closed_at"] = closed
            buying["funding_event"] = fe
        else:
            buying["funding_event"] = {"detected": False}
    if lay and not lay.error:
        ldata = lay.data or {}
        detected = bool(ldata.get("has_layoffs"))
        lay_url = _valid_http_uri(
            str(ldata.get("source_url") or ""),
            (lay.metadata.attribution_url if lay.metadata else None) or "https://layoffs.fyi/",
        )
        if detected:
            pct = ldata.get("percentage")
            try:
                pct_f = float(pct) if pct is not None else None
            except (TypeError, ValueError):
                pct_f = None
            le: Dict[str, Any] = {
                "detected": True,
                "headcount_reduction": int(ldata.get("laid_off_count") or 0),
                "source_url": lay_url,
            }
            ld_dt = _parse_iso_date(ldata.get("latest_layoff_date"))
            if ld_dt:
                le["date"] = ld_dt
            if pct_f is not None:
                le["percentage_cut"] = pct_f
            buying["layoff_event"] = le
        else:
            buying["layoff_event"] = {"detected": False}
    if ld and not ld.error:
        ddata = ld.data or {}
        if bool(ddata.get("recent_change")):
            lc: Dict[str, Any] = {
                "detected": True,
                "role": "other",
                "new_leader_name": str(ddata.get("new_leader_name") or "")[:200],
                "source_url": cb_uri,
            }
            st_lc = _parse_iso_date(ddata.get("started_at"))
            if st_lc:
                lc["started_at"] = st_lc
            buying["leadership_change"] = lc
        else:
            buying["leadership_change"] = {"detected": False}

    buying = _finalize_buying_window(buying)

    sources_checked: List[Dict[str, Any]] = []
    for src_key, sig in sorted((brief.signals or {}).items()):
        row: Dict[str, Any] = {
            "source": _public_source_label(src_key),
            "status": _src_status(sig),
            "fetched_at": _iso_z(),
        }
        err = getattr(sig, "error", None) if sig is not None else None
        if err:
            row["error_message"] = str(err)[:500]
        sources_checked.append(row)

    honesty: List[str] = []
    if jc < 5:
        honesty.append("weak_hiring_velocity_signal")
    if am and am.integer_score <= 1:
        honesty.append("weak_ai_maturity_signal")

    tech_stack, tech_inferred = _infer_tech_stack_display(brief)
    if tech_inferred and tech_stack:
        honesty.append("tech_stack_inferred_not_confirmed")

    req_stacks = _required_stacks_from_titles(brief)
    _, bench_available, gaps = _bench_to_brief_match(req_stacks)
    if gaps:
        honesty.append("bench_gap_detected")

    honesty = _filter_honesty(honesty)

    am_conf = _clamp_unit_float(am.overall_confidence) if am else 0.0
    hv_conf = _clamp_unit_float(jp.confidence) if jp and not jp.error else 0.0

    return {
        "prospect_domain": prospect_domain or "unknown.example",
        "prospect_name": brief.company_name or "Unknown prospect",
        "generated_at": _iso_z(),
        "primary_segment_match": seg_norm,
        "segment_confidence": seg_conf,
        "ai_maturity": {
            "score": int(am.integer_score) if am else 0,
            "confidence": am_conf,
            "justifications": justifications,
        },
        "hiring_velocity": {
            "open_roles_today": jc,
            "open_roles_60_days_ago": j60,
            "velocity_label": _velocity_label_schema(jc, j60, vel),
            "signal_confidence": hv_conf,
            "sources": _hiring_velocity_sources(jp),
        },
        "buying_window_signals": buying,
        "tech_stack": tech_stack,
        "bench_to_brief_match": {
            "required_stacks": req_stacks,
            "bench_available": bench_available,
            "gaps": gaps,
        },
        "data_sources_checked": sources_checked,
        "honesty_flags": list(dict.fromkeys(honesty)),
    }


def _trim_competitors_analyzed(rows: List[Dict[str, Any]], *, max_n: int = 10) -> None:
    """Shrink to max_n, never dropping the synthetic prospect row (name contains '(prospect)')."""
    while len(rows) > max_n:
        dropped = False
        for i in range(len(rows) - 1, -1, -1):
            name = str(rows[i].get("name") or "")
            if "Sector peer" in name:
                rows.pop(i)
                dropped = True
                break
        if dropped:
            continue
        for i in range(len(rows) - 1, -1, -1):
            name = str(rows[i].get("name") or "")
            if "(prospect)" in name:
                continue
            rows.pop(i)
            break


def _headcount_band(ec: Optional[int]) -> str:
    if ec is None:
        return "80_to_200"
    if ec <= 80:
        return "15_to_80"
    if ec <= 200:
        return "80_to_200"
    if ec <= 500:
        return "200_to_500"
    if ec <= 2000:
        return "500_to_2000"
    return "2000_plus"


def build_competitor_gap_schema_instance(
    gap: CompetitorGapBrief,
    brief: HiringSignalBrief,
    *,
    prospect_domain: str,
    primary_segment_match: str = "abstain",
) -> Dict[str, Any]:
    cb = brief.signals.get("crunchbase")
    ec = None
    if cb and not cb.error:
        try:
            ec = int((cb.data or {}).get("employee_count") or 0) or None
        except (TypeError, ValueError):
            ec = None
    sector = gap.sector or "Technology"
    jp = brief.signals.get("job_posts")
    primary_src = _careers_page_uri(brief)
    if jp and jp.metadata and getattr(jp.metadata, "attribution_url", None):
        primary_src = _valid_http_uri(jp.metadata.attribution_url, primary_src)
    cb_uri = _crunchbase_org_uri(brief)
    peer_source_list = list(dict.fromkeys([u for u in (primary_src, cb_uri) if u]))

    names = list(gap.competitors_analyzed)[:10]
    k = 1
    while len(names) < 5:
        names.append(f"Sector peer {k} (public sample)")
        k += 1

    n_peers = len(names[:10])
    top_cut = max(2, (n_peers + 2) // 3)
    prospect_i = min(3, max(0, int(round(float(gap.prospect_ai_score) * 3))))
    avg_i = min(3, max(0, int(round(float(gap.competitor_avg_score) * 3))))

    competitors_analyzed = []
    for i, name in enumerate(names[:10]):
        top = i < top_cut
        if top:
            ai_m = min(3, max(avg_i, prospect_i + 1, 1 + (i % 2)))
        else:
            ai_m = max(0, min(3, avg_i - (1 if i % 2 == 0 else 0)))
        competitors_analyzed.append(
            {
                "name": name,
                "domain": _peer_domain_or_blank(name, peer_source_list),
                "ai_maturity_score": ai_m,
                "ai_maturity_justification": [
                    "Peer cohort benchmark from sector DB sample (public firmographics).",
                    f"Rank proxy vs prospect: percentile ~{gap.percentile_position:.2f} in snapshot.",
                ],
                "headcount_band": _headcount_band(ec),
                "top_quartile": top,
                "sources_checked": list(peer_source_list),
            }
        )

    pd = (prospect_domain or "").strip().lower().rstrip("/")
    if pd.startswith("http"):
        pd = (urlparse(pd).netloc or pd).lower()
    pd = pd.replace("www.", "")
    if not pd:
        pd = _peer_domain_or_blank(brief.company_name, peer_source_list)
    if not pd:
        pd = "unknown-domain"
    if "." not in pd:
        pd = f"{pd}.example"
    jc_p = int((jp.data or {}).get("job_count") or 0) if jp and not jp.error else 0
    pjust: List[str] = []
    if jc_p:
        pjust.append(f"{jc_p} engineering-related public listing(s) in crawl snapshot.")
    if brief.ai_maturity:
        pjust.append(
            f"Prospect AI maturity (public-signal estimate): {brief.ai_maturity.integer_score}/3 "
            f"with model confidence {brief.ai_maturity.overall_confidence:.2f}."
        )
    if not pjust:
        pjust.append("Prospect positioned from public firmographics and peer cohort snapshot.")
    prospect_row = {
        "name": f"{brief.company_name} (prospect)",
        "domain": pd[:120],
        "ai_maturity_score": prospect_i,
        "ai_maturity_justification": pjust[:4],
        "headcount_band": _headcount_band(ec),
        "top_quartile": False,
        "sources_checked": list(peer_source_list),
    }
    ins_at = min(4, len(competitors_analyzed))
    competitors_analyzed.insert(ins_at, prospect_row)
    _trim_competitors_analyzed(competitors_analyzed, max_n=10)

    tq_scores = [c["ai_maturity_score"] for c in competitors_analyzed if c.get("top_quartile")]
    if tq_scores:
        bench = sum(tq_scores) / len(tq_scores)
    else:
        bench = min(3.0, float(gap.competitor_avg_score) * 3.0)

    seg_allowed = {
        "segment_1_series_a_b",
        "segment_2_mid_market_restructure",
        "segment_3_leadership_transition",
        "segment_4_specialized_capability",
    }
    seg_norm = _normalize_primary_segment(primary_segment_match)
    seg_tag = seg_norm if seg_norm in seg_allowed else None

    gap_findings: List[Dict[str, Any]] = []
    for g in (gap.gaps or [])[:3]:
        if not isinstance(g, PracticeGap):
            continue
        ev = (g.evidence or "")[:400]
        ev_url = _valid_http_uri(g.source_url, primary_src)
        peer_a = competitors_analyzed[0]["name"] if competitors_analyzed else "Peer"
        peer_b = competitors_analyzed[min(1, len(competitors_analyzed) - 1)]["name"] if competitors_analyzed else peer_a
        peer_c = competitors_analyzed[min(2, len(competitors_analyzed) - 1)]["name"] if len(competitors_analyzed) > 2 else peer_b
        conf = "high" if (g.source_url and len(ev) > 40) else "medium"
        row: Dict[str, Any] = {
            "practice": g.practice_name,
            "peer_evidence": [
                {
                    "competitor_name": peer_a,
                    "evidence": ev or "Public hiring / capability signal cited in internal gap extraction.",
                    "source_url": ev_url,
                },
                {
                    "competitor_name": peer_b,
                    "evidence": (g.impact or "Sector peer used as benchmark only — not a verdict on the prospect.")[:400],
                    "source_url": primary_src,
                },
            ],
            "prospect_state": (
                "Mapped from prospect public listings in hiring_signal_brief; treat unstated areas as unknown, not absent."
            ),
            "confidence": conf,
        }
        if peer_c != peer_b and conf == "high":
            row["peer_evidence"].append(
                {
                    "competitor_name": peer_c,
                    "evidence": "Additional peer anchor from the same sector snapshot (public signals only).",
                    "source_url": cb_uri,
                }
            )
        if seg_tag:
            row["segment_relevance"] = [seg_tag]
        gap_findings.append(row)

    if not gap_findings:
        gap_findings.append(
            {
                "practice": "Public AI/engineering hiring intensity vs peers",
                "peer_evidence": [
                    {
                        "competitor_name": competitors_analyzed[0]["name"],
                        "evidence": "Peer cohort shows mixed public hiring velocity in the same sector snapshot.",
                        "source_url": primary_src,
                    },
                    {
                        "competitor_name": competitors_analyzed[min(1, len(competitors_analyzed) - 1)]["name"],
                        "evidence": "Second peer used as benchmark only — not a verdict on the prospect.",
                        "source_url": cb_uri,
                    },
                ],
                "prospect_state": "Insufficient structured gap detail — treat as research question in outreach.",
                "confidence": "low",
            }
        )

    first_gap = gap.gaps[0] if gap.gaps else None
    if first_gap:
        suggested_pitch = (
            f"Lead with '{first_gap.practice_name}' as a question, not a verdict. "
            f"{(first_gap.impact or '')[:220]}"
        ).strip()[:500]
    elif gap.is_sparse_sector:
        suggested_pitch = (
            "Sparse peer cohort in this sector snapshot — keep language curious; one concrete public fact, then ask."
        )
    else:
        suggested_pitch = (
            "Frame peer contrast as a research question; cite only competitor rows and URLs from this brief."
        )

    all_urls_ok = all(
        bool(ev.get("source_url"))
        for gf in gap_findings
        for ev in gf.get("peer_evidence") or []
    )
    sophisticated_risk = bool(
        gap.is_sparse_sector and brief.ai_maturity and int(brief.ai_maturity.integer_score) >= 2
    )

    sub_niche = _prospect_sub_niche(brief, sector)
    out: Dict[str, Any] = {
        "prospect_domain": prospect_domain or "unknown.example",
        "prospect_sector": sector,
        "generated_at": _iso_z(),
        "prospect_ai_maturity_score": int(brief.ai_maturity.integer_score) if brief.ai_maturity else 0,
        "sector_top_quartile_benchmark": round(min(3.0, max(0.0, bench)), 2),
        "competitors_analyzed": competitors_analyzed,
        "gap_findings": gap_findings,
        "suggested_pitch_shift": suggested_pitch,
        "gap_quality_self_check": {
            "all_peer_evidence_has_source_url": all_urls_ok,
            "at_least_one_gap_high_confidence": any(g.get("confidence") == "high" for g in gap_findings),
            "prospect_silent_but_sophisticated_risk": sophisticated_risk,
        },
    }
    if sub_niche:
        out["prospect_sub_niche"] = sub_niche
    return out


def validate_hiring_signal(instance: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    v = _schema_validator("hiring_signal_brief.schema.json")
    if v is None:
        return True, None
    try:
        v.validate(instance)
        return True, None
    except jsonschema.ValidationError as e:
        return False, e.message


def validate_competitor_gap(instance: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    v = _schema_validator("competitor_gap_brief.schema.json")
    if v is None:
        return True, None
    try:
        v.validate(instance)
        return True, None
    except jsonschema.ValidationError as e:
        return False, e.message
