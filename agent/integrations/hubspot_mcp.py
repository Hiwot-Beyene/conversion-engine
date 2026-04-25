import logging
import httpx
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from agent.config import settings

logger = logging.getLogger(__name__)

class HubSpotError(Exception):
    """Custom exception for HubSpot API failures."""
    pass

class HubSpotClient:
    """
    Production-grade HubSpot integration for syncing lead data and enrichment signals.
    """

    def __init__(self):
        self.access_token = settings.HUBSPOT_ACCESS_TOKEN
        self.base_url = "https://api.hubapi.com"
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.RequestError, HubSpotError)),
        reraise=True
    )
    async def create_or_update_contact(self, email: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """
        Idempotent contact creation/update in HubSpot.
        """
        url = f"{self.base_url}/crm/v3/objects/contacts"
        
        # HubSpot expects search before update for clean state, 
        # but we can use the batch upsert or patch if we have the ID.
        # Here we'll use a search followed by create or update.
        
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        search_payload = {
            "filterGroups": [{
                "filters": [{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email
                }]
            }]
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.post(search_url, headers=self.headers, json=search_payload)
            search_data = search_resp.json()
            
            if search_data.get("total", 0) > 0:
                contact_id = search_data["results"][0]["id"]
                # Update
                update_url = f"{self.base_url}/crm/v3/objects/contacts/{contact_id}"
                resp = await client.patch(update_url, headers=self.headers, json={"properties": properties})
            else:
                # Create
                properties["email"] = email
                resp = await client.post(url, headers=self.headers, json={"properties": properties})

            if resp.status_code not in (200, 201):
                logger.error(f"HubSpot sync error: {resp.text}")
                return {"success": False, "error": resp.text}

            return {"success": True, "data": resp.json()}

    async def sync_enrichment_data(self, email: str, enrichment_signals: Dict[str, Any]):
        """
        Maps lead signals into HubSpot custom properties, including ICP fit.
        """
        from datetime import datetime, timezone
        
        cb_data = enrichment_signals.get("crunchbase", {}).get("data", {})
        
        # Mastery logic: Calculate ICP Segment/Fit
        # Example criteria: >50 employees and >$1M funding = "High Fit"
        employee_count = cb_data.get("employee_count", 0)
        funding_amount = cb_data.get("funding_amount_usd", 0)
        
        icp_fit = "Low Fit"
        if employee_count > 500:
            icp_fit = "Enterprise Fit"
        elif employee_count > 50 or funding_amount > 1000000:
            icp_fit = "Mid-Market / High Fit"

        properties = {
            "company": cb_data.get("name"),
            "website": cb_data.get("domain"),
            "industry": cb_data.get("sector"),
            "numberofemployees": str(employee_count),
            "icp_segment": icp_fit,  # Mastery field
            "last_enrichment_timestamp": datetime.now(timezone.utc).isoformat(), # Mastery field
            "lifecyclestage": "lead"
        }
        
        # Add custom signal metadata
        if enrichment_signals.get("layoffs", {}).get("data", {}).get("has_layoffs"):
            properties["notes"] = "Attention: Recent layoffs detected at this company."

        await self.create_or_update_contact(email, properties)

    async def log_event(self, email: str, event_type: str, body: str) -> Dict[str, Any]:
        """
        Logs a communication event (email, SMS, reply) as a HubSpot note.
        """
        # 1. Get contact ID
        search_url = f"{self.base_url}/crm/v3/objects/contacts/search"
        search_payload = {
            "filters": [{"propertyName": "email", "operator": "EQ", "value": email}]
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_resp = await client.post(search_url, headers=self.headers, json={"filterGroups": [{"filters": search_payload["filters"]}]})
            search_data = search_resp.json()
            
            if search_data.get("total", 0) == 0:
                logger.warning(f"Cannot log event: Contact {email} not found in HubSpot.")
                return {"success": False, "error": "Contact not found"}
            
            contact_id = search_data["results"][0]["id"]
            
            # 2. Create Note (Engagement)
            note_url = f"{self.base_url}/crm/v3/objects/notes"
            note_payload = {
                "properties": {
                    "hs_note_body": f"<b>[{event_type.upper()}]</b><br/>{body}",
                    "hubspot_owner_id": None # Optional
                },
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": 202 # Note to Contact
                            }
                        ]
                    }
                ]
            }
            
            resp = await client.post(note_url, headers=self.headers, json=note_payload)
            if resp.status_code not in (200, 201):
                logger.error(f"Failed to log HubSpot event: {resp.text}")
                return {"success": False, "error": resp.text}
                
            return {"success": True, "data": resp.json()}

# Singleton instance
hubspot_client = HubSpotClient()
