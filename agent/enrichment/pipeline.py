import logging
import asyncio
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from agent.enrichment import EnrichmentSignal, HiringSignalBrief
from agent.enrichment.crunchbase import enrich_from_crunchbase
from agent.enrichment.job_posts import enrich_from_job_posts
from agent.enrichment.layoffs import enrich_from_layoffs
from agent.enrichment.leadership import enrich_leadership_signals
from agent.enrichment.ai_maturity import ai_maturity_scorer

logger = logging.getLogger(__name__)

class EnrichmentPipeline:
    """
    Production-grade enrichment pipeline that orchestrates calls to multiple
    data sources and aggregates them into a structured lead enrichment report.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def run(self, company_name: str, domain: Optional[str] = None) -> HiringSignalBrief:
        """
        Executes all enrichment modules in parallel where possible.
        Aggregates into a HiringSignalBrief.
        """
        logger.info(f"Starting enrichment pipeline for: {company_name}")

        # 1. Crunchbase (DB Query - Async)
        cb_signal = await enrich_from_crunchbase(self.db_session, domain=domain, name=company_name)

        # 2. Run other enrichments in parallel
        # Note: In production we use a worker pool or specialized clients.
        loop = asyncio.get_event_loop()
        
        results = await asyncio.gather(
            loop.run_in_executor(None, enrich_from_layoffs, company_name),
            enrich_from_job_posts(company_name),
            return_exceptions=True
        )
        
        layoff_signal = results[0] if not isinstance(results[0], Exception) else EnrichmentSignal(source="layoffs", error=str(results[0]))
        job_signal = results[1] if not isinstance(results[1], Exception) else EnrichmentSignal(source="job_posts", error=str(results[1]))

        # 3. Leadership (Dependent on Crunchbase)
        leadership_signal = enrich_leadership_signals(cb_signal)

        # Aggregation
        signals = {
            "crunchbase": cb_signal,
            "layoffs": layoff_signal,
            "job_posts": job_signal,
            "leadership": leadership_signal
        }

        # Velocity Logic (60-day window)
        # We extract from job posts signal which already computed its local delta
        velocity_60d = job_signal.data.get("velocity_60d", 0.0)

        # Confidence and Summary
        # AI Maturity Scoring (New 0-3 Mechanism)
        ai_maturity = ai_maturity_scorer.calculate_score(signals)

        brief = HiringSignalBrief(
            company_name=company_name,
            signals=signals,
            overall_confidence=overall_confidence,
            velocity_60d=velocity_60d,
            ai_maturity=ai_maturity,
            summary=ai_maturity.summary if ai_maturity else f"Enrichment for {company_name} complete."
        )

        return brief

    def _calculate_overall_confidence(self, signals: Dict[str, EnrichmentSignal]) -> float:
        """Simple average of confidence scores for successfully enriched sources."""
        valid_scores = [s.confidence for s in signals.values() if not s.error]
        if not valid_scores:
            return 0.0
        return sum(valid_scores) / len(valid_scores)
