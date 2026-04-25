import logging
import pandas as pd
from typing import Optional
from agent.enrichment import EnrichmentSignal
from agent.config import settings

logger = logging.getLogger(__name__)

def enrich_from_layoffs(company_name: str) -> EnrichmentSignal:
    """
    Enriches data from the layoffs.fyi CSV snapshot.
    """
    path = settings.LAYOFFS_CSV_PATH
    if not path:
        return EnrichmentSignal(source="layoffs", error="Layoffs CSV path not configured")

    try:
        df = pd.read_csv(path)
        # Search for company name (case-insensitive)
        match = df[df['Company'].str.contains(company_name, case=False, na=False)]
        
        from agent.enrichment import SignalMetadata
        
        if match.empty:
            return EnrichmentSignal(
                source="layoffs", 
                confidence=1.0, 
                metadata=SignalMetadata(evidence_strength=1.0),
                data={"has_layoffs": False, "note": "No layoff history found in layoffs.fyi snapshot."}
            )

        # Get the most recent layoff
        latest = match.sort_values(by='Date', ascending=False).iloc[0]
        
        return EnrichmentSignal(
            source="layoffs",
            confidence=1.0,
            metadata=SignalMetadata(
                attribution_url=str(latest['Source']),
                evidence_strength=1.0
            ),
            data={
                "has_layoffs": True,
                "latest_layoff_date": str(latest['Date']),
                "laid_off_count": int(latest['Laid_Off_Count']) if pd.notnull(latest['Laid_Off_Count']) else None,
                "percentage": float(latest['Percentage']) if pd.notnull(latest['Percentage']) else None,
                "industry": latest['Industry'],
                "source_url": latest['Source']
            }
        )
    except Exception as e:
        logger.error(f"Layoffs enrichment error: {e}")
        return EnrichmentSignal(source="layoffs", error=str(e))
