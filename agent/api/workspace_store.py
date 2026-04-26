"""
Postgres mirror for dashboard in-memory `_workspace` (recovery after restart).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from agent.db.database import async_session
from agent.db.models import ProspectWorkspace

logger = logging.getLogger(__name__)


def _serialize_workspace_entry(st: Dict[str, Any]) -> Dict[str, Any]:
    """Strip non-JSON objects (Pydantic models) from a workspace row for persistence."""
    raw_brief = st.get("raw_brief")
    raw_gap = st.get("raw_gap")
    out = {k: v for k, v in st.items() if k not in ("raw_brief", "raw_gap")}
    if raw_brief is not None and hasattr(raw_brief, "model_dump"):
        out["raw_brief"] = raw_brief.model_dump(mode="json")
    if raw_gap is not None and hasattr(raw_gap, "model_dump"):
        out["raw_gap"] = raw_gap.model_dump(mode="json")
    return out


async def mirror_workspace_row(crunchbase_id: str, st: Dict[str, Any]) -> None:
    try:
        payload = _serialize_workspace_entry(st)
        async with async_session() as session:
            stmt = (
                insert(ProspectWorkspace)
                .values(crunchbase_id=crunchbase_id, payload=payload)
                .on_conflict_do_update(
                    index_elements=[ProspectWorkspace.crunchbase_id],
                    set_={"payload": payload},
                )
            )
            await session.execute(stmt)
            await session.commit()
    except Exception as e:
        logger.warning("ProspectWorkspace mirror failed for %s: %s", crunchbase_id, e)


async def load_all_mirrored() -> Dict[str, Dict[str, Any]]:
    """Returns {crunchbase_id: payload} for rehydrate. Does not restore Pydantic models."""
    try:
        async with async_session() as session:
            res = await session.execute(select(ProspectWorkspace))
            rows = res.scalars().all()
            return {r.crunchbase_id: dict(r.payload or {}) for r in rows}
    except Exception as e:
        logger.warning("ProspectWorkspace load failed: %s", e)
        return {}


async def find_workspace_keys_for_email(email: str) -> List[str]:
    """Resolve Crunchbase ids whose mirrored payload references this prospect email."""
    if not (email or "").strip():
        return []
    e = email.strip().lower()
    keys: List[str] = []
    try:
        async with async_session() as session:
            res = await session.execute(select(ProspectWorkspace))
            for row in res.scalars().all():
                p = row.payload or {}
                ch = p.get("channel_state") or {}
                pe = (p.get("prospect_email") or ch.get("last_outreach_email") or "").strip().lower()
                if pe == e:
                    keys.append(row.crunchbase_id)
    except Exception as ex:
        logger.debug("find_workspace_keys_for_email: %s", ex)
    return keys
