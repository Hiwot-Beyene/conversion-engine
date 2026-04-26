"""
Compatibility layer for hiring-signal brief projections.

Historically this module existed as a placeholder; now it provides a typed
adapter over `agent.agent.schema_validate` so legacy imports continue working.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from agent.agent.schema_validate import (
    build_hiring_signal_schema_instance,
    validate_hiring_signal,
)
from agent.enrichment import HiringSignalBrief


def build_brief(
    brief: HiringSignalBrief,
    *,
    prospect_domain: str,
    primary_segment_match: str,
    segment_confidence: float,
) -> Dict[str, Any]:
    return build_hiring_signal_schema_instance(
        brief,
        prospect_domain=prospect_domain,
        primary_segment_match=primary_segment_match,
        segment_confidence=segment_confidence,
    )


def validate_brief(instance: Dict[str, Any]) -> Tuple[bool, str | None]:
    return validate_hiring_signal(instance)
