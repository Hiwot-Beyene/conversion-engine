import logging
from sqlalchemy import select
from agent.db.models import Lead
from agent.db.database import async_session
from agent.agent.orchestrator import LeadOrchestrator
from agent.agent.events import event_dispatcher, ConversionEvent

logger = logging.getLogger(__name__)

async def on_lead_email_replied(event: ConversionEvent):
    """
    Listener for lead.email_replied events. 
    Triggers the orchestrator to process the incoming message.
    """
    payload = event.payload
    email = payload.get("email")
    content = payload.get("content")

    async with async_session() as session:
        # Find the lead by email
        stmt = select(Lead).where(Lead.email == email)
        lead = (await session.execute(stmt)).scalar_one_or_none()
        
        if lead:
            logger.info(f"Event: lead.email_replied triggered Orchestrator for lead {lead.id}")
            orchestrator = LeadOrchestrator(session)
            await orchestrator.process_lead(lead.id, incoming_message=content)
        else:
            logger.warning(f"Event: lead.email_replied received for unknown email {email}")

def setup_event_listeners():
    """Initializes all system event subscribers."""
    event_dispatcher.subscribe("lead.email_replied", on_lead_email_replied)
