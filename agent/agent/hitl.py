"""
Human-in-the-loop helpers for outbound approval gates.
"""
from __future__ import annotations

from typing import Any, Dict

from agent.config import settings


def requires_human_approval(channel_state: Dict[str, Any] | None) -> bool:
    """
    True when policy requires manual approval before first outbound.
    """
    if not settings.REQUIRE_HUMAN_APPROVAL:
        return False
    ch = channel_state or {}
    return not bool(ch.get("outreach_approved"))


def approval_status_payload(channel_state: Dict[str, Any] | None) -> Dict[str, Any]:
    ch = channel_state or {}
    approved = bool(ch.get("outreach_approved"))
    return {
        "requires_human_approval": bool(settings.REQUIRE_HUMAN_APPROVAL),
        "approved": approved,
        "state": "approved" if approved else "pending_approval",
    }
