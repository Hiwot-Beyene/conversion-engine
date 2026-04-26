import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from agent.db.models import Company
from agent.enrichment import EnrichmentSignal, SignalMetadata
from agent.enrichment.crunchbase_odm import (
    enrichment_signal_from_odm_row,
    get_odm_row_by_id,
    _load_odm_dataframe,
)

logger = logging.getLogger(__name__)


def _map_company(company: Company, confidence: float) -> EnrichmentSignal:
    """Maps a SQLAlchemy Company row to an EnrichmentSignal."""
    metadata = SignalMetadata(
        attribution_url=f"https://www.crunchbase.com/organization/{company.crunchbase_id}",
        evidence_strength=1.0 if company.funding_round else 0.7,
    )

    return EnrichmentSignal(
        source="crunchbase",
        confidence=confidence,
        metadata=metadata,
        data={
            "crunchbase_id": company.crunchbase_id,
            "name": company.name,
            "domain": company.domain,
            "website_url": company.domain,
            "description": getattr(company, "description", None),
            "employee_count": company.employee_count,
            "sector": company.sector,
            "funding_round": company.funding_round,
            "funding_amount_usd": company.funding_amount_usd,
            "location": company.location,
            "social_links": company.social_links_json,
            "founders": company.founders_json,
        },
    )


async def enrich_from_crunchbase(
    session: AsyncSession,
    domain: Optional[str] = None,
    name: Optional[str] = None,
    crunchbase_id: Optional[str] = None,
    funding_min: Optional[float] = None,
) -> EnrichmentSignal:
    """
    Firmographics: ODM CSV first (grading source of truth), then optional local Postgres mirror.

    The ODM `id` field is a Crunchbase permalink slug — it must not be reused as BuiltIn/Wellfound
    company URL slugs (those platforms use different identifiers).
    """
    if not domain and not name and not crunchbase_id:
        return EnrichmentSignal(source="crunchbase", error="No search criteria provided")

    if crunchbase_id:
        row = get_odm_row_by_id(str(crunchbase_id))
        if row is not None:
            logger.info("Crunchbase enrichment from ODM CSV for id=%s", crunchbase_id)
            return enrichment_signal_from_odm_row(row, confidence=1.0)

    if name:
        df = _load_odm_dataframe()
        if df is not None and "name" in df.columns:
            mask = df["name"].astype(str).str.contains(str(name), case=False, na=False)
            hits = df[mask]
            if not hits.empty:
                row = hits.iloc[0]
                logger.info("Crunchbase enrichment from ODM CSV by name match: %s", name)
                return enrichment_signal_from_odm_row(row, confidence=0.85)

    try:
        if domain:
            stmt = select(Company).where(Company.domain == domain)
            if funding_min:
                stmt = stmt.where(Company.funding_amount_usd >= funding_min)
            result = await session.execute(stmt)
            company = result.scalar_one_or_none()
            if company:
                return _map_company(company, confidence=1.0)

        if name:
            stmt = select(Company).where(Company.name.ilike(f"%{name}%"))
            if funding_min:
                stmt = stmt.where(Company.funding_amount_usd >= funding_min)
            stmt = stmt.order_by(Company.employee_count.desc())
            result = await session.execute(stmt)
            row = result.first()
            if row:
                return _map_company(row[0], confidence=0.8)

    except ProgrammingError as e:
        logger.warning("Postgres companies table out of sync with ORM (%s); ODM CSV only.", e)
    except Exception as e:
        logger.error("Crunchbase DB enrichment error: %s", e)

    if crunchbase_id:
        try:
            stmt = (
                select(
                    Company.crunchbase_id,
                    Company.name,
                    Company.domain,
                    Company.sector,
                    Company.employee_count,
                    Company.funding_round,
                    Company.funding_amount_usd,
                    Company.location,
                    Company.founders_json,
                    Company.social_links_json,
                ).where(Company.crunchbase_id == str(crunchbase_id))
            )
            r = (await session.execute(stmt)).one_or_none()
            if r:
                m = r._mapping

                return EnrichmentSignal(
                    source="crunchbase_pg_partial",
                    confidence=0.95,
                    metadata=SignalMetadata(
                        attribution_url=f"https://www.crunchbase.com/organization/{m['crunchbase_id']}",
                        evidence_strength=0.85,
                    ),
                    data={
                        "crunchbase_id": m["crunchbase_id"],
                        "name": m["name"],
                        "domain": m["domain"],
                        "website_url": m["domain"],
                        "description": None,
                        "employee_count": m["employee_count"],
                        "sector": m["sector"],
                        "funding_round": m["funding_round"],
                        "funding_amount_usd": m["funding_amount_usd"],
                        "location": m["location"],
                        "social_links": m["social_links_json"],
                        "founders": m["founders_json"] or [],
                    },
                )
        except ProgrammingError:
            logger.debug("Narrow company select failed (schema drift).")
        except Exception as e:
            logger.debug("Narrow company lookup failed: %s", e)

    return EnrichmentSignal(
        source="crunchbase",
        error="Company not found in ODM CSV or local mirror",
    )
