import logging
from typing import Optional, List
from agent.enrichment import EnrichmentSignal

logger = logging.getLogger(__name__)

def enrich_leadership_signals(crunchbase_data: EnrichmentSignal) -> EnrichmentSignal:
    """
    Extracts and validates leadership signals primarily from Crunchbase data.
    """
    if crunchbase_data.error:
        return EnrichmentSignal(source="leadership", error="Upstream Crunchbase data missing")

    try:
        founders = crunchbase_data.data.get("founders", [])
        
        if not founders:
            return EnrichmentSignal(source="leadership", confidence=0.5, data={"leadership_found": False})

        # Process founders list
        styled_leaders = []
        if isinstance(founders, list):
            for f in founders:
                if isinstance(f, dict):
                    styled_leaders.append({
                        "name": f.get("name"),
                        "role": f.get("role") or "Founder",
                        "linkedin": f.get("linkedin_url")
                    })
        elif isinstance(founders, str):
            # Maybe it's a raw string or comma separated
            styled_leaders = [{"name": founders, "role": "Founder"}]

        return EnrichmentSignal(
            source="leadership",
            confidence=0.9,
            data={
                "leadership_found": True,
                "leaders": styled_leaders,
                "is_founder_led": True if styled_leaders else False
            }
        )
    except Exception as e:
        logger.error(f"Leadership signal extraction error: {e}")
        return EnrichmentSignal(source="leadership", error=str(e))
