import logging
from typing import List, Optional, Dict, Any
import httpx
from agent.config import settings

logger = logging.getLogger(__name__)

class EmailClientError(Exception):
    """Custom exception for email service errors."""
    pass

class EmailClient:
    """
    Production-grade Resend email client using httpx for async operations.
    """
    
    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.base_url = "https://api.resend.com"
        self.from_email = settings.RESEND_FROM_EMAIL
        
    async def send_email(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        reply_to: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        tags: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Sends an email using the Resend API.
        """
        if settings.outbound_is_suppressed():
            logger.info("Kill switch: email send suppressed (defense-in-depth).")
            return {"success": False, "suppressed": True, "reason": "outbound_suppressed"}

        url = f"{self.base_url}/emails"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "from": self.from_email,
            "to": to,
            "subject": subject,
            "html": html,
        }
        
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if tags:
            payload["tags"] = tags

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                
            if response.status_code not in (200, 201):
                logger.error(f"Resend API error: {response.status_code} - {response.text}")
                raise EmailClientError(f"Failed to send email: {response.text}")
                
            data = response.json()
            logger.info(f"Email sent successfully to {to}. ID: {data.get('id')}")
            return {
                "success": True,
                "email_id": data.get("id"),
                "status": "sent"
            }
            
        except httpx.RequestError as e:
            logger.error(f"Network error while calling Resend: {e}")
            raise EmailClientError(f"Network error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in send_email: {e}")
            raise EmailClientError(str(e))

# Singleton instance
email_client = EmailClient()
