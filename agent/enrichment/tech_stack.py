"""
Tech-stack enrichment from public hiring signal text.

This module intentionally stays lightweight (no external APIs) and derives a
directional stack signal from parsed public role titles. It is used as one
input into AI-maturity scoring and brief projection, not as ground truth.
"""
from __future__ import annotations

from typing import Any, Dict, List

from agent.enrichment import EnrichmentSignal, SignalMetadata


def _blob_from_roles(roles: List[str]) -> str:
    return " ".join(str(r).lower() for r in roles if r)


def _extract_stack_hints(blob: str) -> Dict[str, Any]:
    langs: List[str] = []
    tools: List[str] = []
    cloud: List[str] = []

    if any(k in blob for k in ("python", "django", "flask", "fastapi")):
        langs.append("python")
    if any(k in blob for k in ("typescript", "javascript", "node", "react", "next.js", "nextjs")):
        langs.append("typescript_javascript")
    if any(k in blob for k in ("go", "golang")):
        langs.append("go")
    if "java" in blob:
        langs.append("java")

    if any(k in blob for k in ("postgres", "postgresql", "mysql", "sql")):
        tools.append("relational_db")
    if any(k in blob for k in ("snowflake", "dbt", "bigquery", "redshift")):
        tools.append("analytics_stack")
    if any(k in blob for k in ("kubernetes", "docker", "terraform")):
        tools.append("platform_ops")
    if any(k in blob for k in ("mlops", "pytorch", "tensorflow", "llm", "vector", "rag")):
        tools.append("ml_stack")

    if "aws" in blob:
        cloud.append("aws")
    if "gcp" in blob or "google cloud" in blob:
        cloud.append("gcp")
    if "azure" in blob:
        cloud.append("azure")

    out = {
        "languages": list(dict.fromkeys(langs)),
        "tooling": list(dict.fromkeys(tools)),
        "cloud": list(dict.fromkeys(cloud)),
    }
    out["has_vector_db"] = "vector" in blob
    out["has_mlops_signal"] = "mlops" in blob or "ml platform" in blob
    return out


def enrich_from_tech_stack(job_posts_signal: EnrichmentSignal | None) -> EnrichmentSignal:
    """
    Build an inferred stack signal from public role text.
    Returns a valid EnrichmentSignal in all cases.
    """
    if not job_posts_signal or job_posts_signal.error:
        return EnrichmentSignal(
            source="tech_stack_inference",
            confidence=0.25,
            metadata=SignalMetadata(evidence_strength=0.2),
            data={"note": "No usable job-post signal for stack inference."},
        )

    data = job_posts_signal.data or {}
    roles = data.get("roles") or []
    if not isinstance(roles, list):
        roles = []
    blob = _blob_from_roles([str(r) for r in roles])

    if not blob.strip():
        return EnrichmentSignal(
            source="tech_stack_inference",
            confidence=0.3,
            metadata=SignalMetadata(evidence_strength=0.22),
            data={"note": "Role list empty; stack inference unavailable."},
        )

    hints = _extract_stack_hints(blob)
    signal_count = (
        len(hints.get("languages") or [])
        + len(hints.get("tooling") or [])
        + len(hints.get("cloud") or [])
    )
    conf = 0.55 if signal_count <= 1 else (0.68 if signal_count <= 3 else 0.78)
    ev = 0.35 if signal_count <= 1 else (0.52 if signal_count <= 3 else 0.66)

    return EnrichmentSignal(
        source="tech_stack_inference",
        confidence=conf,
        metadata=SignalMetadata(evidence_strength=ev),
        data={
            **hints,
            "inferred_from": "job_post_titles",
            "title_sample_size": len(roles),
        },
    )
