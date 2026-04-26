import logging
import re
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
        self.short_code = settings.AT_SHORT_CODE

    @staticmethod
    def normalize_recipient(raw: str) -> str:
        """E.164-style number for Africa's Talking (leading +, no spaces)."""
        s = (raw or "").strip()
        s = re.sub(r"[\s\-().]", "", s)
        if not s:
            return ""
        if s.startswith("00"):
            s = "+" + s[2:]
        if not s.startswith("+") and s.isdigit():
            s = "+" + s
        return s

    def _from_address(self) -> Optional[str]:
        """Sandbox/production often require a short code or approved sender as `from`."""
        for candidate in (self.sender_id, self.short_code):
            v = (candidate or "").strip()
            if v:
                return v
        return None

    def _require_config(self) -> None:
        if not (self.api_key or "").strip() or not (self.username or "").strip():
            raise SMSClientError(
                "Africa's Talking is not configured: set AT_API_KEY and AT_USERNAME in .env."
            )

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
        if settings.outbound_is_suppressed():
            logger.info("Kill switch: SMS send suppressed (defense-in-depth).")
            return {"success": False, "suppressed": True, "reason": "outbound_suppressed"}

        # 1. Verification (Gating)
        from agent.agent.policies import ChannelSafetyPolicy
        
        lead = await db.get(Lead, lead_id)
        if not lead:
            raise SMSClientError(f"Lead with ID {lead_id} not found.")

        can_send, reason = ChannelSafetyPolicy.can_send_sms(lead)
        if not can_send:
            logger.warning(f"SMS gated for Lead {lead_id}: {reason}")
            raise SMSGatingError(f"SMS outreach blocked: {reason}")

        to = self.normalize_recipient(to)
        if not to:
            raise SMSClientError("Recipient phone number is empty after normalization.")

        # 2. Preparation
        # AT expects form data
        self._require_config()
        data = {
            "username": self.username,
            "to": to,
            "message": message,
        }
        from_addr = self._from_address()
        if from_addr:
            data["from"] = from_addr

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

    async def send_warm_lead_sms(self, to: str, message: str) -> Dict[str, Any]:
        """
        Sends SMS without a persisted Lead row. Caller must enforce Tenacious policy
        (email first, reply received) — e.g. dashboard/API layer.
        """
        if settings.outbound_is_suppressed():
            logger.info("Kill switch: warm SMS suppressed (defense-in-depth).")
            return {"success": False, "suppressed": True, "reason": "outbound_suppressed"}

        self._require_config()
        to_norm = self.normalize_recipient(to)
        if not to_norm:
            raise SMSClientError("Recipient phone number is empty after normalization.")

        data = {
            "username": self.username,
            "to": to_norm,
            "message": message,
        }
        from_addr = self._from_address()
        if from_addr:
            data["from"] = from_addr
        headers = {
            "apiKey": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.base_url, headers=headers, data=data)
        except httpx.RequestError as e:
            logger.error("Network error while calling Africa's Talking: %s", e)
            raise SMSClientError(f"Network error: {e}") from e

        if response.status_code not in (200, 201):
            logger.error(
                "Africa's Talking HTTP %s: %s",
                response.status_code,
                response.text[:2000],
            )
            raise SMSClientError(f"API HTTP {response.status_code}: {response.text}")

        try:
            result = response.json()
        except Exception as e:
            raise SMSClientError(f"Invalid JSON from Africa's Talking: {response.text[:500]}") from e

        recipients = result.get("SMSMessageData", {}).get("Recipients", [])
        if recipients and recipients[0].get("status") == "Success":
            return {"success": True, "message_id": recipients[0].get("messageId")}

        r0 = recipients[0] if recipients else {}
        status = r0.get("status") or "Unknown Error"
        code = r0.get("statusCode")
        detail = f"{status}" + (f" (code {code})" if code is not None else "")
        logger.error("Africa's Talking send failed for %s: %s — full: %s", to_norm, detail, result)
        raise SMSClientError(
            f"Africa's Talking: {detail}. "
            f"In sandbox, use a registered test number and set AT_SHORT_CODE or AT_SENDER_ID as `from`."
        )


# Singleton instance
sms_client = SMSClient()
