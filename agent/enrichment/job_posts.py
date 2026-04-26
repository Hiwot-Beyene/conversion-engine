import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlparse

from playwright.async_api import async_playwright

from agent.config import settings
from agent.enrichment import EnrichmentSignal, SignalMetadata
from agent.paths import resolve_repo_path

logger = logging.getLogger(__name__)

_NAV_TIMEOUT_MS = 14_000
_POST_LOAD_MS = 1_200
_MAX_URLS_TOTAL = 5
_MAX_CAREER_URLS = 3

_MARKETING_HEADING_RE = re.compile(
    r"^(how\s+.+\s+works|what\s+we\s+do|why\s+.+|get\s+started|our\s+story|meet\s+the\s+team|"
    r"life\s+at\s+.+|join\s+our\s+team|work\s+with\s+us|open\s+positions?)\s*$",
    re.I,
)

_JOB_TITLE_KEYWORDS_RE = re.compile(
    r"\b(engineer|engineering|developer|scientist|researcher|manager|management|director|"
    r"lead\b|analyst|designer|architect|devops|sre|platform|data\s|ml\s|machine\s+learning|"
    r"\bmachine learning\b|product\s+manager|sales|account\s+executive|marketing|legal|counsel|"
    r"hr\b|people\s+ops|recruiter|officer|head\s+of|vp\b|vice\s+president|intern|contractor|"
    r"full[\s-]?stack|backend|frontend|software|quant|applied\s+scientist)\b",
    re.I,
)


def _looks_jobish_but_ambiguous(title: str) -> bool:
    """
    Count only potentially job-related strings as discarded candidates.
    This avoids inflating noise counts with generic nav/marketing headings.
    """
    t = (title or "").strip().lower()
    if not t:
        return False
    if any(x in t for x in ("job", "jobs", "career", "careers", "hiring", "vacanc", "position", "role")):
        return True
    if _JOB_TITLE_KEYWORDS_RE.search(title):
        return True
    return False


def is_plausible_public_job_title(title: str) -> bool:
    """
    Drop careers-page noise (nav headings, marketing H2s) so counts and narratives stay honest.
    Exported for insights / UI consumers.
    """
    t = (title or "").strip()
    if len(t) < 8 or len(t) > 200:
        return False
    tl = t.lower().strip()
    if _MARKETING_HEADING_RE.match(t):
        return False
    nav_noise = {
        "careers",
        "jobs",
        "job openings",
        "open positions",
        "open roles",
        "join us",
        "we're hiring",
        "home",
        "about",
        "blog",
        "contact",
        "privacy policy",
        "terms of service",
    }
    if tl in nav_noise or tl.rstrip(".") in nav_noise:
        return False
    if _JOB_TITLE_KEYWORDS_RE.search(t):
        return True
    if re.search(r"\s[-–|]\s", t) and len(t) <= 120:
        return True
    return False


def _host_from_website(website: Optional[str]) -> Optional[str]:
    """Derive hostname from CSV `website` column (URL or bare domain)."""
    if not website:
        return None
    s = str(website).strip()
    if s.startswith("http"):
        netloc = urlparse(s).netloc
        return netloc[4:] if netloc.startswith("www.") else netloc or None
    return s[4:] if s.startswith("www.") else s


