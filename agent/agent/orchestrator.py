import logging
import json
from enum import Enum
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import httpx

from agent.db.models import Lead, LeadStatus, Enrichment, Conversation, Booking
from agent.enrichment.pipeline import EnrichmentPipeline
from agent.channels.email_client import email_client
from agent.channels.sms_client import sms_client
from agent.channels.cal_client import cal_client
from agent.agent.composer import email_composer
from agent.agent.qualifier import reply_qualifier
from agent.agent.insights import insight_generator
from agent.integrations.hubspot_mcp import hubspot_client
from agent.config import settings
from agent.integrations.langfuse_client import langfuse

logger = logging.getLogger(__name__)

class LeadIntent(str, Enum):
    INTERESTED = "interested"
    QUESTION = "question"
    NOT_INTERESTED = "not_interested"
    UNSUBSCRIBE = "unsubscribe"
    OTHER = "other"

class LeadOrchestrator:
    """
    Lead Lifecycle Orchestrator.
    Deterministic state machine for lead processing with full observability.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.enrichment_pipeline = EnrichmentPipeline(db)

    async def process_lead(self, lead_id: int, incoming_message: Optional[str] = None) -> Dict[str, Any]:
        """
        Main entry point for processing a lead's lifecycle step.
        """
        # Start a root trace for this lead interaction
        trace = langfuse.trace(
            name="lead_processing_cycle",
            user_id=str(lead_id),
            metadata={"has_message": bool(incoming_message)}
        )

        try:
            # 1. Load Lead State
            lead = await self._step_load_state(lead_id, trace)
            
            # 2. Fetch/Update Enrichment
            enrichment_signals = await self._step_enrich(lead, trace)

            # 3. Classify User Intent (if message provided)
            intent = "other"
            if incoming_message:
                intent = await self._step_classify_intent(incoming_message, trace)
                # Update status based on reply
                if lead.status == LeadStatus.CONTACTED:
                    lead.status = LeadStatus.REPLIED
                    lead.has_replied_email = True
                    await self.db.commit()

            # 4. Decide & Execute Next Action
            action_result = await self._step_execute_decision(lead, intent, enrichment_signals, trace)

            # 5. Update CRM + DB
            self._step_update_crm(lead, action_result, trace)

            trace.update(status_message="Successfully completed cycle")
            return {
                "lead_id": lead_id,
                "status": lead.status,
                "intent": intent,
                "action": action_result.get("action")
            }

        except Exception as e:
            logger.error(f"Orchestration failure for Lead {lead_id}: {e}", exc_info=True)
            trace.update(status_message=f"Error: {str(e)}", level="ERROR")
            raise
        finally:
            langfuse.flush()

    async def _step_load_state(self, lead_id: int, trace) -> Lead:
        span = trace.span(name="load_lead_state")
        lead = await self.db.get(Lead, lead_id)
        if not lead:
            span.end(output="Lead not found")
            raise ValueError(f"Lead {lead_id} not found")
        
        span.end(output=f"Lead loaded: {lead.email} - Status: {lead.status}")
        return lead

    async def _step_enrich(self, lead: Lead, trace) -> Dict[str, Any]:
        span = trace.span(name="enrichment_cycle")
        
        # We only re-enrich if not recently done or missing
        # For production-grade, we check the latest Enrichment record
        signals = await self.enrichment_pipeline.run(company_name=lead.company)
        
        # Save to DB
        enrichment_record = Enrichment(
            lead_id=lead.id,
            signals=signals,
            confidence=self.enrichment_pipeline._calculate_overall_confidence(signals)
        )
        self.db.add(enrichment_record)
        await self.db.commit()

        span.end(output=f"Enrichment complete. Confidence: {enrichment_record.confidence}")
        return signals

    async def _step_classify_intent(self, message: str, trace) -> str:
        """Uses the dedicated Qualifier module."""
        span = trace.span(name="classify_intent")
        
        result = await reply_qualifier.qualify(message)
        intent = result.get("intent", "unclear")
        
        span.end(output=intent)
        return intent

    async def _step_execute_decision(self, lead: Lead, intent: str, signals: dict, trace) -> Dict[str, Any]:
        """DETERMINISTIC decision matrix delegating to specialized modules."""
        span = trace.span(name="decision_matrix")
        
        # 1. Terminal states
        if intent in ("unsubscribe", "not_interested"):
            lead.status = LeadStatus.BOOKED # Close out
            span.end(output=f"Action: {intent} processed")
            return {"action": intent}

        # 2. Intent-based actions
        if intent == "interested":
            lead.status = LeadStatus.QUALIFIED
            
            # ATOMIC ACTION: Book Meeting + Update CRM
            booking_res = await cal_client.book_meeting(
                name=lead.company, 
                email=lead.email,
                start_time="2026-05-01T10:00:00Z" # In production, this would come from a selected slot
            )
            
            if booking_res["success"]:
                lead.status = LeadStatus.BOOKED
                # Sync 'Booked' status back to CRM immediately
                await hubspot_client.create_or_update_contact(
                    email=lead.email,
                    properties={"lifecyclestage": "opportunity", "lead_status": "BOOKED"}
                )
                
                span.end(output=f"Action: Successfully booked meeting {booking_res['booking_id']}")
                return {"action": "booked_meeting", "id": booking_res["booking_id"]}
            else:
                span.end(output="Action: Booking failed", level="ERROR")
                return {"action": "booking_failed", "error": booking_res["error"]}

        # 3. Status-based outreach
        if lead.status == LeadStatus.NEW:
            # Generate personalized Insight first
            competitors = ["Competitor A", "Competitor B"] # Mock competitors 
            gap_insight = await insight_generator.generate_competitor_gap(signals, competitors)
            
            # Compose high-quality email
            email = await email_composer.compose(
                lead_name=lead.company, # Fallback to company name if lead name missing
                company=lead.company,
                hiring_signal_brief=gap_insight
            )
            
            # Send
            await email_client.send_email(
                to=lead.email,
                subject=email["subject"],
                html=email["body"]
            )
            
            lead.status = LeadStatus.CONTACTED
            self.db.commit()
            span.end(output="Action: Sent AI-composed email")
            return {"action": "send_personalized_email"}

        span.end(output="Action: No action required")
        return {"action": "none"}

    async def _step_update_crm(self, lead: Lead, result: dict, trace):
        """
        Synchronizes the current lead state and enriched signals to HubSpot.
        """
        span = trace.span(name="crm_sync")
        
        # 1. Fetch latest enrichment signals for this lead
        # (Assuming we want to push the signals we just fetched)
        enrichment = await self.db.execute(
            select(Enrichment).where(Enrichment.lead_id == lead.id).order_by(Enrichment.created_at.desc())
        )
        latest = enrichment.scalars().first()
        
        # 2. Push to HubSpot
        try:
            await hubspot_client.sync_enrichment_data(
                email=lead.email,
                enrichment_signals=latest.signals if latest else {}
            )
            
            # 3. Update Lifecycle Status based on current orchestrator state
            await hubspot_client.create_or_update_contact(
                email=lead.email,
                properties={
                    "hs_lead_status": lead.status.value,
                    "last_orchestrator_action": result.get("action")
                }
            )
            span.end(output="Sync successful")
        except Exception as e:
            logger.error(f"CRM Sync failed: {e}")
            span.end(output=str(e), level="ERROR")
