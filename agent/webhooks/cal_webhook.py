import logging
from fastapi import APIRouter, Request, HTTPException, status
from agent.db.models import Lead, LeadStatus, Booking
from agent.db.database import async_session
from sqlalchemy import select
from agent.integrations.hubspot_mcp import hubspot_client

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("")
async def handle_cal_webhook(request: Request):
    """
    Handles Cal.com booking confirmation events.
    Updates lead status to BOOKED and logs to CRM.
    """
    payload = await request.json()
    trigger_event = payload.get("triggerEvent")
    
    if trigger_event == "BOOKING_CREATED":
        data = payload.get("payload", {})
        attendees = data.get("attendees", [])
        if not attendees:
            return {"status": "ignored", "reason": "no attendees"}
        
        email = attendees[0].get("email")
        start_time = data.get("startTime")
        booking_id = data.get("uid")

        logger.info(f"Booking confirmed for {email} at {start_time}")

        async with async_session() as session:
            # 1. Update Lead State
            stmt = select(Lead).where(Lead.email == email)
            lead = (await session.execute(stmt)).scalar_one_or_none()
            
            if lead:
                lead.status = LeadStatus.BOOKED
                
                # 2. Record Booking
                new_booking = Booking(
                    lead_id=lead.id,
                    cal_event_id=booking_id,
                    scheduled_at=start_time,
                    status="scheduled"
                )
                session.add(new_booking)
                await session.commit()

                # 3. CRM Sync
                await hubspot_client.create_or_update_contact(
                    email=email,
                    properties={"lifecyclestage": "opportunity", "lead_status": "BOOKED"}
                )
                
                await hubspot_client.log_event(
                    email=email,
                    event_type="Meeting Booked",
                    body=f"Meeting confirmed via Cal.com for {start_time}. ID: {booking_id}"
                )

                return {"status": "processed", "lead_id": lead.id}
            
    return {"status": "ignored"}
