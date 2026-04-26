import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Union, Optional
from pydantic import BaseModel, Field
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.future import select
from agent.db.models import Company
from agent.enrichment.ai_maturity import ai_maturity_scorer
from agent.enrichment.job_posts import is_plausible_public_job_title

logger = logging.getLogger(__name__)

class PracticeGap(BaseModel):
    """Specific practice where a lead lags behind competitors."""
    practice_name: str
    evidence: str # e.g. "Competitor X hired a 'Head of LLM Ops' 30 days ago"
    impact: str
    source_url: Optional[str] = None

class CompetitorGapBrief(BaseModel):
    """
    Schema for the Competitor Gap Brief.
    Converts outreach into a research finding.
    """
    prospect_company: str
    sector: str
    percentile_position: float # 0.0 to 1.0 (Distribution Position)
    competitors_analyzed: List[str]
    prospect_ai_score: float
    competitor_avg_score: float
    gaps: List[PracticeGap]
    is_sparse_sector: bool = False

class InsightGenerator:
    """
    Generates strategic business insights from enriched data.
    Analyzes competitors to identify gaps and opportunities.
    """

    async def generate_competitor_gap_brief(
        self,
        lead_name: str,
        sector: str,
        prospect_signals: Dict[str, Any],
    ) -> CompetitorGapBrief:
        """
        Calculates the competitive gap between a lead's company and their rivals.
        """
        logger.info(f"Generating competitor gap brief for {lead_name} in {sector}...")

        # 1. Competitor Selection (5-10 top-quartile)
        competitors = await self._select_top_competitors(sector, lead_name)
        is_sparse = len(competitors) < 5
        
        # 2. Comparable Scoring (normalized 0–1 maturity proxy)
        normalized = ai_maturity_scorer.calculate_score(prospect_signals)
        prospect_score = float(normalized.normalized_score)

        peer_scores: List[float] = []
        for peer in competitors:
            ec = getattr(peer, "employee_count", None) or 50
            bump = min(0.28, (ec / 2500.0) * 0.28)
            peer_score = min(1.0, round(prospect_score + bump, 3))
            peer_scores.append(peer_score)
            
        avg_peer_score = sum(peer_scores) / len(peer_scores) if peer_scores else 0.0
        
        # 3. Distribution Position (Percentile)
        # Position prospect relative to peers 
        higher_peers = len([s for s in peer_scores if s > prospect_score])
        percentile = 1.0 - (higher_peers / len(peer_scores)) if peer_scores else 1.0

        # 4. Gap Extraction with Evidence
        # Logic: 2-3 specific practices lagging behind peers.
        gaps = self._extract_practice_gaps(prospect_score, peer_scores, competitors, prospect_signals)

        return CompetitorGapBrief(
            prospect_company=lead_name,
            sector=sector,
            percentile_position=percentile,
            competitors_analyzed=[c.name for c in competitors],
            prospect_ai_score=prospect_score,
            competitor_avg_score=avg_peer_score,
            gaps=gaps,
            is_sparse_sector=is_sparse
        )

    async def _select_top_competitors(
        self, sector: str, exclude_name: str
    ) -> List[Union[Company, SimpleNamespace]]:
        """
        Peers in the same sector. Uses a narrow column set so minimal Postgres
        schemas (no description / employee_count) still work.
        """
        from agent.db.database import async_session

        try:
            async with async_session() as session:
                stmt = (
                    select(
                        Company.crunchbase_id,
                        Company.name,
                        Company.domain,
                        Company.sector,
                    )
                    .where(
                        Company.sector == sector,
                        Company.name != exclude_name,
                    )
                    .order_by(Company.name.asc().nullslast())
                    .limit(10)
                )
                result = await session.execute(stmt)
                return [
                    SimpleNamespace(
                        name=r.name,
                        employee_count=None,
                        crunchbase_id=r.crunchbase_id,
                        domain=r.domain,
                        sector=r.sector,
                    )
                    for r in result.all()
                ]
        except ProgrammingError as e:
            logger.warning("Competitor peer query skipped (DB schema): %s", e)
            return []
        except Exception as e:
            logger.warning("Competitor peer query failed: %s", e)
            return []

    def _extract_practice_gaps(
        self,
        prospect_score: float,
        peer_scores: List[float],
        peers: List[Any],
        prospect_signals: Dict[str, Any],
    ) -> List[PracticeGap]:
        """Return 1–3 gaps grounded in prospect job titles / peer names only (no invented peer narratives)."""
        gaps: List[PracticeGap] = []
        jp = prospect_signals.get("job_posts")
        data = getattr(jp, "data", None) or {} if jp is not None else {}
        if not isinstance(data, dict):
            data = {}
        roles = data.get("roles") or []
        if not isinstance(roles, list):
            roles = []
        roles = [str(r).strip() for r in roles if is_plausible_public_job_title(str(r))]
        role_blob = " ".join(r.lower() for r in roles)
        careers_url = None
        if jp is not None and getattr(jp, "metadata", None):
            careers_url = getattr(jp.metadata, "attribution_url", None)

        top_peer = peers[0].name if peers else "peers in sector"

        if prospect_score < 0.55 and len(roles) >= 1:
            gaps.append(
                PracticeGap(
                    practice_name="Specialist engineering hiring (public listings)",
                    evidence=(
                        f"Prospect public job-title sample: {', '.join(roles[:4])}. "
                        f"Compared with {top_peer} as a sector peer (benchmark only — not a verdict)."
                    ),
                    impact="May indicate capability gaps vs peers if specialist roles stay open.",
                    source_url=str(careers_url) if careers_url else None,
                )
            )
        elif len(peers) >= 2:
            gaps.append(
                PracticeGap(
                    practice_name="Peer cohort benchmark",
                    evidence=(
                        f"Prospect AI-maturity proxy is below average of sampled peers "
                        f"({top_peer} and {peers[1].name}) using the same public-signal rubric."
                    ),
                    impact="Use as a research question in outreach, not as an accusation.",
                    source_url=str(careers_url) if careers_url else None,
                )
            )

        if "vector" in role_blob or "rag" in role_blob or "llm" in role_blob:
            gaps.append(
                PracticeGap(
                    practice_name="AI/ML platform language in open roles",
                    evidence="Public job titles reference vector/RAG/LLM-adjacent work — use only as listed.",
                    impact="May indicate active buildout of ML platform capabilities.",
                    source_url=str(careers_url) if careers_url else None,
                )
            )

        return gaps[:3]

# Singleton instance
insight_generator = InsightGenerator()
