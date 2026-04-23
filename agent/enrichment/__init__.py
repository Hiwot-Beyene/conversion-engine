from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class EnrichmentSignal(BaseModel):
    """Standardized output for every enrichment source."""
    source: str
    data: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error: Optional[str] = None

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
