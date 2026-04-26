import logging
import json
from enum import Enum
from typing import Optional, Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import httpx

from agent.db.models import Lead, LeadStatus, Enrichment, Conversation, Booking, OutboundLog
from agent.enrichment.pipeline import EnrichmentPipeline
from agent.enrichment import HiringSignalBrief
from agent.channels.email_client import email_client
from agent.channels.sms_client import sms_client
from agent.channels.cal_client import cal_client, CalError
from agent.agent.composer import email_composer
from agent.agent.qualifier import reply_qualifier
from agent.agent.insights import insight_generator
from agent.integrations.hubspot_mcp import hubspot_client
from agent.config import settings
from agent.integrations.langfuse_client import langfuse, start_root_trace

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
        trace = start_root_trace(
            name="lead_processing_cycle",
            user_id=str(lead_id),
            metadata={"has_message": bool(incoming_message)},
        )

        try:
            # 1. Load Lead State
            lead = await self._step_load_state(lead_id, trace)
            
            # 2. Fetch/Update Enrichment
            hiring_brief = await self._step_enrich(lead, trace)

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
            action_result = await self._step_execute_decision(lead, intent, hiring_brief, trace)

            # 5. Update CRM + DB
            await self._step_update_crm(lead, action_result, trace)

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

    async def _step_enrich(self, lead: Lead, trace) -> HiringSignalBrief:
        span = trace.span(name="enrichment_cycle")

        brief = await self.enrichment_pipeline.run(company_name=lead.company)
        stored = {
            "company_name": brief.company_name,
            "overall_confidence": brief.overall_confidence,
            "velocity_60d": brief.velocity_60d,
            "summary": brief.summary,
            "ai_maturity": brief.ai_maturity.model_dump(mode="json") if brief.ai_maturity else None,
            "signals": {k: v.model_dump(mode="json") for k, v in brief.signals.items()},
        }
        enrichment_record = Enrichment(
            lead_id=lead.id,
            signals=stored,
            confidence=brief.overall_confidence,
        )
        self.db.add(enrichment_record)
        await self.db.commit()

        span.end(output=f"Enrichment complete. Confidence: {enrichment_record.confidence}")
        return brief

    async def _step_classify_intent(self, message: str, trace) -> str:
        """Uses the dedicated Qualifier module."""
        span = trace.span(name="classify_intent")
        
        result = await reply_qualifier.qualify(message)
        intent = result.get("intent", "unclear")
        
        span.end(output=intent)
        return intent

    async def _step_execute_decision(self, lead: Lead, intent: str, brief: HiringSignalBrief, trace) -> Dict[str, Any]:
        """DETERMINISTIC decision matrix delegating to specialized modules."""
        span = trace.span(name="decision_matrix")
        
        # 1. Terminal states
        if intent == "unsubscribe":
            lead.status = LeadStatus.UNSUBSCRIBED
            await hubspot_client.create_or_update_contact(
                email=lead.email,
                properties={"lifecyclestage": "other"},
            )
            await hubspot_client.log_event(
                email=lead.email,
                event_type="Unsubscribe",
                body="Prospect unsubscribed — terminal state.",
            )
            span.end(output="Action: unsubscribe processed")
            return {"action": "unsubscribe"}

        if intent == "not_interested":
            lead.status = LeadStatus.CLOSED_LOST
            await hubspot_client.create_or_update_contact(
                email=lead.email,
                properties={"lifecyclestage": "other"},
            )
            await hubspot_client.log_event(
                email=lead.email,
                event_type="Not interested",
                body="Prospect declined — closed lost.",
            )
            span.end(output="Action: not_interested processed")
            return {"action": "not_interested"}

        # 2. Intent-based actions
        if intent == "interested":
            lead.status = LeadStatus.QUALIFIED

            if settings.REQUIRE_HUMAN_APPROVAL:
                await hubspot_client.log_event(
                    email=lead.email,
                    event_type="Qualification",
                    body="Interested — awaiting human approval before Cal.com API booking.",
                )
                await hubspot_client.log_event(
                    email=lead.email,
                    event_type="Voice handoff requested",
                    body="Human discovery handoff requested (interested intent).",
                )
                span.end(output="Action: qualified; human approval gate")
                return {"action": "pending_human_booking"}

            slot_start = await cal_client.resolve_booking_start_time(horizon_days=21)
            if not slot_start:
                span.end(output="Action: No Cal.com slots available", level="ERROR")
                return {
                    "action": "booking_failed",
                    "error": "No available slots in the configured window",
                }
            try:
                booking_res = await cal_client.book_meeting(
                    name=lead.company,
                    email=lead.email,
                    start_time=slot_start,
                    booking_title=lead.company,
                )
            except CalError as e:
                span.end(output=f"Action: Booking failed: {e}", level="ERROR")
                return {"action": "booking_failed", "error": str(e)}

            if booking_res.get("success"):
                lead.status = LeadStatus.BOOKED
                await hubspot_client.create_or_update_contact(
                    email=lead.email,
                    properties={"lifecyclestage": "opportunity"},
                )
                await hubspot_client.log_event(
                    email=lead.email,
                    event_type="Meeting booked",
                    body=f"Cal.com booking id: {booking_res.get('booking_id')}",
                )

                span.end(output=f"Action: Successfully booked meeting {booking_res.get('booking_id')}")
                return {"action": "booked_meeting", "id": booking_res.get("booking_id")}
            span.end(output="Action: Booking failed", level="ERROR")
            return {"action": "booking_failed", "error": booking_res.get("error")}

        # 3. Status-based outreach
        if lead.status == LeadStatus.NEW:
            cb = brief.signals.get("crunchbase")
            sector = lead.icp_segment or "Technology"
            if cb and not cb.error:
                sector = cb.data.get("sector") or sector

            gap_brief = await insight_generator.generate_competitor_gap_brief(
                lead_name=lead.company,
                sector=sector,
                prospect_signals=brief.signals,
            )

            email, _outreach_meta = await email_composer.compose_personalized(
                hiring_brief=brief,
                gap_brief=gap_brief,
                salutation_name="",
                scheduling_url="",
            )

            email_body = email["body"]

            send_res = await email_client.send_email(
                to=lead.email,
                subject=email["subject"],
                html=email_body.replace("\n", "<br/>")
            )
            if send_res.get("suppressed"):
                self.db.add(
                    OutboundLog(
                        channel="email",
                        recipient=lead.email,
                        suppressed=True,
                        detail={"reason": "kill_switch", "lead_id": lead.id},
                    )
                )
                await self.db.commit()
                await hubspot_client.log_event(
                    email=lead.email,
                    event_type="Email Outreach",
                    body=f"SUPPRESSED (kill switch): would have sent subject: {email['subject']}",
                )
                span.end(output="Action: email suppressed by kill switch")
                return {"action": "email_suppressed"}

            await hubspot_client.log_event(
                email=lead.email,
                event_type="Email Outreach",
                body=f"Sent initial AI-personalized email with subject: {email['subject']}"
            )

            lead.status = LeadStatus.CONTACTED
            await self.db.commit()
            span.end(output="Action: Sent AI-composed email")
            return {"action": "send_personalized_email"}

        if lead.status == LeadStatus.REPLIED and intent in ("interested", "question", "other"):
            if not (lead.phone or "").strip():
                span.end(output="Action: SMS skipped — no phone on lead")
                return {"action": "sms_skipped_no_phone"}

            try:
                sms_text = (
                    f"Tenacious: thanks for the reply re {lead.company}. "
                    "If useful, share two times next week for a 15m call and we will confirm."
                )[:320]

                sms_res = await sms_client.send_sms(
                    to=lead.phone,
                    message=sms_text,
                    lead_id=lead.id,
                    db=self.db
                )
                if sms_res.get("suppressed"):
                    self.db.add(
                        OutboundLog(
                            channel="sms",
                            recipient=lead.phone,
                            suppressed=True,
                            detail={"reason": "kill_switch", "lead_id": lead.id},
                        )
                    )
                    await self.db.commit()
                    await hubspot_client.log_event(
                        email=lead.email,
                        event_type="SMS Follow-up",
                        body=f"SUPPRESSED (kill switch): would have sent: {sms_text}",
                    )
                    span.end(output="Action: SMS suppressed")
                    return {"action": "sms_suppressed"}

                await hubspot_client.log_event(
                    email=lead.email,
                    event_type="SMS Follow-up",
                    body=f"Sent SMS follow-up: {sms_text}"
                )

                span.end(output="Action: Sent SMS follow-up")
                return {"action": "sent_sms_followup"}

            except Exception as e:
                logger.warning(f"SMS Follow-up skipped or failed: {e}")
                span.end(output=f"Action: SMS Gated or Failed: {str(e)}", level="WARNING")
                return {"action": "sms_skipped", "reason": str(e)}

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
        payload = latest.signals if latest else {}

        # 2. Push to HubSpot
        try:
            await hubspot_client.sync_enrichment_data(
                email=lead.email,
                enrichment_signals=payload,
            )
            
            # 3. Update Lifecycle Status based on current orchestrator state
            await hubspot_client.create_or_update_contact(
                email=lead.email,
                properties={"hs_lead_status": lead.status.value.replace("_", " ")[:120]},
            )
            await hubspot_client.log_event(
                email=lead.email,
                event_type="Orchestrator",
                body=f"last_action={result.get('action')}",
            )
            span.end(output="Sync successful")
        except Exception as e:
            logger.error(f"CRM Sync failed: {e}")
            span.end(output=str(e), level="ERROR")
