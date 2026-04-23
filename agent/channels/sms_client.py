import logging
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from agent.db.models import Lead
from agent.config import settings

logger = logging.getLogger(__name__)

class SMSClientError(Exception):
    """Custom exception for SMS service errors."""
    pass

class SMSGatingError(SMSClientError):
    """Raised when SMS is blocked due to gating rules."""
    pass

class SMSClient:
    """
    Africa's Talking SMS client with integrated safety gating.
    Gating: Inbound email interaction is required before SMS outreach.
    """

    def __init__(self):
        self.username = settings.AT_USERNAME
        self.api_key = settings.AT_API_KEY
        self.base_url = "https://api.africastalking.com/version1/messaging"
        self.sender_id = settings.AT_SENDER_ID

    async def send_sms(
        self, 
        to: str, 
        message: str, 
        lead_id: int, 
        db: Session
    ) -> Dict[str, Any]:
        """
        Sends an SMS through Africa's Talking after validating lead compliance.
        """
        # 1. Verification (Gating)
        lead = db.get(Lead, lead_id)
        if not lead:
            raise SMSClientError(f"Lead with ID {lead_id} not found.")

        if not lead.has_replied_email:
            logger.warning(f"SMS gated for Lead {lead_id}: No email reply detected.")
            raise SMSGatingError(f"SMS outreach blocked for lead {lead_id}: has_replied_email is False.")

        # 2. Preparation
        # AT expects form data
        data = {
            "username": self.username,
            "to": to,
            "message": message,
        }
        if self.sender_id:
            data["from"] = self.sender_id

        headers = {
            "apiKey": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        # 3. Execution
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.base_url, 
                    headers=headers, 
                    data=data
                )
                
            if response.status_code not in (200, 201):
                logger.error(f"Africa's Talking API error: {response.status_code} - {response.text}")
                raise SMSClientError(f"API Error: {response.text}")

            result = response.json()
            recipients = result.get("SMSMessageData", {}).get("Recipients", [])
            
            if recipients and recipients[0].get("status") == "Success":
                logger.info(f"SMS successfully sent to {to} for Lead {lead_id}")
                return {
                    "success": True,
                    "message_id": recipients[0].get("messageId"),
                    "cost": recipients[0].get("cost")
                }
            else:
                status = recipients[0].get("status") if recipients else "Unknown Error"
                raise SMSClientError(f"Africa's Talking reported failure: {status}")

        except httpx.RequestError as e:
            logger.error(f"Network error while calling Africa's Talking: {e}")
            raise SMSClientError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in send_sms: {e}")
            raise SMSClientError(str(e))

# Singleton instance
sms_client = SMSClient()
