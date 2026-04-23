import logging
import os
import json
from typing import Optional, List
from agent.enrichment import EnrichmentSignal
from agent.config import settings
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

def enrich_from_job_posts(company_name: str) -> EnrichmentSignal:
    """
    Scans the job posts snapshot directory for relevant job listings.
    Uses fuzzy matching for company name if needed.
    """
    directory = settings.JOB_POSTS_SNAPSHOT_DIR
    if not directory or not os.path.exists(directory):
        return EnrichmentSignal(source="job_posts", error="Job posts directory not found")

    try:
        files = os.listdir(directory)
        if not files:
            return EnrichmentSignal(source="job_posts", confidence=1.0, data={"job_count": 0, "roles": []})

        relevant_jobs: List[dict] = []
        
        # This assumes job posts are stored in files that might contain company names
        # or separate JSON files per company. Here we'll search the content for a match.
        for filename in files:
            if not filename.endswith(".json"):
                continue
                
            with open(os.path.join(directory, filename), 'r') as f:
                try:
                    data = json.load(f)
                    # Support both list of jobs or single object
                    items = data if isinstance(data, list) else [data]
                    
                    for item in items:
                        item_company = item.get("company", "")
                        if fuzz.partial_ratio(company_name.lower(), item_company.lower()) > 90:
                            relevant_jobs.append(item)
                except json.JSONDecodeError:
                    continue

        return EnrichmentSignal(
            source="job_posts",
            confidence=0.9 if relevant_jobs else 1.0,
            data={
                "job_count": len(relevant_jobs),
                "roles": [j.get("title") for j in relevant_jobs[:10]],  # Limit to 10
                "latest_posting": relevant_jobs[0].get("posted_at") if relevant_jobs else None
            }
        )
    except Exception as e:
        logger.error(f"Job posts enrichment error: {e}")
        return EnrichmentSignal(source="job_posts", error=str(e))
