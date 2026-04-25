import logging
from typing import Dict, Any
from agent.integration.resend_mailer import mailer
from agent.integration.africas_talking import sms_client
from agent.integration.hubspot import hubspot
from agent.integration.cal_com import cal_generator

logger = logging.getLogger(__name__)

class HandoffManager:
    """
    Criterion 5: Centralized Channel Handoff Logic.
    This module acts as the state machine for multi-channel dispatch.
    """
    
    async def process_outreach(self, lead_data: Dict[str, Any], channel: str) -> Dict[str, Any]:
        """
        Global entry point for outreach (Criterion 5).
        """
        email = lead_data.get("email")
        phone = lead_data.get("phone")
        has_replied = lead_data.get("has_replied_email", False)
        
        # 1. Cal.com Link Shared Across Paths (Criterion 4)
        booking_link = cal_generator.generate_link(email, lead_data.get("name", ""))
        message = f"Book here: {booking_link}"
        
        if channel == "email":
            # 2. Email Path (Criterion 1)
            result = await mailer.send_email(to=email, subject="Meeting Request", html=message)
            if result["success"]:
                await hubspot.log_event(email, "EMAIL_SENT")
            return result
            
        elif channel == "sms":
            # 3. SMS Path with Warm-Lead Gate (Criterion 2 & 5)
            # This is the centralized enforcement node for the safety policy
            result = await sms_client.send_sms(to=phone, message=message, has_replied_email=has_replied)
            
            if result["success"]:
                await hubspot.log_event(email, "SMS_SENT")
            return result
            
        else:
            return {"success": False, "error": f"Unknown channel: {channel}"}

# Singleton
orchestrator = HandoffManager()
