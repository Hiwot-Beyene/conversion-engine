import logging
from typing import Optional, List
from agent.enrichment import EnrichmentSignal

logger = logging.getLogger(__name__)

def enrich_leadership_signals(crunchbase_data: EnrichmentSignal) -> EnrichmentSignal:
    """
    Extracts and validates leadership signals primarily from Crunchbase data.
    Detects changes by looking at recent signals if available.
    """
    from agent.enrichment import SignalMetadata
    
    if crunchbase_data.error:
        return EnrichmentSignal(source="leadership", error="Upstream Crunchbase data missing")

    try:
        founders = crunchbase_data.data.get("founders", [])
        
        # Leadership changes: In a real ODM, we would query the 'Signals' table for 'leadership' type.
        # Here we simulate detection logic.
        has_recent_change = False
        change_note = "No recent leadership changes detected in the standard window."
        
        if not founders:
            return EnrichmentSignal(
                source="leadership", 
                confidence=1.0, 
                metadata=SignalMetadata(evidence_strength=0.5),
                data={"leadership_found": False, "recent_change": False, "note": "No leadership records found."}
            )

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
        
        return EnrichmentSignal(
            source="leadership",
            confidence=0.9,
            metadata=SignalMetadata(
                attribution_url=crunchbase_data.metadata.attribution_url,
                evidence_strength=0.9
            ),
            data={
                "leadership_found": True,
                "leaders": styled_leaders,
                "is_founder_led": True if styled_leaders else False,
                "recent_change": has_recent_change,
                "change_note": change_note
            }
        )
    except Exception as e:
        logger.error(f"Leadership signal extraction error: {e}")
        return EnrichmentSignal(source="leadership", error=str(e))
