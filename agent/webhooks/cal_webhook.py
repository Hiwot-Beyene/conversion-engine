import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from agent.config import settings, Environment
from agent.db.database import async_session
from agent.db.models import Booking, Lead, LeadStatus
from agent.integrations.hubspot_mcp import hubspot_client
from agent.api.leads_router import append_channel_event_by_email

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_cal_signature(body: bytes, signature_header: Optional[str]) -> bool:
    secret = (settings.CALCOM_WEBHOOK_SECRET or "").strip()
    if not secret:
        if settings.ENVIRONMENT == Environment.PRODUCTION:
            return False
        logger.warning("CALCOM_WEBHOOK_SECRET unset — allowing webhook in non-production only")
        return True
    if not signature_header:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    sig = signature_header.strip().lower().replace("sha256=", "")
    return hmac.compare_digest(digest, sig)


def _parse_dt(val: Any) -> datetime:
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(timezone.utc)


@router.post("")
async def handle_cal_webhook(request: Request):
    """
    Cal.com booking events. Verifies HMAC (X-Cal-Signature-256) when CALCOM_WEBHOOK_SECRET is set.
    Idempotent on booking uid.
    """
    raw = await request.body()
    sig = request.headers.get("x-cal-signature-256") or request.headers.get("X-Cal-Signature-256")
    if not _verify_cal_signature(raw, sig):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Cal.com webhook signature")

    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None

    trigger_event = payload.get("triggerEvent")
    if trigger_event != "BOOKING_CREATED":
        return {"status": "ignored", "trigger": trigger_event}

    data = payload.get("payload") or {}
    attendees = data.get("attendees") or []
    if not attendees:
        return {"status": "ignored", "reason": "no attendees"}

    email = attendees[0].get("email")
    start_time = _parse_dt(data.get("startTime"))
    booking_uid = str(data.get("uid") or data.get("id") or "")

    async with async_session() as session:
        if booking_uid:
            existing = (
                await session.execute(select(Booking).where(Booking.cal_uid == booking_uid))
            ).scalar_one_or_none()
            if existing:
                logger.info("Duplicate Cal webhook for uid=%s — idempotent ok", booking_uid)
                return {"status": "duplicate", "booking_uid": booking_uid}

        stmt = select(Lead).where(Lead.email == email)
        lead = (await session.execute(stmt)).scalar_one_or_none()

        if lead:
            lead.status = LeadStatus.BOOKED
            b = Booking(
                lead_id=lead.id,
                cal_uid=booking_uid or None,
                cal_event_id=str(data.get("id") or booking_uid) if (data.get("id") or booking_uid) else None,
                scheduled_at=start_time,
                status="scheduled",
            )
            session.add(b)
            await session.commit()

            await hubspot_client.create_or_update_contact(
                email=email,
                properties={"lifecyclestage": "opportunity"},
            )
            await hubspot_client.log_event(
                email=email,
                event_type="Meeting Booked",
                body=f"Meeting confirmed via Cal.com webhook for {start_time.isoformat()}. uid={booking_uid}",
            )
            try:
                await append_channel_event_by_email(
                    email,
                    "cal.booking_confirmed",
                    {"booking_uid": booking_uid, "start": start_time.isoformat()},
                )
            except Exception as e:
                logger.debug("timeline append skipped: %s", e)

            return {"status": "processed", "lead_id": lead.id}

    return {"status": "ignored", "reason": "lead not found"}
