import logging
from typing import Optional
from fastapi import APIRouter, Request, status, HTTPException, Form
from pydantic import BaseModel
from agent.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

class InboundSMS(BaseModel):
    """Normalized inbound SMS representation."""
    from_number: str
    to_number: str
    text: str
    message_id: str
    link_id: Optional[str] = None

@router.post("")
async def handle_sms_webhook(
    from_number: str = Form(..., alias="from"),
    to_number: str = Form(..., alias="to"),
    text: str = Form(..., alias="text"),
    message_id: str = Form(..., alias="id"),
    link_id: Optional[str] = Form(None, alias="linkId")
):
    """
    Webhook handler for Africa's Talking inbound SMS.
    Handles opt-out requests and routes messages to the core orchestrator.
    """
    logger.info(f"Received inbound SMS from {from_number}: {text[:20]}...")

    # 1. Normalize payload
    inbound = InboundSMS(
        from_number=from_number,
        to_number=to_number,
        text=text,
        message_id=message_id,
        link_id=link_id
    )

    # 2. Handle STOP/HELP (Regulatory compliance)
    command = inbound.text.strip().upper()
    if command in ("STOP", "END", "CANCEL", "UNSUBSCRIBE"):
        return await _handle_opt_out(inbound)
    
    if command == "HELP":
        return await _handle_help_request(inbound)

    # 3. Route to Orchestrator
    # This is where you would call your agent logic, update DB, or trigger a task.
    # For now we log and return success as the requirement is to 'route'.
    # In a real system, you might put this on a Redis queue or call an async service.
    _route_to_orchestrator(inbound)

    return {"status": "received"}

async def _handle_opt_out(inbound: InboundSMS):
    """Handles opt-out (STOP) requests."""
    logger.info(f"User {inbound.from_number} requested OPT-OUT via SMS.")
    # Business logic to blacklist this number would go here
    return {"status": "unsubscribed"}

async def _handle_help_request(inbound: InboundSMS):
    """Handles HELP requests."""
    logger.info(f"User {inbound.from_number} requested HELP via SMS.")
    return {"status": "help_provided"}

def _route_to_orchestrator(inbound: InboundSMS):
    """
    Placeholder for routing logic to the main agent orchestrator.
    """
    logger.info(f"Routing SMS from {inbound.from_number} to Orchestrator...")
    # Example: orchestrator.process_inbound_sms(inbound)
    pass
