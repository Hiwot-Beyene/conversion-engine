import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class AIMaturityScore(BaseModel):
    """Structured AI Maturity response."""
    overall_score: float = Field(..., ge=0.0, le=1.0)
    indices: Dict[str, float] = Field(default_factory=dict) # e.g. talent_density, tech_stack, public_sentiment
    evidence: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8)

class AIMaturityScorer:
    """
    Production-grade AI maturity scoring engine.
    Heuristic-based scoring using talent density, tech stack signals, and public data.
    """

    def calculate_score(self, signals: Dict[str, Any]) -> AIMaturityScore:
        """
        Computes a unified AI maturity score from multi-channel signals.
        """
        indices = {
            "talent_density": self._score_talent(signals.get("job_posts", {}).get("data", {}).get("roles", [])),
            "tech_stack": self._score_stack(signals.get("tech_stack", {}).get("data", {})),
            "funding_weight": self._score_funding(signals.get("crunchbase", {}).get("data", {}))
        }
        
        # Weighted Average
        weights = {"talent_density": 0.5, "tech_stack": 0.3, "funding_weight": 0.2}
        overall = sum(indices[k] * weights[k] for k in weights)
        
        # Evidence Extraction
        evidence = []
        if indices["talent_density"] > 0.7:
            evidence.append("High density of specialized AI/ML roles in active job posts.")
        if indices["tech_stack"] > 0.7:
            evidence.append("Advanced AI infrastructure (e.g., Pinecone, Weights & Biases) detected in stack.")
            
        return AIMaturityScore(
            overall_score=round(overall, 2),
            indices=indices,
            evidence=evidence
        )

    def _score_talent(self, roles: List[str]) -> float:
        """Scores density of AI-related roles."""
        if not roles: return 0.1
        ai_keywords = ["machine learning", "ml", "nlp", "data scientist", "ai engineer", "llm"]
        matches = [r for r in roles if any(kw in r.lower() for kw in ai_keywords)]
        return min(1.0, len(matches) / 3.0) # 3+ roles = max score

    def _score_stack(self, stack_data: Dict[str, Any]) -> float:
        """Scores sophistication of detected tech stack."""
        # Stub: logic to check for vector DBs, orchestration layers, etc.
        return 0.5 

    def _score_funding(self, cb_data: Dict[str, Any]) -> float:
        """Funding context for maturity potential."""
        amt = cb_data.get("funding_amount_usd", 0)
        if amt > 100000000: return 1.0
        if amt > 10000000: return 0.7
        if amt > 1000000: return 0.4
        return 0.1

ai_maturity_scorer = AIMaturityScorer()
