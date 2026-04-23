import logging
import asyncio
from typing import List, Dict, Any
from playwright.async_api import async_playwright
from agent.enrichment import EnrichmentSignal

logger = logging.getLogger(__name__)

async def enrich_from_job_posts(company_name: str) -> EnrichmentSignal:
    """
    Scrapes active job listings for a company using Playwright.
    Target: Google Jobs Search (Publicly accessible).
    """
    logger.info(f"Scraping job posts for {company_name}...")
    
    try:
        async with async_playwright() as p:
            # 1. Launch Browser (Headless for production)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # 2. Search for jobs
            # Using Google Search with job filter to avoid direct board login walls
            query = f"{company_name} careers active openings"
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            
            await page.goto(search_url, wait_until="networkidle")
            
            # 3. Extract Titles (Basic selector for search results or job snippets)
            # This is a heuristic approach to find job-related titles in snippets
            selectors = ["h3", ".vv778b", ".LC20lb"]
            job_titles = []
            
            for selector in selectors:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    text = await el.inner_text()
                    # Filter for relevance
                    if any(kw in text.lower() for kw in ["hiring", "job", "career", "engineer", "manager", "role"]):
                        if company_name.lower() in text.lower() or len(text) > 5:
                            job_titles.append(text.strip())
            
            await browser.close()
            
            # 4. Result Formatting
            unique_jobs = list(set(job_titles))[:10] # Top 10 unique findings
            
            return EnrichmentSignal(
                source="job_posts_scraper",
                confidence=0.8 if unique_jobs else 1.0, # 1.0 confidence in "no jobs" if search is clean
                data={
                    "job_count": len(unique_jobs),
                    "roles": unique_jobs,
                    "search_method": "playwright_google_scrape"
                }
            )
            
    except Exception as e:
        logger.error(f"Playwright scraping failed for {company_name}: {e}")
        return EnrichmentSignal(source="job_posts_scraper", error=str(e))
