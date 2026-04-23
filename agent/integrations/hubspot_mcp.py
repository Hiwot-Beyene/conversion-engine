import logging
import httpx
from typing import Dict, Any, Optional
from agent.config import settings

logger = logging.getLogger(__name__)

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
        Maps lead signals into HubSpot custom properties.
        """
        # Map signals to HubSpot internal properties (assuming these exist in HS)
        cb_data = enrichment_signals.get("crunchbase", {}).get("data", {})
        
        properties = {
            "company": cb_data.get("name"),
            "website": cb_data.get("domain"),
            "industry": cb_data.get("sector"),
            "numberofemployees": str(cb_data.get("employee_count", "")),
            "lifecyclestage": "lead"
        }
        
        # Add custom signal metadata if needed
        if enrichment_signals.get("layoffs", {}).get("data", {}).get("has_layoffs"):
            properties["notes"] = "Attention: Recent layoffs detected at this company."

        await self.create_or_update_contact(email, properties)

# Singleton instance
hubspot_client = HubSpotClient()