def _name_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _load_job_snapshot(crunchbase_id: Optional[str], company_name: str) -> Optional[Dict[str, Any]]:
    base = resolve_repo_path(settings.JOB_POSTS_SNAPSHOT_DIR)
    if not base.is_dir():
        return None
    keys: List[str] = []
    if crunchbase_id:
        keys.extend([crunchbase_id, crunchbase_id.lower()])
    keys.append(_name_slug(company_name))
    tried: Set[str] = set()
    for key in keys:
        if not key or key in tried:
            continue
        tried.add(key)
        for fp in (base / f"{key}.json", base / f"{key.replace(' ', '-')}.json"):
            if fp.is_file():
                try:
                    return json.loads(fp.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning("Snapshot read failed %s: %s", fp, e)
    return None


async def _extract_job_like_texts(page) -> List[str]:
    """Broad selectors for public career / job listing pages (Playwright)."""
    texts: List[str] = []
    selectors = [
        "[data-testid*='job' i]",
        "[class*='job' i][class*='title' i]",
        "a[href*='job' i]",
        "a[href*='career' i]",
        "a[href*='position' i]",
        "li a",
        "article h2",
        "article h3",
        "h2",
        "h3",
        ".job-title",
    ]
    for sel in selectors:
        try:
            els = await page.query_selector_all(sel)
            for el in els[:80]:
                try:
                    t = (await el.inner_text()).strip()
                    if 8 < len(t) < 200 and not t.lower().startswith("http"):
                        texts.append(t)
                except Exception:
                    continue
        except Exception:
            continue
    # de-dupe preserving order
    out, seen = [], set()
    for t in texts:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:120]


async def _scrape_url(context, url: str, company_name: str, host: Optional[str]) -> Tuple[List[Dict[str, str]], int]:
    """Returns (job rows, count of long headings rejected as non-job noise)."""
    page = await context.new_page()
    jobs: List[Dict[str, str]] = []
    noise = 0
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT_MS)
        try:
            await page.wait_for_timeout(_POST_LOAD_MS)
        except Exception:
            pass
        titles = await _extract_job_like_texts(page)
        for title in titles:
            t = title.strip()
            if is_plausible_public_job_title(t):
                jobs.append({"title": t, "source_url": url})
            elif _looks_jobish_but_ambiguous(t):
                noise += 1
    except Exception as e:
        logger.debug("Playwright page skip %s: %s", url, e)
    finally:
        await page.close()
    return jobs, noise


def _third_party_search_urls(company_name: str) -> Dict[str, str]:
    """
    Public job discovery by company *name* only.
    Crunchbase ODM `id` is not a stable slug on BuiltIn/Wellfound/LinkedIn — do not use it in paths.
    """
    q = quote(company_name.strip())
    return {
        "builtin_jobs_search": f"https://builtin.com/jobs?search={q}",
        "wellfound_jobs_search": f"https://wellfound.com/jobs?query={q}",
        "linkedin_jobs_kw": f"https://www.linkedin.com/jobs/search?keywords={q}",
    }


def _careers_urls(host: Optional[str]) -> List[str]:
    if not host:
        return []
    h = host if host.startswith("http") else f"https://{host}"
    base = h.rstrip("/")
    paths = (
        "/careers",
        "/jobs",
        "/careers/jobs",
        "/about/careers",
        "/team/careers",
        "/openings",
    )
    return [base + p for p in paths]


