"""Wantedly job board scraper using Playwright (headless browser)."""

import logging
import random
import re
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class WantedlyBrowserScraper:
    """Scraper for wantedly.com using Playwright headless browser."""

    BASE_URL = "https://www.wantedly.com"
    SEARCH_URL = "https://www.wantedly.com/projects"

    # Occupation type mappings
    OCCUPATION_MAP = {
        "デザイナー": "designer",
        "エンジニア": "engineer",
        "マーケター": "marketer",
        "セールス": "sales",
        "PM": "pm_director",
        "プロダクトマネージャー": "pm_director",
        "ディレクター": "pm_director",
        "人事": "hr",
        "バックオフィス": "corporate",
    }

    def __init__(self, delay_range: tuple[float, float] = (2.0, 4.0), headless: bool = True):
        """Initialize scraper with delay settings.

        Args:
            delay_range: Tuple of (min_delay, max_delay) seconds between actions.
            headless: Run browser in headless mode.
        """
        self.delay_range = delay_range
        self.headless = headless
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Set up logger for this scraper."""
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)
        return logger

    @property
    def job_board_name(self) -> str:
        return "wantedly"

    def delay(self) -> None:
        """Sleep for a random duration within the delay range."""
        sleep_time = random.uniform(*self.delay_range)
        time.sleep(sleep_time)

    def _build_search_url(self, keywords: list[str], page: int = 1) -> str:
        """Build the search URL based on keywords.

        Args:
            keywords: List of keywords to search for.
            page: Page number for pagination.

        Returns:
            Search URL string.
        """
        from urllib.parse import quote

        # Use keyword search with pagination
        keyword_str = " ".join(keywords)
        return f"{self.SEARCH_URL}?page={page}&keywords={quote(keyword_str)}"

    def _parse_job_cards(self, page) -> list[dict]:
        """Parse job cards from the current page.

        Args:
            page: Playwright page object.

        Returns:
            List of job dictionaries.
        """
        jobs = []
        seen_ids = set()

        # Get all project links
        links = page.locator('a[href*="/projects/"]').all()
        self.logger.info(f"Found {len(links)} project links")

        for link in links:
            try:
                href = link.get_attribute("href") or ""
                match = re.search(r'/projects/(\d+)', href)
                if not match:
                    continue

                project_id = match.group(1)
                if project_id in seen_ids:
                    continue
                seen_ids.add(project_id)

                # Get title from link text
                title = link.inner_text().strip()
                if not title or len(title) < 5:
                    continue

                # Clean up title (remove entry count etc)
                title = re.sub(r'\d+\s*エントリー', '', title).strip()
                title = title[:200]  # Truncate

                # Try to get company name from nearby elements
                company = ""
                try:
                    # Navigate up to find company info
                    parent = link.locator("xpath=ancestor::div[contains(@class, 'project') or contains(@class, 'card')]").first
                    if parent.count() > 0:
                        company_elem = parent.locator('[class*="company"], [class*="Company"]').first
                        if company_elem.count() > 0:
                            company = company_elem.inner_text().strip()
                except:
                    pass

                url = f"{self.BASE_URL}/projects/{project_id}"

                jobs.append({
                    "job_id": project_id,
                    "title": title,
                    "company": company,
                    "location": "",
                    "description": "",
                    "salary_text": None,
                    "salary_annual_min": None,
                    "salary_annual_max": None,
                    "url": url,
                    "job_board": self.job_board_name,
                })

            except Exception as e:
                self.logger.debug(f"Failed to parse link: {e}")
                continue

        return jobs

    def _scroll_to_load_more(self, page, max_scrolls: int = 10) -> int:
        """Scroll down to load more jobs (infinite scroll).

        Args:
            page: Playwright page object.
            max_scrolls: Maximum number of scroll attempts.

        Returns:
            Number of jobs found after scrolling.
        """
        last_count = 0

        for i in range(max_scrolls):
            # Count current jobs
            current_count = page.locator('a[href*="/projects/"]').count()

            if current_count == last_count and i > 0:
                # No new jobs loaded
                self.logger.info(f"No more jobs after {i} scrolls")
                break

            last_count = current_count
            self.logger.debug(f"Scroll {i+1}: {current_count} jobs found")

            # Scroll to bottom
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)  # Wait for content to load

        return last_count

    def search(
        self, keywords: list[str], location: str = None, max_pages: int = 3
    ) -> list[dict]:
        """Search for jobs using Playwright headless browser with pagination.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter (added to keywords if provided).
            max_pages: Number of pages to scrape.

        Returns:
            List of job dictionaries.
        """
        # Add location to keywords if provided
        search_keywords = list(keywords)
        if location:
            search_keywords.append(location)

        self.logger.info(f"Starting Wantedly browser search: keywords={search_keywords}")

        all_jobs = []
        seen_ids = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ja-JP",
            )
            page = context.new_page()

            try:
                for page_num in range(1, max_pages + 1):
                    url = self._build_search_url(search_keywords, page_num)
                    self.logger.info(f"Scraping page {page_num}/{max_pages}: {url}")

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)  # Wait for JS to render

                        # Parse jobs from this page
                        jobs = self._parse_job_cards(page)

                        # Deduplicate
                        new_jobs = []
                        for job in jobs:
                            if job["job_id"] not in seen_ids:
                                seen_ids.add(job["job_id"])
                                new_jobs.append(job)

                        all_jobs.extend(new_jobs)
                        self.logger.info(f"Page {page_num}: {len(jobs)} jobs, {len(new_jobs)} new")

                        # Stop if no new jobs found
                        if len(new_jobs) == 0:
                            self.logger.info("No new jobs found, stopping pagination")
                            break

                        # Delay between pages
                        if page_num < max_pages:
                            self.delay()

                    except PlaywrightTimeout:
                        self.logger.warning(f"Timeout on page {page_num}, continuing...")
                        continue

            except Exception as e:
                self.logger.error(f"Error: {e}")
            finally:
                browser.close()

        self.logger.info(f"Wantedly browser search complete. Total jobs: {len(all_jobs)}")
        return all_jobs
