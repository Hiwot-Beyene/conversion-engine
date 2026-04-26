import logging
import hmac
import hashlib
import json
from typing import Optional, Dict, Any
from fastapi import APIRouter, Request, Header, HTTPException, status
from pydantic import BaseModel
from agent.config import settings, Environment
from agent.api.leads_router import append_channel_event_by_email

logger = logging.getLogger(__name__)
router = APIRouter()

class EmailEvent(BaseModel):
    """Structured representation of an email lifecycle event."""
    event_type: str
    email_id: str
    recipient: str
    timestamp: str
    metadata: Dict[str, Any] = {}
    content: Optional[str] = None  # For inbound replies

def verify_resend_signature(payload: bytes, headers: Dict[str, str]) -> bool:
    """
    Verifies the Svix/Resend webhook signature.
    Resend uses Svix for webhooks. Headers needed:
    - webhook-id
    - webhook-timestamp
    - webhook-signature
    """
    secret = (settings.RESEND_WEBHOOK_SECRET or "").strip()
    if not secret:
        if settings.ENVIRONMENT == Environment.PRODUCTION:
            logger.error("RESEND_WEBHOOK_SECRET required in production.")
            return False
        logger.warning("RESEND_WEBHOOK_SECRET not configured — skipping verification (development only).")
        return True
        
    msg_id = headers.get("webhook-id")
    msg_timestamp = headers.get("webhook-timestamp")
    msg_signature = headers.get("webhook-signature")
    
    if not all([msg_id, msg_timestamp, msg_signature]):
        return False
        
    # Construct signature base
    to_sign = f"{msg_id}.{msg_timestamp}.".encode() + payload
    
    # Extract actual signature from v1,sig1 v1,sig2 string
    signatures = msg_signature.split(" ")
    for sig in signatures:
        if not sig.startswith("v1,"):
            continue
        provided_sig = sig[3:]
        
        # Calculate expected hmac
        # The secret from Resend/Svix starts with 'whsec_' - we need the part after
        key = secret.replace("whsec_", "")
        expected_sig = hmac.new(
            key.encode(),
            to_sign,
            hashlib.sha256
        ).hexdigest()
        
        if hmac.compare_digest(expected_sig, provided_sig):
            return True
            
    return False

@router.post("")
async def handle_email_webhook(
    request: Request,
    webhook_id: str = Header(None, alias="webhook-id"),
    webhook_timestamp: str = Header(None, alias="webhook-timestamp"),
    webhook_signature: str = Header(None, alias="webhook-signature")
):
    """
    Unified entry point for Resend webhooks.
    Handles verification, parsing, and normalization of events.
    """
    raw_body = await request.body()
    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": webhook_timestamp,
        "webhook-signature": webhook_signature
    }

    # 1. Verify Signature
    if not verify_resend_signature(raw_body, headers):
        logger.error("Invalid Resend webhook signature detected.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature"
        )

    # 2. Parse Payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    event_type = payload.get("type")
    data = payload.get("data", {})
    
    # 3. Normalize into structured response
    normalized_event = _normalize_resend_event(event_type, data)
    
    # 4. Downstream Integration (The 'Senior' part)
    if event_type == "email.replied" and normalized_event.content:
        from agent.agent.events import event_dispatcher, ConversionEvent

        await event_dispatcher.dispatch(ConversionEvent(
            event_name="lead.email_replied",
            payload={
                "email": normalized_event.recipient,
                "content": normalized_event.content,
                "timestamp": normalized_event.timestamp
            }
        ))
        try:
            await append_channel_event_by_email(
                normalized_event.recipient,
                "email_replied",
                {"preview": (normalized_event.content or "")[:240]},
            )
        except Exception as e:
            logger.debug("timeline email_replied: %s", e)

    if event_type == "email.bounced":
        try:
            await append_channel_event_by_email(
                normalized_event.recipient,
                "email_bounced",
                {"metadata": normalized_event.metadata},
            )
        except Exception as e:
            logger.debug("timeline email_bounced: %s", e)

    if event_type == "email.delivered":
        try:
            await append_channel_event_by_email(
                normalized_event.recipient,
                "email_delivered",
                {"email_id": normalized_event.email_id},
            )
        except Exception as e:
            logger.debug("timeline email_delivered: %s", e)

    # 5. Log and Return
    logger.info(f"Received email event: {event_type} for {normalized_event.recipient}")
    
    return {
        "status": "processed",
        "email_id": normalized_event.email_id,
        "event": normalized_event.model_dump()
    }

def _normalize_resend_event(event_type: str, data: Dict[str, Any]) -> EmailEvent:
    """
    Maps Resend-specific payload structure to a internal normalized EmailEvent.
    """
    # Resend sends the email ID as 'id' or within 'email_id' depending on event
    email_id = data.get("email_id") or data.get("id") or "unknown"
    recipient = data.get("to", [])
    if isinstance(recipient, list) and recipient:
        recipient = recipient[0]
    else:
        recipient = str(recipient)

    metadata = data.get("metadata", {})
    content = None
    
    # Special handling for Inbound Replies
    if event_type == "email.replied":
        content = data.get("text") or data.get("html")
        metadata["subject"] = data.get("subject")
        metadata["from"] = data.get("from")
        
    # Special handling for Bounces
    if event_type == "email.bounced":
        metadata["bounce_type"] = data.get("bounce_type")
        metadata["error"] = data.get("message")

    return EmailEvent(
        event_type=event_type,
        email_id=email_id,
        recipient=recipient,
        timestamp=data.get("created_at") or "",
        metadata=metadata,
        content=content
    )
