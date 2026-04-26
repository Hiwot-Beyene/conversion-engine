"""
Crunchbase ODM sample (CSV) — source of truth for challenge firmographics.

Column semantics match Bright Data / Crunchbase sample exports:
- id: organization permalink slug (NOT transferable to BuiltIn/Wellfound URL slugs)
- name, website, about, industries (JSON), num_employees, location, country_code, ipo_status, founders, etc.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any, Dict, Optional

import pandas as pd

from agent.config import settings
from agent.enrichment import EnrichmentSignal, SignalMetadata
from agent.paths import resolve_repo_path

logger = logging.getLogger(__name__)


def _parse_employee_band(val: Any) -> Optional[int]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    m = re.search(r"\d+", str(val))
    return int(m.group()) if m else None


def _parse_industry(val: Any) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        ind = json.loads(str(val))
        if isinstance(ind, list) and ind:
            return ind[0].get("value")
    except (json.JSONDecodeError, TypeError):
        pass
    return None


@lru_cache(maxsize=1)
def _load_odm_dataframe() -> Optional[pd.DataFrame]:
    path = resolve_repo_path(settings.CRUNCHBASE_CSV_PATH)
    if not path.is_file():
        logger.error("Crunchbase ODM CSV not found at %s", path)
        return None
    try:
        return pd.read_csv(path, low_memory=False)
    except Exception as e:
        logger.error("Failed to read Crunchbase CSV: %s", e)
        return None


def get_odm_row_by_id(crunchbase_id: str) -> Optional[pd.Series]:
    """Lookup one company by ODM `id` (permalink slug)."""
    df = _load_odm_dataframe()
    if df is None or "id" not in df.columns:
        return None
    mid = df["id"].astype(str) == str(crunchbase_id)
    hits = df[mid]
    if hits.empty:
        return None
    return hits.iloc[0]


def website_to_display_domain(website: Any) -> Optional[str]:
    """Keep raw website string for Playwright; normalize for DB-style domain field."""
    if website is None or (isinstance(website, float) and pd.isna(website)):
        return None
    s = str(website).strip()
    if not s:
        return None
    if s.startswith("http"):
        from urllib.parse import urlparse

        host = urlparse(s).netloc
        return host[4:] if host.startswith("www.") else host or None
    return s[4:] if s.startswith("www.") else s


def enrichment_signal_from_odm_row(row: pd.Series, confidence: float = 1.0) -> EnrichmentSignal:
    """Build EnrichmentSignal from a CSV row (public ODM)."""
    cid = str(row["id"])
    name = str(row["name"])
    raw_site = row.get("website")
    domain = website_to_display_domain(raw_site)
    about = row.get("about")
    if about is not None and not (isinstance(about, float) and pd.isna(about)):
        desc = str(about)[:8000]
    else:
        desc = None

    founders_raw = row.get("founders")
    founders: Any = []
    if founders_raw is not None and not (isinstance(founders_raw, float) and pd.isna(founders_raw)):
        try:
            founders = json.loads(str(founders_raw))
        except (json.JSONDecodeError, TypeError):
            founders = []

    meta = SignalMetadata(
        attribution_url=f"https://www.crunchbase.com/organization/{cid}",
        evidence_strength=1.0,
    )
    return EnrichmentSignal(
        source="crunchbase_odm_csv",
        confidence=confidence,
        metadata=meta,
        data={
            "crunchbase_id": cid,
            "name": name,
            "domain": domain,
            "website_url": str(raw_site).strip() if raw_site is not None and not (isinstance(raw_site, float) and pd.isna(raw_site)) else None,
            "description": desc,
            "employee_count": _parse_employee_band(row.get("num_employees")),
            "sector": _parse_industry(row.get("industries")),
            "funding_round": str(row["ipo_status"]) if pd.notnull(row.get("ipo_status")) else None,
            "funding_amount_usd": None,
            "location": str(row["location"]) if pd.notnull(row.get("location")) else None,
            "country": str(row["country_code"]) if "country_code" in row.index and pd.notnull(row.get("country_code")) else None,
            "social_links": row.get("social_media_links"),
            "founders": founders if isinstance(founders, list) else [],
        },
    )
