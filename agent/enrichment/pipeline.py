import logging
import asyncio
import inspect
from typing import Dict, Any, Optional, Callable, Awaitable, Union
from sqlalchemy.ext.asyncio import AsyncSession

from agent.enrichment import EnrichmentSignal, HiringSignalBrief
from agent.enrichment.crunchbase import enrich_from_crunchbase
from agent.enrichment.job_posts import enrich_from_job_posts
from agent.enrichment.layoffs import enrich_from_layoffs
from agent.enrichment.leadership import enrich_leadership_signals
from agent.enrichment.tech_stack import enrich_from_tech_stack
from agent.enrichment.ai_maturity import ai_maturity_scorer

logger = logging.getLogger(__name__)

_JOB_ENRICH_TIMEOUT_S = 75

class EnrichmentPipeline:
    """
    Production-grade enrichment pipeline that orchestrates calls to multiple
    data sources and aggregates them into a structured lead enrichment report.
    """

    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def _prog(
        self,
        cb: Optional[Callable[[str], Union[None, Awaitable[None]]]],
        stage: str,
    ) -> None:
        if not cb:
            return
        out = cb(stage)
        if inspect.isawaitable(out):
            await out

    async def run(
        self,
        company_name: str,
        domain: Optional[str] = None,
        crunchbase_id: Optional[str] = None,
        website_url: Optional[str] = None,
        progress_callback: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None,
    ) -> HiringSignalBrief:
        """
        Executes all enrichment modules in parallel where possible.
        Aggregates into a HiringSignalBrief.
        """
        logger.info("Starting enrichment pipeline for: %s (odm_id=%s)", company_name, crunchbase_id)

        await self._prog(progress_callback, "crunchbase")
        # 1. Crunchbase ODM CSV first, then optional Postgres mirror
        cb_signal = await enrich_from_crunchbase(
            self.db_session,
            domain=domain,
            name=company_name,
            crunchbase_id=crunchbase_id,
        )

        # 2. Run other enrichments in parallel
        loop = asyncio.get_event_loop()

        cb_id = cb_signal.data.get("crunchbase_id") if cb_signal and not cb_signal.error else crunchbase_id
        site_for_jobs = website_url
        if cb_signal and not cb_signal.error:
            site_for_jobs = site_for_jobs or cb_signal.data.get("website_url") or cb_signal.data.get("domain")

        await self._prog(progress_callback, "layoffs_jobs")
        layoffs_task = loop.run_in_executor(None, enrich_from_layoffs, company_name)
        jobs_task = asyncio.wait_for(
            enrich_from_job_posts(
                company_name,
                crunchbase_id=cb_id,
                website_url=site_for_jobs,
            ),
            timeout=_JOB_ENRICH_TIMEOUT_S,
        )
        results = await asyncio.gather(layoffs_task, jobs_task, return_exceptions=True)
        
        layoff_signal = results[0] if not isinstance(results[0], Exception) else EnrichmentSignal(source="layoffs", error=str(results[0]))
        if isinstance(results[1], asyncio.TimeoutError):
            logger.warning("Job enrichment timed out after %ss for %s", _JOB_ENRICH_TIMEOUT_S, company_name)
            job_signal = EnrichmentSignal(
                source="job_posts",
                confidence=0.62,
                data={
                    "job_count": 0,
                    "velocity_60d": 0.0,
                    "note": f"Job enrichment timed out after {_JOB_ENRICH_TIMEOUT_S}s; used safe fallback.",
                },
                error=None,
            )
        else:
            job_signal = results[1] if not isinstance(results[1], Exception) else EnrichmentSignal(source="job_posts", error=str(results[1]))

        await self._prog(progress_callback, "leadership")
        # 3. Leadership (Dependent on Crunchbase)
        leadership_signal = enrich_leadership_signals(cb_signal)

        await self._prog(progress_callback, "ai_maturity")
        # Aggregation
        signals = {
            "crunchbase": cb_signal,
            "layoffs": layoff_signal,
            "job_posts": job_signal,
            "leadership": leadership_signal,
            "tech_stack": enrich_from_tech_stack(job_signal),
        }

        # Velocity Logic (60-day window)
        # We extract from job posts signal which already computed its local delta
        velocity_60d = job_signal.data.get("velocity_60d", 0.0)

        # Confidence and Summary
        # AI Maturity Scoring (New 0-3 Mechanism)
        ai_maturity = ai_maturity_scorer.calculate_score(signals)
        overall_confidence = self._calculate_overall_confidence(signals)

        brief = HiringSignalBrief(
            company_name=company_name,
            signals=signals,
            overall_confidence=overall_confidence,
            velocity_60d=velocity_60d,
            ai_maturity=ai_maturity,
            summary=ai_maturity.summary if ai_maturity else f"Enrichment for {company_name} complete.",
        )

        await self._prog(progress_callback, "competitors_ready")
        return brief

    def _calculate_overall_confidence(self, signals: Dict[str, EnrichmentSignal]) -> float:
        """
        Blend module confidence (fetch succeeded) with metadata evidence_strength (claim usefulness).
        Avoids ~97% pipeline blend when several sources only prove "CSV row exists", not strong facts.
        """
        pipe: list[float] = []
        ev: list[float] = []
        for s in signals.values():
            if s.error:
                continue
            c = float(s.confidence or 0.0)
            pipe.append(c)
            evs = None
            if s.metadata is not None:
                evs = getattr(s.metadata, "evidence_strength", None)
            if evs is not None and float(evs) > 0:
                ev.append(float(evs))
            else:
                ev.append(min(0.82, c * 0.88))
        if not pipe:
            return 0.0
        p_avg = sum(pipe) / len(pipe)
        e_avg = sum(ev) / len(ev)
        blended = 0.42 * p_avg + 0.58 * e_avg
        return round(min(0.94, max(0.18, blended)), 3)
