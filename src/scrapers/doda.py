"""Doda job board scraper."""

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper


class DodaScraper(BaseScraper):
    """Scraper for doda.jp job board."""

    BASE_URL = "https://doda.jp"
    SEARCH_URL = "https://doda.jp/DodaFront/View/JobSearchList.action"

    # Regex to extract job ID from URL
    JOB_ID_PATTERN = re.compile(r"/j_jid__(\d+)/")

    # Regex patterns for salary extraction
    # Matches patterns like "年収460万円", "月給25万円", "1,200万円"
    SALARY_PATTERN = re.compile(r"(\d{1,3}(?:,\d{3})*|\d+)万円")
    # Matches annual salary patterns specifically: "年収460万円" or "予定年収＞980万円"
    ANNUAL_SALARY_PATTERN = re.compile(r"(?:年収|予定年収)[＞>]?(\d{1,3}(?:,\d{3})*|\d+)万円")

    @property
    def job_board_name(self) -> str:
        return "doda"

    def _build_search_url(self, keywords: list[str], location: str = None) -> str:
        """Build the search URL with keywords and location.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter (included in keyword search).

        Returns:
            Search URL string.
        """
        # Combine keywords with location for search
        # Doda's 'ar' parameter doesn't work reliably, so include location in keywords
        search_terms = list(keywords)
        if location:
            search_terms.append(location)

        params = {
            "k": " ".join(search_terms),
            "kwc": 1,  # Keyword match setting
            "ss": 1,   # Search setting
            "pic": 1,  # Include pictures
            "ds": 0,   # Display setting
            "so": 50,  # Results per page
            "tp": 1,   # Type/pagination
        }

        return f"{self.SEARCH_URL}?{urlencode(params)}"

    def _extract_job_id(self, url: str) -> str | None:
        """Extract job ID from URL.

        Args:
            url: Job detail URL.

        Returns:
            Job ID string, or None if not found.
        """
        match = self.JOB_ID_PATTERN.search(url)
        return match.group(1) if match else None

    def _parse_salary(self, salary_text: str | None) -> tuple[int | None, int | None]:
        """Parse salary text and extract annual min/max values in yen.

        Handles formats like:
        - 年収460万円～580万円
        - 月給25万円～30万円 (converted to annual)
        - 年収800万円
        - ＜予定年収＞980万円～1,200万円

        Args:
            salary_text: Raw salary text from the job listing.

        Returns:
            Tuple of (annual_min, annual_max) in yen, or (None, None) if parsing fails.
        """
        if not salary_text:
            return None, None

        # Determine if this is monthly or annual
        is_monthly = "月給" in salary_text or "月収" in salary_text
        is_annual = "年収" in salary_text or "予定年収" in salary_text

        # If both annual and monthly are mentioned, extract only annual figures
        if is_annual and is_monthly:
            matches = self.ANNUAL_SALARY_PATTERN.findall(salary_text)
        elif is_annual:
            # Only annual - use the specific pattern for cleaner extraction
            matches = self.ANNUAL_SALARY_PATTERN.findall(salary_text)
            # Fall back to general pattern if specific one doesn't match
            if not matches:
                matches = self.SALARY_PATTERN.findall(salary_text)
        else:
            # Monthly only or unclear - use general pattern
            matches = self.SALARY_PATTERN.findall(salary_text)

        if not matches:
            return None, None

        # Convert matches to integers (remove commas, multiply by 10000 for 万円)
        amounts = []
        for match in matches:
            try:
                value = int(match.replace(",", "")) * 10000  # Convert 万円 to yen
                amounts.append(value)
            except ValueError:
                continue

        if not amounts:
            return None, None

        # If only monthly (no annual mentioned), convert to annual
        # But only convert amounts that are clearly monthly (< 250万円 = ¥2,500,000)
        # Amounts >= 250万円 are likely annual examples even without "年収" prefix
        if is_monthly and not is_annual:
            amounts = [a * 12 if a < 2500000 else a for a in amounts]

        # Get min and max from all amounts found
        salary_min = min(amounts)
        salary_max = max(amounts)

        return salary_min, salary_max

    def _extract_dl_value(self, article: BeautifulSoup, label: str) -> str | None:
        """Extract value from a dl element by its label.

        Args:
            article: BeautifulSoup article element.
            label: The label text to search for (e.g., "勤務地", "給与").

        Returns:
            The value text, or None if not found.
        """
        # Find span containing the label
        label_span = article.find("span", string=lambda x: x and label in x)
        if not label_span:
            return None

        # The value is typically in the parent's next sibling or nearby
        parent = label_span.parent
        if parent:
            # Get the parent's parent (usually the dl or container)
            container = parent.parent
            if container:
                # Get all text except the label
                full_text = container.get_text(strip=True)
                # Remove the label from the text
                value = full_text.replace(label, "").strip()
                return value if value else None

        return None

    def _parse_job(self, article: BeautifulSoup) -> dict | None:
        """Parse a single job article element.

        Args:
            article: BeautifulSoup article element.

        Returns:
            Job dictionary, or None if parsing failed.
        """
        try:
            # Extract company name from h2
            company_elem = article.find("h2")
            company = company_elem.get_text(strip=True) if company_elem else None

            # Extract title and URL from job detail link
            detail_link = article.find("a", href=lambda x: x and "JobSearchDetail" in x)
            if not detail_link:
                return None

            url = detail_link.get("href", "")
            if not url.startswith("http"):
                url = urljoin(self.BASE_URL, url)

            # Title is in the link text, but often includes company name
            # Try to get cleaner title from the link
            raw_title = detail_link.get_text(strip=True)

            # Remove company name from title if it's prefixed
            title = raw_title
            if company and raw_title.startswith(company):
                title = raw_title[len(company):].strip()

            # Extract job ID
            job_id = self._extract_job_id(url)
            if not job_id:
                return None

            # Extract location and salary from dl elements
            location = self._extract_dl_value(article, "勤務地")
            salary_text = self._extract_dl_value(article, "給与")

            # Parse salary into annual min/max
            salary_annual_min, salary_annual_max = self._parse_salary(salary_text)

            # Get full job body text for description/keyword matching
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

    def _get_next_page_url(self, soup: BeautifulSoup) -> str | None:
        """Find the next page URL from pagination.

        Args:
            soup: BeautifulSoup object of the current page.

        Returns:
            Next page URL, or None if no next page.
        """
        # Look for link containing "次" (next)
        next_link = soup.find("a", string=lambda x: x and "次" in x)
        if next_link:
            href = next_link.get("href", "")
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

        # Find all job articles
        articles = soup.find_all("article")
        self.logger.info(f"Found {len(articles)} job articles on page")

        for article in articles:
            job = self._parse_job(article)
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
            max_pages: Maximum number of pages to scrape (default 3 = ~150 jobs).

        Returns:
            List of job dictionaries.
        """
        all_jobs = []
        url = self._build_search_url(keywords, location)

        self.logger.info(f"Starting search: keywords={keywords}, location={location}")
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

        self.logger.info(f"Search complete. Total jobs found: {len(all_jobs)}")
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
