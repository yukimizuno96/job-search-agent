#!/usr/bin/env python3
"""Scrape jobs from job boards and store in database.

Usage:
    python scripts/scrape_and_store.py --source doda
    python scripts/scrape_and_store.py --source all
    python scripts/scrape_and_store.py --source doda --local path/to/file.html
"""

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Type

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timezone

from src.models.database import Job, get_engine, get_session
from src.models.job_utils import find_duplicate_job, generate_fingerprint
from src.scrapers.base import BaseScraper
from src.scrapers.doda import DodaScraper
from src.scrapers.green import GreenScraper
from src.scrapers.indeed import IndeedScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# Scraper Registry - Add new scrapers here
# =============================================================================
SCRAPERS: dict[str, Type[BaseScraper]] = {
    "doda": DodaScraper,
    "green": GreenScraper,
    "indeed": IndeedScraper,
}


@dataclass
class ScrapeStats:
    """Statistics from a scrape run."""
    source: str = ""
    total_scraped: int = 0
    new_jobs: int = 0
    duplicates: int = 0
    errors: int = 0


@dataclass
class AggregateStats:
    """Aggregate statistics across multiple sources."""
    sources: list[ScrapeStats] = field(default_factory=list)

    @property
    def total_scraped(self) -> int:
        return sum(s.total_scraped for s in self.sources)

    @property
    def new_jobs(self) -> int:
        return sum(s.new_jobs for s in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(s.duplicates for s in self.sources)

    @property
    def errors(self) -> int:
        return sum(s.errors for s in self.sources)

    def add(self, stats: ScrapeStats):
        self.sources.append(stats)


def store_jobs(jobs: list[dict], session, source: str) -> ScrapeStats:
    """Store scraped jobs in the database.

    Uses fingerprint-based deduplication and updates last_seen_at for existing jobs.

    Args:
        jobs: List of job dictionaries from scraper.
        session: Database session.
        source: Name of the job board source.

    Returns:
        ScrapeStats with counts.
    """
    stats = ScrapeStats(source=source, total_scraped=len(jobs))
    now = datetime.now(timezone.utc)

    for job_data in jobs:
        try:
            # Generate fingerprint for deduplication
            fingerprint = generate_fingerprint(
                job_data["title"],
                job_data["company"],
                job_data["job_board"],
            )

            # Check if job already exists (by URL or fingerprint)
            existing = find_duplicate_job(session, job_data["url"], fingerprint)

            if existing:
                # Update last_seen_at to track job is still active
                existing.last_seen_at = now
                existing.is_active = True
                stats.duplicates += 1
                logger.debug(f"Duplicate (updated last_seen): {job_data['title'][:50]}")
                continue

            # Create new job record
            job = Job(
                title=job_data["title"],
                company=job_data["company"],
                description=job_data.get("description"),
                salary_text=job_data.get("salary_text"),
                salary_annual_min=job_data.get("salary_annual_min"),
                salary_annual_max=job_data.get("salary_annual_max"),
                location=job_data.get("location"),
                url=job_data["url"],
                job_board=job_data["job_board"],
                fingerprint=fingerprint,
                last_seen_at=now,
            )
            session.add(job)
            stats.new_jobs += 1
            logger.debug(f"Added: {job_data['title'][:50]}")

        except Exception as e:
            stats.errors += 1
            logger.error(f"Error storing job: {e}")

    # Commit all new jobs
    try:
        session.commit()
        logger.info(f"Committed {stats.new_jobs} new jobs from {source}")
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to commit: {e}")
        stats.errors += stats.new_jobs
        stats.new_jobs = 0

    return stats


def scrape_source(
    source: str,
    scraper_class: Type[BaseScraper],
    keywords: list[str],
    location: str = None,
    max_pages: int = 3,
    local_html: str = None,
    session=None,
) -> ScrapeStats:
    """Scrape a single source and store jobs.

    Args:
        source: Name of the source (e.g., "doda").
        scraper_class: The scraper class to use.
        keywords: Search keywords.
        location: Optional location filter.
        max_pages: Maximum pages to scrape.
        local_html: Optional path to local HTML file for testing.
        session: Database session.

    Returns:
        ScrapeStats for this source.
    """
    logger.info(f"{'='*50}")
    logger.info(f"Scraping: {source.upper()}")
    logger.info(f"{'='*50}")

    scraper = scraper_class()

    try:
        # Scrape jobs
        if local_html:
            logger.info(f"Loading from local file: {local_html}")
            html = Path(local_html).read_text(encoding="utf-8")
            jobs = scraper.search_from_html(html)
        else:
            logger.info(f"Searching: keywords={keywords}, location={location}")
            jobs = scraper.search(keywords, location, max_pages)

        logger.info(f"Scraped {len(jobs)} jobs from {source}")

        # Store jobs
        stats = store_jobs(jobs, session, source)
        return stats

    except Exception as e:
        logger.error(f"Failed to scrape {source}: {e}")
        return ScrapeStats(source=source, errors=1)


def scrape_and_store(
    sources: list[str],
    keywords: list[str],
    location: str = None,
    max_pages: int = 3,
    local_html: str = None,
) -> AggregateStats:
    """Scrape from multiple sources and store in database.

    Args:
        sources: List of source names to scrape (or ["all"]).
        keywords: Search keywords.
        location: Optional location filter.
        max_pages: Maximum pages to scrape per source.
        local_html: Optional path to local HTML file (only for single source).

    Returns:
        AggregateStats with counts from all sources.
    """
    # Resolve "all" to list of all available scrapers
    if "all" in sources:
        sources = list(SCRAPERS.keys())

    # Validate sources
    for source in sources:
        if source not in SCRAPERS:
            logger.error(f"Unknown source: {source}")
            logger.info(f"Available sources: {', '.join(SCRAPERS.keys())}")
            return AggregateStats()

    # Local HTML only works with single source
    if local_html and len(sources) > 1:
        logger.error("--local can only be used with a single source")
        return AggregateStats()

    engine = get_engine()
    session = get_session(engine)
    aggregate = AggregateStats()

    try:
        for source in sources:
            scraper_class = SCRAPERS[source]
            stats = scrape_source(
                source=source,
                scraper_class=scraper_class,
                keywords=keywords,
                location=location,
                max_pages=max_pages,
                local_html=local_html,
                session=session,
            )
            aggregate.add(stats)

        # Log summary
        logger.info("")
        logger.info("=" * 50)
        logger.info("SCRAPE SUMMARY")
        logger.info("=" * 50)

        if len(aggregate.sources) > 1:
            for stats in aggregate.sources:
                logger.info(f"{stats.source}: {stats.new_jobs} new, {stats.duplicates} dups")
            logger.info("-" * 30)

        logger.info(f"Total scraped:  {aggregate.total_scraped}")
        logger.info(f"New jobs added: {aggregate.new_jobs}")
        logger.info(f"Duplicates:     {aggregate.duplicates}")
        logger.info(f"Errors:         {aggregate.errors}")

        return aggregate

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape jobs from job boards and store in database"
    )
    parser.add_argument(
        "--source",
        nargs="+",
        default=["doda"],
        help=f"Source(s) to scrape: {', '.join(SCRAPERS.keys())}, or 'all' (default: doda)"
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=["デザイナー"],
        help="Search keywords (default: デザイナー)"
    )
    parser.add_argument(
        "--location",
        type=str,
        default="東京",
        help="Location filter (default: 東京)"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Maximum pages to scrape per source (default: 2)"
    )
    parser.add_argument(
        "--local",
        type=str,
        help="Path to local HTML file for testing (single source only)"
    )

    args = parser.parse_args()

    stats = scrape_and_store(
        sources=args.source,
        keywords=args.keywords,
        location=args.location,
        max_pages=args.max_pages,
        local_html=args.local,
    )

    # Exit with error code if there were errors
    sys.exit(1 if stats.errors > 0 else 0)


if __name__ == "__main__":
    main()
