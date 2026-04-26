import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote

import httpx
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

    # Bookings and slots use different version gates on api.cal.com; wrong header → 404 on GET /v2/slots.
    _BOOKINGS_API_VERSION = "2026-02-25"
    _SLOTS_API_VERSION = "2024-09-04"

    def __init__(self):
        self.api_key = settings.CALCOM_API_KEY
        self.event_type_id = settings.CALCOM_EVENT_TYPE_ID
        self.base_url = "https://api.cal.com/v2"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "cal-api-version": self._BOOKINGS_API_VERSION,
        }

    def _slots_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "cal-api-version": self._SLOTS_API_VERSION,
        }

    @staticmethod
    def _parse_event_type_id(raw: Any) -> Optional[int]:
        """
        Accepts int-like env values and safely extracts first integer token.
        Returns None for invalid/missing IDs instead of throwing.
        """
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw
        s = str(raw).strip()
        if not s:
            return None
        if s.isdigit():
            return int(s)
        m = re.search(r"\d+", s)
        if m:
            return int(m.group(0))
        return None

    @staticmethod
    def _normalize_start(s: Optional[str]) -> str:
        if not s:
            return ""
        x = str(s).strip().replace("Z", "").replace("+00:00", "")
        if "." in x:
            x = x.split(".", 1)[0]
        return x

    @staticmethod
    def _extract_booking_dicts(raw: Any) -> List[Dict[str, Any]]:
        """Cal list endpoints may return data as a list, nested dict, or list of non-dicts — normalize to dict rows only."""
        if raw is None:
            return []
        if isinstance(raw, dict):
            for key in ("bookings", "booking", "items", "data", "results"):
                inner = raw.get(key)
                if isinstance(inner, list):
                    return CalClient._extract_booking_dicts(inner)
                if isinstance(inner, dict):
                    return CalClient._extract_booking_dicts(inner)
            if any(k in raw for k in ("id", "uid", "start", "startTime")):
                return [raw]
            return []
        if isinstance(raw, list):
            out: List[Dict[str, Any]] = []
            for item in raw:
                if isinstance(item, dict):
                    out.append(item)
            return out
        return []

    @staticmethod
    def _flatten_slots_data(data_obj: Any) -> List[str]:
        """
        Cal v2 returns data as a date-keyed map: { "2050-09-05": [slot, ...], ... }.
        Each slot is either an ISO string or { "start": "..." } (optional "end" with format=range).
        """
        if not isinstance(data_obj, dict):
            return []
        out: List[str] = []
        for _day, day_slots in data_obj.items():
            if not isinstance(day_slots, list):
                continue
            for item in day_slots:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
                elif isinstance(item, dict):
                    s = item.get("start")
                    if isinstance(s, str) and s.strip():
                        out.append(s.strip())

        def _sort_key(s: str) -> datetime:
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)

        out.sort(key=_sort_key)
        return out

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, CalError)),
        reraise=True
    )
    async def get_available_slots(self, start_date: str, end_date: str) -> List[str]:
        """
        Retrieves available slot start times (ISO strings) for the configured event type.
        Query range uses Cal.com v2 parameters `start` and `end` (UTC).
        """
        et_id = self._parse_event_type_id(self.event_type_id)
        if et_id is None:
            logger.error(
                "CALCOM_EVENT_TYPE_ID is missing/invalid; cannot fetch slots. "
                "Set a numeric event type ID in .env."
            )
            return []

        url = f"{self.base_url}/slots"
        params: Dict[str, Any] = {
            "eventTypeId": et_id,
            "start": start_date,
            "end": end_date,
            "timeZone": "UTC",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._slots_headers(), params=params)
            if resp.status_code != 200:
                raise CalError(f"Cal.com slots error: {resp.text}")

            body = resp.json()
            if body.get("status") == "error":
                raise CalError(f"Cal.com slots error: {body}")

            return self._flatten_slots_data(body.get("data"))

    async def resolve_booking_start_time(
        self,
        *,
        horizon_days: int = 21,
        prefer_start: Optional[str] = None,
    ) -> Optional[str]:
        """
        Pick a start time that is actually free on the host calendar (Cal.com computed availability).
        If prefer_start matches a returned slot (normalized), that slot is used; otherwise the
        earliest upcoming slot in the range is returned.
        """
        now = datetime.now(timezone.utc)
        range_start = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        range_end_dt = now + timedelta(days=max(1, horizon_days))
        range_end = range_end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            slots = await self.get_available_slots(range_start, range_end)
        except CalError as e:
            logger.warning("Cal.com slots request failed (check cal-api-version and event type): %s", e)
            return None
        if not slots:
            return None
        if prefer_start:
            want = self._normalize_start(prefer_start)
            for s in slots:
                if self._normalize_start(s) == want:
                    return s
        return slots[0]

    async def book_meeting(
        self,
        name: str,
        email: str,
        start_time: str,
        metadata: Optional[Dict[str, Any]] = None,
        booking_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a confirmed booking on Cal.com.
        Implements an idempotency check by verifying if a booking exists for this email+time.
        """
        # IDEMPOTENCY SAFEGUARD: Search for existing booking
        existing = await self._find_existing_booking(email, start_time)
        if existing is not None:
            logger.info("Duplicate booking detected for %s at %s. Returning existing ID.", email, start_time)
            return {"success": True, "booking_id": existing, "status": "existing"}

        return await self._execute_booking(
            name, email, start_time, metadata, booking_title=booking_title or name
        )

    async def _find_existing_booking(self, email: str, start_time: str) -> Optional[Union[int, str]]:
        """Checks if a lead already has a booking at the specified time."""
        url = f"{self.base_url}/bookings"
        params = {"email": email}
        want = self._normalize_start(start_time)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code != 200:
                return None
            try:
                bookings = self._extract_booking_dicts(resp.json().get("data"))
            except Exception as e:
                logger.warning("Cal bookings list parse failed; skipping idempotency check: %s", e)
                return None
            for b in bookings:
                b_start = b.get("start") or b.get("startTime")
                if self._normalize_start(b_start) == want:
                    bid = b.get("id") or b.get("bookingId") or b.get("uid")
                    if bid is not None:
                        return bid
        return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        retry=retry_if_exception_type((httpx.RequestError, CalError)),
        reraise=True
    )
    async def _execute_booking(
        self,
        name: str,
        email: str,
        start_time: str,
        metadata: Optional[Dict[str, Any]],
        booking_title: str,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/bookings"
        event_type_id = self._parse_event_type_id(self.event_type_id)
        if event_type_id is None:
            msg = (
                "CALCOM_EVENT_TYPE_ID is missing/invalid. Set a numeric event type ID in .env "
                "(e.g. CALCOM_EVENT_TYPE_ID=123456)."
            )
            logger.error(msg)
            return {"success": False, "error": msg}
        meta = dict(metadata or {})
        slug = (getattr(settings, "CALCOM_BOOKING_TITLE_SLUG", None) or "").strip()
        payload: Dict[str, Any] = {
            "eventTypeId": event_type_id,
            "start": start_time,
            "attendee": {
                "name": name,
                "email": email,
                "timeZone": "UTC",
                "language": "en",
            },
            "metadata": meta,
        }
        if slug:
            payload["bookingFieldsResponses"] = {slug: booking_title}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=self.headers, json=payload)

        if resp.status_code not in (200, 201):
            logger.error("Cal.com booking failed: %s", resp.text)
            raise CalError(f"Cal.com booking HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        booking_id = (
            (data.get("data") or {}).get("id")
            or data.get("id")
            or (data.get("data") or {}).get("bookingId")
            or (data.get("data") or {}).get("uid")
        )
        return {"success": True, "booking_id": booking_id, "status": "created", "raw": data}

    def get_booking_link(self, email: str, name: Optional[str] = None) -> str:
        """
        Public booking URL with pre-filled email. Slug/username come from env
        (CALCOM_PUBLIC_USERNAME, CALCOM_PUBLIC_EVENT_SLUG) so deploys are not hard-coded.
        """
        username = (getattr(settings, "CALCOM_PUBLIC_USERNAME", None) or "").strip()
        slug = (getattr(settings, "CALCOM_PUBLIC_EVENT_SLUG", None) or "").strip()
        if not username or not slug:
            logger.warning(
                "Cal booking link config missing (CALCOM_PUBLIC_USERNAME / CALCOM_PUBLIC_EVENT_SLUG); "
                "returning base Cal URL instead of hardcoded demo path."
            )
            return "https://cal.com"
        q = f"email={quote(email)}"
        if name:
            q += f"&name={quote(name)}"
        return f"https://cal.com/{username}/{slug}?{q}"

# Singleton instance
cal_client = CalClient()
