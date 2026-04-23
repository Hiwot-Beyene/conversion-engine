import logging
from typing import Tuple
from agent.db.models import Lead, LeadStatus

logger = logging.getLogger(__name__)

class ChannelSafetyPolicy:
    """
    Centralized governance for multi-channel outreach logic.
    Ensures that automated messaging stays within regulatory and 
    compliance guardrails.
    """

    @staticmethod
    def can_send_sms(lead: Lead) -> Tuple[bool, str]:
        """
        Rule: SMS is a high-cost, high-intimacy channel.
        Requirement: Lead MUST have replied to an email first (Warm-lead gating).
        """
        if not lead.has_replied_email:
            return False, "Lead has not yet interacted via email."
            
        if lead.status in (LeadStatus.BOOKED,):
            return False, "Lead is already in a terminal 'Booked' state."

        # Add more rules as needed (e.g. time of day, opt-out check)
        return True, "All criteria met."

    @staticmethod
    def can_send_email(lead: Lead) -> Tuple[bool, str]:
        """
        Rule: Standard outreach.
        Requirement: Status should be NEW or CONTACTED.
        """
        if lead.status in (LeadStatus.BOOKED,):
            return False, "Lead already booked."
            
        return True, "All criteria met."
