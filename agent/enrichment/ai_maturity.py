import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

class SignalJustification(BaseModel):
    """Per-signal rationale and confidence."""
    score: float
    justification: str
    confidence: float

class AIMaturityScore(BaseModel):
    """
    Structured AI Maturity response.
    Satisfies requirements for 6-category analysis and 0-3 integer mapping.
    """
    integer_score: int = Field(..., ge=0, le=3) # 0: Silent, 1: Emergent, 2: Active, 3: Mature
    normalized_score: float = Field(..., ge=0.0, le=1.0)
    indices: Dict[str, SignalJustification] = Field(default_factory=dict)
    overall_confidence: float = Field(default=0.0)
    summary: str

class AIMaturityScorer:
    """
    Production-grade AI maturity scoring engine.
    Analyzes six signal categories: Talent, Stack, Funding, Velocity, Leadership, and Advocacy.
    """

    def calculate_score(self, signals: Dict[str, Any]) -> AIMaturityScore:
        """
        Computes a unified AI maturity score from six signal categories.
        Explicitly handles silent companies with a 0 score.
        """
        # 1. Individual Signal Analysis
        raw_indices = {
            "talent": self._analyze_talent(signals.get("job_posts", {})),
            "tech_stack": self._analyze_stack(signals.get("tech_stack", {})),
            "funding": self._analyze_funding(signals.get("crunchbase", {})),
            "velocity": self._analyze_velocity(signals.get("job_posts", {})),
            "leadership": self._analyze_leadership(signals.get("leadership", {})),
            "advocacy": self._analyze_advocacy(signals.get("crunchbase", {}))
        }

        # 2. Weighted Aggregation
        weights = {
            "talent": 0.30,
            "tech_stack": 0.20,
            "funding": 0.10,
            "velocity": 0.20,
            "leadership": 0.10,
            "advocacy": 0.10
        }

        weighted_score = sum(raw_indices[k].score * weights[k] for k in weights)
        avg_confidence = sum(raw_indices[k].confidence for k in weights) / len(weights)

        # 3. Handle Silent Companies
        # If total score is negligible or all major high-confidence signals are missing
        if weighted_score < 0.1 or all(raw_indices[k].score < 0.1 for k in ["talent", "tech_stack", "velocity"]):
            return AIMaturityScore(
                integer_score=0,
                normalized_score=0.0,
                indices=raw_indices,
                overall_confidence=avg_confidence,
                summary="Company is 'silent' with no detectable public AI signals across target channels."
            )

        # 4. Integer Mapping (0-3)
        if weighted_score >= 0.75:
            integer_score = 3
        elif weighted_score >= 0.45:
            integer_score = 2
        else:
            integer_score = 1

        return AIMaturityScore(
            integer_score=integer_score,
            normalized_score=round(weighted_score, 2),
            indices=raw_indices,
            overall_confidence=round(avg_confidence, 2),
            summary=self._generate_summary(integer_score, raw_indices)
        )

    def _analyze_talent(self, signal: Dict[str, Any]) -> SignalJustification:
        roles = signal.get("data", {}).get("roles", [])
        if not roles:
            return SignalJustification(score=0.0, justification="No AI/ML roles found.", confidence=1.0)
        
        keywords = ["machine learning", "ml", "nlp", "ai engineer", "llm"]
        matches = [r for r in roles if any(kw in r.lower() for kw in keywords)]
        score = min(1.0, len(matches) / 3.0)
        return SignalJustification(
            score=score,
            justification=f"Found {len(matches)} AI-related roles in active listings.",
            confidence=0.9
        )

    def _analyze_stack(self, signal: Dict[str, Any]) -> SignalJustification:
        # Mock stack analysis
        has_ai_stack = signal.get("data", {}).get("has_vector_db", False)
        return SignalJustification(
            score=1.0 if has_ai_stack else 0.4,
            justification="Infrastructure suggests initial AI capability." if not has_ai_stack else "Advanced AI stack detected.",
            confidence=0.7
        )

    def _analyze_funding(self, signal: Dict[str, Any]) -> SignalJustification:
        funding = signal.get("data", {}).get("funding_amount_usd", 0)
        score = 1.0 if funding > 50000000 else (0.5 if funding > 5000000 else 0.1)
        return SignalJustification(
            score=score,
            justification=f"Funding level of ${funding:,.0f} supports R&D investment.",
            confidence=1.0
        )

    def _analyze_velocity(self, signal: Dict[str, Any]) -> SignalJustification:
        velocity = signal.get("data", {}).get("velocity_60d", 0.0)
        score = min(1.0, max(0.0, (velocity + 0.5) / 1.5)) # Normalize -0.5..1.0 to 0..1
        return SignalJustification(
            score=score,
            justification=f"Hiring velocity of {velocity:.2f} roles/day.",
            confidence=0.8
        )

    def _analyze_leadership(self, signal: Dict[str, Any]) -> SignalJustification:
        has_change = signal.get("data", {}).get("recent_change", False)
        return SignalJustification(
            score=0.8 if has_change else 0.3,
            justification="Recent leadership transition creates window for AI pivoting." if has_change else "Stable leadership stack.",
            confidence=0.85
        )

    def _analyze_advocacy(self, signal: Dict[str, Any]) -> SignalJustification:
        desc = signal.get("data", {}).get("description", "").lower()
        has_keywords = any(kw in desc for kw in ["ai-first", "autonomous", "intelligent", "transforming"])
        return SignalJustification(
            score=0.9 if has_keywords else 0.2,
            justification="Corporate messaging explicitly prioritizes AI capability." if has_keywords else "Low public AI advocacy.",
            confidence=0.6
        )

    def _generate_summary(self, integer_score: int, indices: Dict[str, SignalJustification]) -> str:
        levels = {0: "Silent", 1: "Emergent", 2: "Active", 3: "Mature"}
        top_signal = max(indices.items(), key=lambda x: x[1].score)
        return f"Level {integer_score} ({levels[integer_score]}): Driven primarily by {top_signal[0]} ({top_signal[1].justification})"

ai_maturity_scorer = AIMaturityScorer()
