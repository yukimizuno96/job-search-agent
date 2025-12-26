#!/usr/bin/env python3
"""Orchestrate scraping from all job boards with parallel execution.

Features:
- Parallel execution of scrapers
- Per-scraper configuration
- Error isolation (one failure doesn't stop others)
- Aggregate reporting

Usage:
    python scripts/scrape_all_boards.py
    python scripts/scrape_all_boards.py --config config.json
    python scripts/scrape_all_boards.py --keywords "エンジニア" --location "大阪"
"""

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.database import Job, get_engine, get_session
from src.models.job_utils import find_duplicate_job, generate_fingerprint
from src.scrapers.base import BaseScraper
from src.scrapers.doda_browser import DodaBrowserScraper
from src.scrapers.green import GreenScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.wantedly_browser import WantedlyBrowserScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s"
)
logger = logging.getLogger("orchestrator")


# =============================================================================
# Scraper Registry
# =============================================================================
SCRAPERS = {
    "doda": DodaBrowserScraper,  # Uses Playwright for browser-based scraping
    "green": GreenScraper,
    "indeed": IndeedScraper,
    "wantedly": WantedlyBrowserScraper,  # Uses Playwright for infinite scroll
}


# =============================================================================
# Default Configuration
# =============================================================================
DEFAULT_CONFIG = {
    "global": {
        "keywords": ["デザイナー"],
        "location": "東京",
        "max_pages": 2,
        "parallel": True,
        "max_workers": 3,
    },
    "scrapers": {
        "doda": {
            "enabled": True,
            # Override global settings per-scraper:
            # "keywords": ["UXデザイナー"],
            # "max_pages": 3,
        },
        "green": {
            "enabled": True,
        },
        "indeed": {
            "enabled": True,
        },
    },
}


@dataclass
class ScraperResult:
    """Result from a single scraper run."""
    name: str
    success: bool
    jobs_scraped: int = 0
    jobs_added: int = 0
    duplicates: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    error_message: str = None


@dataclass
class OrchestratorResult:
    """Aggregate result from all scrapers."""
    results: list[ScraperResult] = field(default_factory=list)
    total_duration_seconds: float = 0.0

    @property
    def total_scraped(self) -> int:
        return sum(r.jobs_scraped for r in self.results)

    @property
    def total_added(self) -> int:
        return sum(r.jobs_added for r in self.results)

    @property
    def total_duplicates(self) -> int:
        return sum(r.duplicates for r in self.results)

    @property
    def total_errors(self) -> int:
        return sum(r.errors for r in self.results)

    @property
    def successful_scrapers(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed_scrapers(self) -> int:
        return sum(1 for r in self.results if not r.success)


def get_scraper_config(config: dict, scraper_name: str) -> dict:
    """Get merged configuration for a specific scraper.

    Scraper-specific settings override global settings.
    """
    global_config = config.get("global", {})
    scraper_config = config.get("scrapers", {}).get(scraper_name, {})

    # Start with global settings
    merged = {
        "keywords": global_config.get("keywords", ["デザイナー"]),
        "location": global_config.get("location", "東京"),
        "max_pages": global_config.get("max_pages", 2),
        "delay_range": global_config.get("delay_range", [2.0, 3.0]),
    }

    # Override with scraper-specific settings
    if "keywords" in scraper_config:
        merged["keywords"] = scraper_config["keywords"]
    if "location" in scraper_config:
        merged["location"] = scraper_config["location"]
    if "max_pages" in scraper_config:
        merged["max_pages"] = scraper_config["max_pages"]
    if "delay_range" in scraper_config:
        merged["delay_range"] = scraper_config["delay_range"]

    return merged


def run_scraper(
    name: str,
    scraper_class: type[BaseScraper],
    config: dict,
    engine,
) -> ScraperResult:
    """Run a single scraper with error isolation.

    Each scraper gets its own database session for thread safety.
    """
    start_time = time.time()
    scraper_config = get_scraper_config(config, name)

    scraper_logger = logging.getLogger(f"scraper.{name}")
    scraper_logger.info(f"Starting {name} scraper")
    scraper_logger.info(f"Config: {scraper_config}")

    try:
        # Create scraper and run search
        delay_range = tuple(scraper_config.get("delay_range", (2.0, 3.0)))
        scraper = scraper_class(delay_range=delay_range)
        jobs = scraper.search(
            keywords=scraper_config["keywords"],
            location=scraper_config["location"],
            max_pages=scraper_config["max_pages"],
        )

        scraper_logger.info(f"Scraped {len(jobs)} jobs from {name}")

        # Store jobs with isolated session
        session = get_session(engine)
        jobs_added = 0
        duplicates = 0
        errors = 0
        now = datetime.now()

        try:
            for job_data in jobs:
                try:
                    # Generate fingerprint for deduplication
                    fingerprint = generate_fingerprint(
                        job_data["title"],
                        job_data["company"],
                        job_data["job_board"],
                    )

                    # Check for duplicate by URL or fingerprint
                    existing = find_duplicate_job(session, job_data["url"], fingerprint)

                    if existing:
                        # Update last_seen_at to track job is still active
                        existing.last_seen_at = now
                        existing.is_active = True
                        duplicates += 1
                        continue

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
                    jobs_added += 1

                except Exception as e:
                    errors += 1
                    scraper_logger.error(f"Error storing job: {e}")

            session.commit()
            scraper_logger.info(f"Committed {jobs_added} new jobs from {name}")

        finally:
            session.close()

        duration = time.time() - start_time
        return ScraperResult(
            name=name,
            success=True,
            jobs_scraped=len(jobs),
            jobs_added=jobs_added,
            duplicates=duplicates,
            errors=errors,
            duration_seconds=duration,
        )

    except Exception as e:
        duration = time.time() - start_time
        scraper_logger.error(f"Scraper {name} failed: {e}")
        return ScraperResult(
            name=name,
            success=False,
            duration_seconds=duration,
            error_message=str(e),
        )


def run_all_scrapers(config: dict) -> OrchestratorResult:
    """Run all enabled scrapers with optional parallelization."""
    start_time = time.time()
    result = OrchestratorResult()

    # Get enabled scrapers
    enabled_scrapers = []
    for name, scraper_class in SCRAPERS.items():
        scraper_config = config.get("scrapers", {}).get(name, {})
        if scraper_config.get("enabled", True):
            enabled_scrapers.append((name, scraper_class))

    if not enabled_scrapers:
        logger.warning("No scrapers enabled")
        return result

    logger.info(f"Running {len(enabled_scrapers)} scrapers: {[s[0] for s in enabled_scrapers]}")

    # Get shared engine (sessions created per-thread)
    engine = get_engine()

    global_config = config.get("global", {})
    use_parallel = global_config.get("parallel", True)
    max_workers = global_config.get("max_workers", 3)

    if use_parallel and len(enabled_scrapers) > 1:
        logger.info(f"Running in parallel with {max_workers} workers")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_scraper, name, scraper_class, config, engine): name
                for name, scraper_class in enabled_scrapers
            }

            for future in as_completed(futures):
                scraper_name = futures[future]
                try:
                    scraper_result = future.result()
                    result.results.append(scraper_result)
                except Exception as e:
                    logger.error(f"Unexpected error from {scraper_name}: {e}")
                    result.results.append(ScraperResult(
                        name=scraper_name,
                        success=False,
                        error_message=str(e),
                    ))
    else:
        logger.info("Running sequentially")
        for name, scraper_class in enabled_scrapers:
            scraper_result = run_scraper(name, scraper_class, config, engine)
            result.results.append(scraper_result)

    result.total_duration_seconds = time.time() - start_time
    return result