async def enrich_from_job_posts(
    company_name: str,
    *,
    crunchbase_id: Optional[str] = None,
    website_url: Optional[str] = None,
) -> EnrichmentSignal:
    """
    Job-post signal via Playwright on public pages:
    1) Company careers URLs from CSV `website` / host
    2) BuiltIn / Wellfound / LinkedIn *search* by legal name (not Crunchbase id)

    Optional JSON snapshot (keyed by ODM id or name slug) supplements thin live runs.
    """
    logger.info("Playwright job enrichment for %s (site=%s)", company_name, website_url)
    host = _host_from_website(website_url)
    snapshot = _load_job_snapshot(crunchbase_id, company_name)

    all_jobs: List[Dict[str, str]] = []
    urls_tried: List[str] = []
    playwright_error: Optional[str] = None
    discarded_headings = 0

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            async def route_block_media(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**/*", route_block_media)

            for u in _careers_urls(host)[:_MAX_CAREER_URLS]:
                urls_tried.append(u)
                batch, nnoise = await _scrape_url(context, u, company_name, host)
                all_jobs.extend(batch)
                discarded_headings += nnoise
                if len(urls_tried) >= _MAX_URLS_TOTAL:
                    break

            for _, u in _third_party_search_urls(company_name).items():
                if len(urls_tried) >= _MAX_URLS_TOTAL:
                    break
                urls_tried.append(u)
                batch, nnoise = await _scrape_url(context, u, company_name, host)
                all_jobs.extend(batch)
                discarded_headings += nnoise

            await browser.close()
    except Exception as e:
        playwright_error = str(e)
        logger.error("Playwright job scrape failed for %s: %s", company_name, e)

    # Merge snapshot if live crawl thin
    snap_roles: List[str] = []
    if snapshot:
        snap_roles = list(snapshot.get("roles") or snapshot.get("titles") or [])

    seen_titles = {j["title"].lower() for j in all_jobs}
    for r in snap_roles:
        if not isinstance(r, str) or not r.strip():
            continue
        rs = r.strip()
        if not is_plausible_public_job_title(rs):
            if _looks_jobish_but_ambiguous(rs):
                discarded_headings += 1
            continue
        rl = rs.lower()
        if rl not in seen_titles:
            seen_titles.add(rl)
            all_jobs.append({"title": rs, "source_url": "snapshot"})

    raw_parse_count = len(all_jobs)
    uniq_titles = {j["title"].strip().lower() for j in all_jobs}
    listing_quality = "high"
    if raw_parse_count > 0 and len(uniq_titles) == 1 and raw_parse_count >= 2:
        listing_quality = "low"
    elif raw_parse_count > 0 and len(uniq_titles) <= 1 and raw_parse_count >= 1:
        listing_quality = "medium"

    current_count = len(all_jobs)

    count_60d_ago = 5
    if snapshot and snapshot.get("count_60d_ago") is not None:
        try:
            count_60d_ago = int(snapshot["count_60d_ago"])
        except (TypeError, ValueError):
            pass

    velocity = (current_count - count_60d_ago) / 60.0
    platforms = list({j.get("source_url", "") for j in all_jobs if j.get("source_url")})
    attribution = urls_tried[0] if urls_tried else (platforms[0] if platforms else "")

    if playwright_error and current_count == 0 and not snapshot:
        return EnrichmentSignal(
            source="job_posts_scraper",
            error=playwright_error,
            metadata=SignalMetadata(attribution_url=attribution or None),
        )

    if current_count == 0:
        note = "No job-like listings parsed from public pages (Playwright)."
        if discarded_headings > 0:
            note = (
                "Found ambiguous career/job-like text but no reliable role titles after filtering. "
                "Treat open-role count as unknown — not zero proof."
            )
        return EnrichmentSignal(
            source="job_posts_scraper",
            confidence=0.45,
            metadata=SignalMetadata(evidence_strength=0.18, attribution_url=attribution or None),
            data={
                "job_count": 0,
                "velocity_60d": 0.0,
                "count_60d_ago": 0,
                "note": note,
                "urls_attempted": urls_tried[:15],
                "playwright_error": playwright_error,
                "discarded_heading_candidates": discarded_headings,
                "listing_quality": "none",
            },
        )

    conf = 0.88 if not playwright_error else 0.72
    ev_strength = 0.85
    if listing_quality == "low":
        conf = min(conf, 0.55)
        ev_strength = 0.34
    elif listing_quality == "medium":
        conf = min(conf, 0.68)
        ev_strength = min(ev_strength, 0.58)

    return EnrichmentSignal(
        source="job_posts_scraper",
        confidence=conf,
        metadata=SignalMetadata(evidence_strength=ev_strength, attribution_url=attribution or None),
        data={
            "job_count": current_count,
            "roles": [j["title"] for j in all_jobs[:25]],
            "velocity_60d": velocity,
            "platforms_scraped": ["playwright_public_pages"],
            "urls_attempted": urls_tried[:20],
            "snapshot_merged": bool(snapshot),
            "playwright_error": playwright_error,
            "listing_quality": listing_quality,
            "unique_title_count": len(uniq_titles),
            "discarded_heading_candidates": discarded_headings,
        },
    )
