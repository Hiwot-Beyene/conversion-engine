"""JSON structured log lines for request correlation."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

from agent.config import settings

logger = logging.getLogger("conversion_engine")


def log_event(
    *,
    event: str,
    correlation_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    step: Optional[str] = None,
    latency_ms: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    row = {
        "event": event,
        "correlation_id": correlation_id,
        "lead_id": lead_id,
        "step": step,
        "latency_ms": latency_ms,
        "kill_switch": settings.KILL_SWITCH,
        "environment": str(settings.ENVIRONMENT),
    }
    if extra:
        row.update(extra)
    logger.info(json.dumps({k: v for k, v in row.items() if v is not None}, default=str))


def new_correlation_id() -> str:
    return str(uuid.uuid4())
