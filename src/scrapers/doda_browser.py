"""Doda job board scraper using Playwright (headless browser)."""

import logging
import random
import re
import time
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class DodaBrowserScraper:
    """Scraper for doda.jp using Playwright headless browser."""

    BASE_URL = "https://doda.jp"
    SEARCH_URL = "https://doda.jp/DodaFront/View/JobSearchList.action"

    # Regex to extract job ID from URL
    JOB_ID_PATTERN = re.compile(r"/j_jid__(\d+)/")

    # Regex patterns for salary extraction
    SALARY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)万円")
    ANNUAL_SALARY_PATTERN = re.compile(r"(?:年収|予定年収)[＞>]?(\d{1,3}(?:,\d{3})*|\d+)万円")

    def __init__(self, delay_range: tuple[float, float] = (3.0, 5.0), headless: bool = False):
        """Initialize scraper with delay settings.

        Args:
            delay_range: Tuple of (min_delay, max_delay) seconds between requests.
            headless: Run browser in headless mode (default False - Doda blocks headless).
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
        return "doda"

    def delay(self) -> None:
        """Sleep for a random duration within the delay range."""
        sleep_time = random.uniform(*self.delay_range)
        self.logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)

    def _build_search_url(self, keywords: list[str], location: str = None) -> str:
        """Build the search URL with keywords and location."""
        search_terms = list(keywords)
        if location:
            search_terms.append(location)

        params = {
            "k": " ".join(search_terms),
            "kwc": 1,
            "ss": 1,
            "pic": 1,
            "ds": 0,
            "so": 50,
            "tp": 1,
        }

        return f"{self.SEARCH_URL}?{urlencode(params)}"

    def _extract_job_id(self, url: str) -> str | None:
        """Extract job ID from URL."""
        match = self.JOB_ID_PATTERN.search(url)
        return match.group(1) if match else None

    def _parse_salary(self, salary_text: str | None) -> tuple[int | None, int | None]:
        """Parse salary text and extract annual min/max values in yen."""
        if not salary_text:
            return None, None

        is_monthly = "月給" in salary_text or "月収" in salary_text
        is_annual = "年収" in salary_text or "予定年収" in salary_text

        if is_annual and is_monthly:
            matches = self.ANNUAL_SALARY_PATTERN.findall(salary_text)
        elif is_annual:
            matches = self.ANNUAL_SALARY_PATTERN.findall(salary_text)
            if not matches:
                matches = self.SALARY_PATTERN.findall(salary_text)
        else:
            matches = self.SALARY_PATTERN.findall(salary_text)

        if not matches:
            return None, None

        amounts = []
        for match in matches:
            try:
                value = int(match.replace(",", "")) * 10000
                amounts.append(value)
            except ValueError:
                continue

        if not amounts:
            return None, None

        if is_monthly and not is_annual:
            amounts = [a * 12 if a < 2500000 else a for a in amounts]

        return min(amounts), max(amounts)

    def _extract_dl_value(self, article: BeautifulSoup, label: str) -> str | None:
        """Extract value from a dl element by its label."""
        label_span = article.find("span", string=lambda x: x and label in x)
        if not label_span:
            return None

        parent = label_span.parent
        if parent:
            container = parent.parent
            if container:
                full_text = container.get_text(strip=True)
                value = full_text.replace(label, "").strip()
                return value if value else None

        return None

    def _parse_job(self, article: BeautifulSoup) -> dict | None:
        """Parse a single job article element."""
        try:
            company_elem = article.find("h2")
            company = company_elem.get_text(strip=True) if company_elem else None

            detail_link = article.find("a", href=lambda x: x and "JobSearchDetail" in x)
            if not detail_link:
                return None

            url = detail_link.get("href", "")
            if not url.startswith("http"):
                url = f"{self.BASE_URL}{url}" if url.startswith("/") else f"{self.BASE_URL}/{url}"

            raw_title = detail_link.get_text(strip=True)
            title = raw_title
            if company and raw_title.startswith(company):
                title = raw_title[len(company):].strip()

            job_id = self._extract_job_id(url)
            if not job_id:
                return None

            location = self._extract_dl_value(article, "勤務地")
            salary_text = self._extract_dl_value(article, "給与")
            salary_annual_min, salary_annual_max = self._parse_salary(salary_text)

            body = article.find("div", class_="jobCard-body")
            description = body.get_text(separator=" ", strip=True) if body else ""

            return {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": location,
                "salary_text": salary_text,
                "salary_annual_min": salary_annual_min,
                "salary_annual_max": salary_annual_max,
                "url": url,
                "job_board": self.job_board_name,
                "description": description,
            }

        except Exception as e:
            self.logger.warning(f"Failed to parse job article: {e}")
            return None

    def _parse_page(self, html: str) -> tuple[list[dict], str | None]:
        """Parse a search results page."""
        soup = BeautifulSoup(html, "lxml")
        jobs = []

        articles = soup.find_all("article")
        self.logger.info(f"Found {len(articles)} job articles on page")

        for article in articles:
            job = self._parse_job(article)
            if job:
                jobs.append(job)

        # Get next page URL
        next_link = soup.find("a", string=lambda x: x and "次" in x)
        next_url = None
        if next_link:
            href = next_link.get("href", "")
            if href:
                next_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

        return jobs, next_url

    def search(
        self, keywords: list[str], location: str = None, max_pages: int = 3
    ) -> list[dict]:
        """Search for jobs using Playwright headless browser.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter.
            max_pages: Maximum number of pages to scrape.

        Returns:
            List of job dictionaries.
        """
        all_jobs = []
        url = self._build_search_url(keywords, location)

        self.logger.info(f"Starting browser search: keywords={keywords}, location={location}")
        self.logger.info(f"Search URL: {url}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="ja-JP",
            )
            page = context.new_page()

            try:
                # First visit homepage and use search form
                self.logger.info("Visiting homepage first to establish session...")
                page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)  # Let page settle

                # Build search query
                search_terms = list(keywords)
                if location:
                    search_terms.append(location)
                search_query = " ".join(search_terms)

                # Try to find and use the search form
                self.logger.info(f"Searching for: {search_query}")
                try:
                    # Look for search input field (Doda uses placeholder "スキルや条件など")
                    search_input = page.locator('input[placeholder*="スキル"], input[placeholder*="条件"]').first
                    search_input.click()
                    time.sleep(0.5)
                    search_input.fill(search_query)
                    time.sleep(0.5)
                    search_input.press("Enter")
                    time.sleep(5)  # Wait for results to load
                    page.wait_for_selector("article", timeout=30000)
                except Exception as e:
                    self.logger.error(f"Could not use search form: {e}")
                    raise

                for page_num in range(1, max_pages + 1):
                    self.logger.info(f"Scraping page {page_num}/{max_pages}")

                    try:
                        # Wait for job cards to load
                        page.wait_for_selector("article", timeout=30000)
                    except PlaywrightTimeout:
                        self.logger.error(f"Timeout waiting for jobs on page {page_num}")
                        break

                    html = page.content()
                    jobs, _ = self._parse_page(html)
                    all_jobs.extend(jobs)

                    self.logger.info(f"Extracted {len(jobs)} jobs from page {page_num}")

                    if page_num < max_pages:
                        # Try to click next page link instead of direct navigation
                        try:
                            next_link = page.locator('a:has-text("次")').first
                            if next_link.is_visible():
                                self.delay()
                                next_link.click()
                                time.sleep(2)  # Wait for page to load
                            else:
                                self.logger.info("No more pages available")
                                break
                        except Exception as e:
                            self.logger.info(f"No more pages: {e}")
                            break

            finally:
                browser.close()

        self.logger.info(f"Browser search complete. Total jobs found: {len(all_jobs)}")
        return all_jobs
