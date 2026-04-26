"""
Compatibility layer for competitor-gap brief projections.

This keeps old import paths operational while delegating to the schema-valid
projection logic used by the API.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from agent.agent.insights import CompetitorGapBrief
from agent.agent.schema_validate import (
    build_competitor_gap_schema_instance,
    validate_competitor_gap,
)
from agent.enrichment import HiringSignalBrief


def build_brief(
    gap: CompetitorGapBrief,
    hiring_brief: HiringSignalBrief,
    *,
    prospect_domain: str,
    primary_segment_match: str = "abstain",
) -> Dict[str, Any]:
    return build_competitor_gap_schema_instance(
        gap,
        hiring_brief,
        prospect_domain=prospect_domain,
        primary_segment_match=primary_segment_match,
    )


def validate_brief(instance: Dict[str, Any]) -> Tuple[bool, str | None]:
    return validate_competitor_gap(instance)
