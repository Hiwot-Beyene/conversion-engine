import logging
import httpx
from typing import Dict, Any, List, Optional
from agent.config import settings

logger = logging.getLogger(__name__)

class CalClient:
    """
    Production-grade Cal.com v2 integration for automated scheduling.
    """

    def __init__(self):
        self.api_key = settings.CAL_API_KEY
        self.event_type_id = settings.CAL_EVENT_TYPE_ID
        self.base_url = "https://api.cal.com/v2"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_available_slots(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Retrieves available booking slots for the configured event type.
        """
        url = f"{self.base_url}/slots"
        params = {
            "eventTypeId": self.event_type_id,
            "startTime": start_date,
            "endTime": end_date
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code != 200:
                logger.error(f"Cal.com slots error: {resp.text}")
                return []
            
            data = resp.json()
            return data.get("data", {}).get("slots", [])

    async def book_meeting(
        self, 
        name: str, 
        email: str, 
        start_time: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Creates a confirmed booking on Cal.com.
        """
        url = f"{self.base_url}/bookings"
        payload = {
            "eventTypeId": int(self.event_type_id),
            "start": start_time,
            "responses": {
                "name": name,
                "email": email
            },
            "metadata": metadata or {},
            "timeZone": "UTC",
            "language": "en"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=self.headers, json=payload)
                
            if resp.status_code not in (200, 201):
                logger.error(f"Cal.com booking error: {resp.text}")
                return {"success": False, "error": resp.text}

            data = resp.json()
            logger.info(f"Meeting booked successfully for {email}. Booking ID: {data.get('data', {}).get('id')}")
            return {
                "success": True, 
                "booking_id": data.get("data", {}).get("id"),
                "status": "confirmed"
            }
        except Exception as e:
            logger.error(f"Unexpected error booking Cal.com meeting: {e}")
            return {"success": False, "error": str(e)}

# Singleton instance
cal_client = CalClient()
