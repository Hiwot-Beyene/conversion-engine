from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from .ai_maturity import AIMaturityScore

class SignalMetadata(BaseModel):
    """Metadata for source attribution and staleness tracking."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attribution_url: Optional[str] = None
    evidence_strength: float = Field(default=0.0, ge=0.0, le=1.0)

class EnrichmentSignal(BaseModel):
    """Standardized output for every enrichment source."""
    source: str
    data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: SignalMetadata = Field(default_factory=SignalMetadata)
    error: Optional[str] = None

class HiringSignalBrief(BaseModel):
    """Merged view of all hiring signals for a company."""
    company_name: str
    signals: Dict[str, EnrichmentSignal]
    overall_confidence: float
    summary: Optional[str] = None
    velocity_60d: Optional[float] = None # Calculated delta
    ai_maturity: Optional[AIMaturityScore] = None # New 0-3 scoring

from .pipeline import EnrichmentPipeline
from .crunchbase import enrich_from_crunchbase
from .job_posts import enrich_from_job_posts
from .layoffs import enrich_from_layoffs
from .leadership import enrich_leadership_signals

__all__ = [
    "EnrichmentSignal", 
    "EnrichmentPipeline",
    "enrich_from_crunchbase",
    "enrich_from_job_posts",
    "enrich_from_layoffs",
    "enrich_leadership_signals"
]
