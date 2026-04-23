import logging
import httpx
from typing import Dict, Any, List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from agent.config import settings

logger = logging.getLogger(__name__)

class CalError(Exception):
    """Custom exception for Cal.com API failures."""
    pass

class CalClient:
    """
    Production-grade Cal.com v2 integration for automated scheduling.
    Includes retries and idempotency safeguards.
    """

    def __init__(self):
        self.api_key = settings.CAL_API_KEY
        self.event_type_id = settings.CAL_EVENT_TYPE_ID
        self.base_url = "https://api.cal.com/v2"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, CalError)),
        reraise=True
    )
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
                raise CalError(f"Cal.com slots error: {resp.text}")
            
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
        Implements an idempotency check by verifying if a booking exists for this email+time.
        """
        # IDEMPOTENCY SAFEGUARD: Search for existing booking
        existing = await self._find_existing_booking(email, start_time)
        if existing:
            logger.info(f"Duplicate booking detected for {email} at {start_time}. Returning existing ID.")
            return {"success": True, "booking_id": existing, "status": "existing"}

        return await self._execute_booking(name, email, start_time, metadata)

    async def _find_existing_booking(self, email: str, start_time: str) -> Optional[int]:
        """Checks if a lead already has a booking at the specified time."""
        url = f"{self.base_url}/bookings"
        params = {"email": email}
        # In a real v2 API, we would filter by time on the server if possible
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code == 200:
                bookings = resp.json().get("data", [])
                for b in bookings:
                    if b.get("start") == start_time:
                        return b.get("id")
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.RequestError, CalError)),
        reraise=True
    )
    async def _execute_booking(self, name: str, email: str, start_time: str, metadata: dict) -> Dict[str, Any]:
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

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            
        if resp.status_code not in (200, 201):
            raise CalError(f"Booking execution failed: {resp.text}")

        data = resp.json()
        return {
            "success": True, 
            "booking_id": data.get("data", {}).get("id"),
            "status": "confirmed"
        }

# Singleton instance
cal_client = CalClient()
