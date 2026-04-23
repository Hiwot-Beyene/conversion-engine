import logging
import asyncio
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from agent.enrichment import EnrichmentSignal
from agent.enrichment.crunchbase import enrich_from_crunchbase
from agent.enrichment.job_posts import enrich_from_job_posts
from agent.enrichment.layoffs import enrich_from_layoffs
from agent.enrichment.leadership import enrich_leadership_signals

logger = logging.getLogger(__name__)

class EnrichmentPipeline:
    """
    Production-grade enrichment pipeline that orchestrates calls to multiple
    data sources and aggregates them into a structured lead enrichment report.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def run(self, company_name: str, domain: Optional[str] = None) -> Dict[str, EnrichmentSignal]:
        """
        Executes all enrichment modules in parallel where possible.
        """
        logger.info(f"Starting enrichment pipeline for: {company_name} ({domain or 'no domain'})")

        # 1. Crunchbase (DB Query - Async)
        cb_signal = await enrich_from_crunchbase(self.db_session, domain=domain, name=company_name)

        # 2. Run other enrichments in parallel
        loop = asyncio.get_event_loop()
        
        tasks = {
            "layoffs": loop.run_in_executor(None, enrich_from_layoffs, company_name),
            "job_posts": loop.run_in_executor(None, enrich_from_job_posts, company_name),
        }
        
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        mapped_results = dict(zip(tasks.keys(), results))

        # Handle potential exceptions from gather
        for key, res in mapped_results.items():
            if isinstance(res, Exception):
                logger.error(f"Error in {key} enrichment: {res}")
                mapped_results[key] = EnrichmentSignal(source=key, error=str(res))

        # 3. Leadership (Dependent on Crunchbase)
        leadership_signal = enrich_leadership_signals(cb_signal)

        # Final Aggregation
        final_signals = {
            "crunchbase": cb_signal,
            "layoffs": mapped_results["layoffs"],
            "job_posts": mapped_results["job_posts"],
            "leadership": leadership_signal
        }

        logger.info(f"Enrichment pipeline completed for {company_name}")
        return final_signals

    def _calculate_overall_confidence(self, signals: Dict[str, EnrichmentSignal]) -> float:
        """Simple average of confidence scores for successfully enriched sources."""
        valid_scores = [s.confidence for s in signals.values() if not s.error]
        if not valid_scores:
            return 0.0
        return sum(valid_scores) / len(valid_scores)
