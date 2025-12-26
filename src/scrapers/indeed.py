"""Indeed Japan job board scraper."""

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper


class IndeedScraper(BaseScraper):
    """Scraper for jp.indeed.com job board."""

    BASE_URL = "https://jp.indeed.com"
    SEARCH_URL = "https://jp.indeed.com/jobs"

    # Regex patterns for salary extraction
    # Matches: "月給 30万円", "年収 500万円", "380,000円"
    SALARY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)万?円")

    @property
    def job_board_name(self) -> str:
        return "indeed"

    def _build_search_url(self, keywords: list[str], location: str = None) -> str:
        """Build the search URL with keywords and location.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter.

        Returns:
            Search URL string.
        """
        params = {
            "q": " ".join(keywords),
        }
        if location:
            params["l"] = location

        return f"{self.SEARCH_URL}?{urlencode(params)}"

    def _parse_salary(self, salary_text: str | None) -> tuple[int | None, int | None]:
        """Parse salary text and extract annual min/max values in yen.

        Args:
            salary_text: Raw salary text (e.g., "月給 30万円 ~ 43万円").

        Returns:
            Tuple of (annual_min, annual_max) in yen.
        """
        if not salary_text:
            return None, None

        # Find all amounts
        matches = self.SALARY_PATTERN.findall(salary_text)
        if not matches:
            return None, None

        amounts = []
        for match in matches:
            try:
                # Remove commas
                value = int(match.replace(",", ""))
                # If value is small (< 1000), it's in 万円 units
                if value < 1000:
                    value = value * 10000  # Convert 万円 to yen
                # Otherwise it's already in yen (e.g., 380,000円)
                amounts.append(value)
            except ValueError:
                continue

        if not amounts:
            return None, None

        # Determine if monthly or annual
        is_monthly = "月給" in salary_text or "月収" in salary_text
        is_annual = "年収" in salary_text or "年俸" in salary_text

        # Convert monthly to annual
        if is_monthly and not is_annual:
            # Only convert amounts that look monthly (< 2.5M yen)
            amounts = [a * 12 if a < 2500000 else a for a in amounts]

        return min(amounts), max(amounts)

    def _extract_salary_text(self, job: BeautifulSoup) -> str | None:
        """Extract salary text from a job card.

        Args:
            job: BeautifulSoup element for the job card.

        Returns:
            Salary text or None.
        """
        # Look for divs containing salary text
        for div in job.find_all("div"):
            text = div.get_text(strip=True)
            # Check if this looks like a salary (starts with 月給/年収 or contains 万円)
            if len(text) < 100:
                if text.startswith("月給") or text.startswith("年収") or text.startswith("年俸"):
                    return text
                if re.match(r"^[\d,]+万?円", text):
                    return text
        return None

    def _parse_job(self, job: BeautifulSoup) -> dict | None:
        """Parse a single job card element.

        Args:
            job: BeautifulSoup element for the job card.

        Returns:
            Job dictionary, or None if parsing failed.
        """
        try:
            # Extract title link (contains title, job ID, and URL)
            title_link = job.select_one("a.jcs-JobTitle")
            if not title_link:
                return None

            title = title_link.get_text(strip=True)
            job_id = title_link.get("data-jk")
            url = title_link.get("href", "")

            if not job_id:
                return None

            # Make URL absolute
            if url and not url.startswith("http"):
                url = urljoin(self.BASE_URL, url)

            # Extract company name
            company_elem = job.select_one("[data-testid='company-name']")
            company = company_elem.get_text(strip=True) if company_elem else None

            # Extract location
            location_elem = job.select_one("[data-testid='text-location']")
            location = location_elem.get_text(strip=True) if location_elem else None

            # Extract salary
            salary_text = self._extract_salary_text(job)
            salary_annual_min, salary_annual_max = self._parse_salary(salary_text)

            # Extract job snippet/description
            snippet_elem = job.select_one("div.job-snippet")
            if not snippet_elem:
                # Try finding any descriptive text
                snippet_elem = job.select_one("table.jobCardShelfContainer")
            description = snippet_elem.get_text(separator=" ", strip=True) if snippet_elem else ""

            # If no snippet, use the full job card text as description
            if not description:
                description = job.get_text(separator=" ", strip=True)

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
            self.logger.warning(f"Failed to parse job card: {e}")
            return None

    def _get_next_page_url(self, soup: BeautifulSoup) -> str | None:
        """Find the next page URL from pagination.

        Args:
            soup: BeautifulSoup object of the current page.

        Returns:
            Next page URL, or None if no next page.
        """
        # Look for next page button
        next_link = soup.select_one("a[data-testid='pagination-page-next']")
        if next_link:
            href = next_link.get("href", "")
            if href:
                return urljoin(self.BASE_URL, href) if not href.startswith("http") else href

        # Fallback: look for link with aria-label containing "次"
        nav = soup.select_one("nav[aria-label='pagination']")
        if nav:
            for link in nav.find_all("a"):
                aria_label = link.get("aria-label", "")
                if "次" in aria_label:
                    href = link.get("href", "")
                    if href:
                        return urljoin(self.BASE_URL, href) if not href.startswith("http") else href

        return None

    def _parse_page(self, html: str) -> tuple[list[dict], str | None]:
        """Parse a search results page.

        Args:
            html: HTML content of the page.

        Returns:
            Tuple of (list of jobs, next page URL or None).
        """
        soup = BeautifulSoup(html, "lxml")
        jobs = []

        # Find all job cards
        job_cards = soup.select("div.job_seen_beacon")
        self.logger.info(f"Found {len(job_cards)} job cards on page")

        for job_card in job_cards:
            job = self._parse_job(job_card)
            if job:
                jobs.append(job)

        # Get next page URL
        next_url = self._get_next_page_url(soup)

        return jobs, next_url

    def search(
        self, keywords: list[str], location: str = None, max_pages: int = 3
    ) -> list[dict]:
        """Search for jobs matching the given criteria.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter.
            max_pages: Maximum number of pages to scrape.

        Returns:
            List of job dictionaries.
        """
        all_jobs = []
        url = self._build_search_url(keywords, location)

        self.logger.info(f"Starting Indeed search: keywords={keywords}, location={location}")
        self.logger.info(f"Search URL: {url}")

        for page_num in range(1, max_pages + 1):
            self.logger.info(f"Scraping page {page_num}/{max_pages}")

            html = self.fetch(url)
            if not html:
                self.logger.error(f"Failed to fetch page {page_num}")
                break

            jobs, next_url = self._parse_page(html)
            all_jobs.extend(jobs)

            self.logger.info(f"Extracted {len(jobs)} jobs from page {page_num}")

            if not next_url:
                self.logger.info("No more pages available")
                break

            if page_num < max_pages:
                url = next_url
                self.delay()

        self.logger.info(f"Indeed search complete. Total jobs found: {len(all_jobs)}")
        return all_jobs

    def search_from_html(self, html: str) -> list[dict]:
        """Parse jobs from HTML string (for testing with local files).

        Args:
            html: HTML content to parse.

        Returns:
            List of job dictionaries.
        """
        jobs, _ = self._parse_page(html)
        return jobs
