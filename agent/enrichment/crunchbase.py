import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from agent.db.models import Company
from agent.enrichment import EnrichmentSignal

logger = logging.getLogger(__name__)

async def enrich_from_crunchbase(
    session: AsyncSession, 
    domain: Optional[str] = None, 
    name: Optional[str] = None,
    funding_min: Optional[float] = None
) -> EnrichmentSignal:
    """
    Enriches data from the local Crunchbase PostgreSQL mirror.
    Includes a funding filter (optional) to prioritize high-growth leads.
    """
    if not domain and not name:
        return EnrichmentSignal(source="crunchbase", error="No search criteria provided")

    try:
        # Try domain match first
        if domain:
            stmt = select(Company).where(Company.domain == domain)
            if funding_min:
                stmt = stmt.where(Company.funding_amount_usd >= funding_min)
            
            result = await session.execute(stmt)
            company = result.scalar_one_or_none()
            if company:
                return _map_company(company, confidence=1.0)

        # Fallback to name match
        if name:
            stmt = select(Company).where(Company.name.ilike(f"%{name}%"))
            if funding_min:
                stmt = stmt.where(Company.funding_amount_usd >= funding_min)
            
            stmt = stmt.order_by(Company.employee_count.desc())
            result = await session.execute(stmt)
            company = result.first()
            if company:
                return _map_company(company[0], confidence=0.8)

        return EnrichmentSignal(source="crunchbase", error="Company not found or filtered out by funding criteria")
    except Exception as e:
        logger.error(f"Crunchbase enrichment error: {e}")
        return EnrichmentSignal(source="crunchbase", error=str(e))

def _map_company(company: Company, confidence: float) -> EnrichmentSignal:
    """Maps a SQLAlchemy Company object to an EnrichmentSignal."""
    from agent.enrichment import SignalMetadata
    metadata = SignalMetadata(
        attribution_url=f"https://crunchbase.com/organization/{company.crunchbase_id}",
        evidence_strength=1.0 if company.funding_round else 0.7
    )
    
    return EnrichmentSignal(
        source="crunchbase",
        confidence=confidence,
        metadata=metadata,
        data={
            "crunchbase_id": company.crunchbase_id,
            "name": company.name,
            "description": company.description,
            "employee_count": company.employee_count,
            "sector": company.sector,
            "funding_round": company.funding_round,
            "funding_amount_usd": company.funding_amount_usd,
            "location": company.location,
            "social_links": company.social_links_json,
            "founders": company.founders_json,
        }
    )