def print_report(result: OrchestratorResult):
    """Print a formatted report of the orchestration results."""
    print("\n" + "=" * 60)
    print("SCRAPE ORCHESTRATION REPORT")
    print("=" * 60)

    # Per-scraper results
    print("\nPer-Scraper Results:")
    print("-" * 60)
    print(f"{'Scraper':<10} {'Status':<8} {'Scraped':<8} {'Added':<8} {'Dups':<6} {'Time':<8}")
    print("-" * 60)

    for r in sorted(result.results, key=lambda x: x.name):
        status = "✓" if r.success else "✗"
        time_str = f"{r.duration_seconds:.1f}s"
        print(f"{r.name:<10} {status:<8} {r.jobs_scraped:<8} {r.jobs_added:<8} {r.duplicates:<6} {time_str:<8}")
        if r.error_message:
            print(f"           Error: {r.error_message[:45]}...")

    # Summary
    print("\n" + "-" * 60)
    print("Summary:")
    print(f"  Scrapers: {result.successful_scrapers} succeeded, {result.failed_scrapers} failed")
    print(f"  Jobs scraped:  {result.total_scraped}")
    print(f"  Jobs added:    {result.total_added}")
    print(f"  Duplicates:    {result.total_duplicates}")
    print(f"  Errors:        {result.total_errors}")
    print(f"  Total time:    {result.total_duration_seconds:.1f}s")
    print("=" * 60)


def load_config(config_path: str = None) -> dict:
    """Load configuration from file or return defaults."""
    if config_path:
        path = Path(config_path)
        if path.exists():
            logger.info(f"Loading config from {config_path}")
            with open(path) as f:
                return json.load(f)
        else:
            logger.warning(f"Config file not found: {config_path}, using defaults")

    return DEFAULT_CONFIG.copy()


def main():
    parser = argparse.ArgumentParser(
        description="Orchestrate scraping from all job boards"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to JSON config file"
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Override global keywords"
    )
    parser.add_argument(
        "--location",
        type=str,
        help="Override global location"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Override global max pages"
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run scrapers sequentially instead of in parallel"
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=list(SCRAPERS.keys()),
        help="Only run specific scrapers"
    )

    args = parser.parse_args()

    # Load and merge config
    config = load_config(args.config)

    # Apply CLI overrides
    if args.keywords:
        config["global"]["keywords"] = args.keywords
    if args.location:
        config["global"]["location"] = args.location
    if args.max_pages:
        config["global"]["max_pages"] = args.max_pages
    if args.sequential:
        config["global"]["parallel"] = False

    # Handle --only flag
    if args.only:
        for name in SCRAPERS.keys():
            if name not in args.only:
                config.setdefault("scrapers", {}).setdefault(name, {})["enabled"] = False

    logger.info("Starting job board orchestrator")
    logger.info(f"Global config: {config['global']}")

    # Run all scrapers
    result = run_all_scrapers(config)

    # Print report
    print_report(result)

    # Exit with error if any scraper failed
    sys.exit(1 if result.failed_scrapers > 0 else 0)


if __name__ == "__main__":
    main()
