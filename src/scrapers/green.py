"""Green Japan job board scraper."""

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper


class GreenScraper(BaseScraper):
    """Scraper for green-japan.com job board."""

    BASE_URL = "https://www.green-japan.com"
    SEARCH_URL = "https://www.green-japan.com/search_key"

    # Regex patterns
    JOB_ID_PATTERN = re.compile(r"/job/(\d+)")
    SALARY_PATTERN = re.compile(r"(\d{3,})\s*万円?\s*[〜~～ー－-]\s*(\d{3,})\s*万円?")
    SALARY_SINGLE_PATTERN = re.compile(r"(\d{3,})\s*万円")

    @property
    def job_board_name(self) -> str:
        return "green"

    def _build_search_url(self, keywords: list[str], location: str = None) -> str:
        """Build the search URL with keywords.

        Args:
            keywords: List of keywords to search for.
            location: Optional location (not directly supported, included in keywords).

        Returns:
            Search URL string.
        """
        search_term = " ".join(keywords)
        if location:
            search_term += f" {location}"

        params = {"keyword": search_term}
        return f"{self.SEARCH_URL}?{urlencode(params)}"

    def _parse_salary(self, salary_text: str | None) -> tuple[int | None, int | None]:
        """Parse salary text and extract annual min/max values in yen.

        Green salaries are typically annual (e.g., "400万円〜600万円").

        Args:
            salary_text: Raw salary text.

        Returns:
            Tuple of (annual_min, annual_max) in yen.
        """
        if not salary_text:
            return None, None

        # Try range pattern first (e.g., "400万円〜600万円")
        match = self.SALARY_PATTERN.search(salary_text)
        if match:
            min_val = int(match.group(1)) * 10000
            max_val = int(match.group(2)) * 10000
            return min_val, max_val

        # Try single value pattern (e.g., "400万円")
        match = self.SALARY_SINGLE_PATTERN.search(salary_text)
        if match:
            val = int(match.group(1)) * 10000
            return val, val

        return None, None

    def _find_job_containers(self, soup: BeautifulSoup) -> list[BeautifulSoup]:
        """Find all job card containers on the page.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            List of job container elements.
        """
        containers = []
        seen_urls = set()

        # Find all job links
        job_links = soup.find_all("a", href=self.JOB_ID_PATTERN)

        for link in job_links:
            url = link.get("href", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Walk up to find a container with substantial content
            parent = link.parent
            max_depth = 8
            depth = 0

            while parent and parent.name != "body" and depth < max_depth:
                text_len = len(parent.get_text(strip=True))
                # Look for container with enough content (company, title, salary, etc.)
                if text_len > 100:
                    containers.append(parent)
                    break
                parent = parent.parent
                depth += 1

        return containers

    def _extract_text_lines(self, container: BeautifulSoup) -> list[str]:
        """Extract clean text lines from a container.

        Args:
            container: BeautifulSoup element.

        Returns:
            List of non-empty text lines.
        """
        text = container.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return lines

    def _find_company(self, lines: list[str]) -> str | None:
        """Find company name from text lines.

        Usually the first meaningful line (skip "New" badges, numbers, etc.).
        """
        for line in lines[:5]:
            # Skip short lines, numbers, or common badges
            if len(line) < 3:
                continue
            if line in ["New", "NEW", "急募", "PR"]:
                continue
            if re.match(r"^\d+人?$", line):  # Employee count
                continue
            if re.match(r"^\d{4}年", line):  # Founded year
                continue
            # First substantial text is likely company name
            if "株式会社" in line or "会社" in line or len(line) > 5:
                return line
        return lines[0] if lines else None

    def _find_title(self, lines: list[str]) -> str | None:
        """Find job title from text lines.

        Usually a longer line containing job-related keywords.
        """
        for line in lines:
            # Skip short lines
            if len(line) < 15:
                continue
            # Look for job-related keywords
            job_keywords = ["デザイナー", "エンジニア", "マネージャー", "ディレクター",
                           "募集", "開発", "担当", "リーダー", "スペシャリスト"]
            if any(kw in line for kw in job_keywords):
                return line
        # Fallback: return longest line
        if lines:
            return max(lines, key=len)
        return None

    def _find_location(self, lines: list[str]) -> str | None:
        """Find location from text lines."""
        location_markers = ["都", "道", "府", "県", "市", "区", "リモート", "在宅"]
        for line in lines:
            if len(line) < 50 and any(marker in line for marker in location_markers):
                return line
        return None

    def _find_salary(self, lines: list[str]) -> str | None:
        """Find salary text from text lines."""
        for line in lines:
            if "万円" in line or "万〜" in line:
                return line
        return None

    def _parse_job(self, container: BeautifulSoup) -> dict | None:
        """Parse a single job container element.

        Args:
            container: BeautifulSoup element for the job card.

        Returns:
            Job dictionary, or None if parsing failed.
        """
        try:
            # Find job link
            job_link = container.find("a", href=self.JOB_ID_PATTERN)
            if not job_link:
                return None

            url = job_link.get("href", "")
            if not url.startswith("http"):
                url = urljoin(self.BASE_URL, url)

            # Extract job ID
            match = self.JOB_ID_PATTERN.search(url)
            job_id = match.group(1) if match else None
            if not job_id:
                return None

            # Extract text lines for parsing
            lines = self._extract_text_lines(container)

            # Extract fields
            company = self._find_company(lines)
            title = self._find_title(lines)
            location = self._find_location(lines)
            salary_text = self._find_salary(lines)
            salary_annual_min, salary_annual_max = self._parse_salary(salary_text)

            # Description is all the text content
            description = " ".join(lines)

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
            self.logger.warning(f"Failed to parse job container: {e}")
            return None

    def _get_next_page_url(self, soup: BeautifulSoup, current_page: int) -> str | None:
        """Find the next page URL.

        Args:
            soup: BeautifulSoup object of the current page.
            current_page: Current page number (0-indexed).

        Returns:
            Next page URL, or None if no next page.
        """
        next_page = current_page + 1

        # Look for link to next page
        next_link = soup.find("a", href=re.compile(rf"page={next_page}"))
        if next_link:
            href = next_link.get("href", "")
            return urljoin(self.BASE_URL, href) if not href.startswith("http") else href

        return None

    def _parse_page(self, html: str, current_page: int = 0) -> tuple[list[dict], str | None]:
        """Parse a search results page.

        Args:
            html: HTML content of the page.
            current_page: Current page number for pagination.

        Returns:
            Tuple of (list of jobs, next page URL or None).
        """
        soup = BeautifulSoup(html, "lxml")
        jobs = []

        # Find all job containers
        containers = self._find_job_containers(soup)
        self.logger.info(f"Found {len(containers)} job containers on page")

        for container in containers:
            job = self._parse_job(container)
            if job:
                jobs.append(job)

        # Get next page URL
        next_url = self._get_next_page_url(soup, current_page)

        return jobs, next_url

    def search(
        self, keywords: list[str], location: str = None, max_pages: int = 3
    ) -> list[dict]:
        """Search for jobs matching the given criteria.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter (added to keywords).
            max_pages: Maximum number of pages to scrape.

        Returns:
            List of job dictionaries.
        """
        all_jobs = []
        url = self._build_search_url(keywords, location)

        self.logger.info(f"Starting Green search: keywords={keywords}, location={location}")
        self.logger.info(f"Search URL: {url}")

        for page_num in range(max_pages):
            self.logger.info(f"Scraping page {page_num + 1}/{max_pages}")

            html = self.fetch(url)
            if not html:
                self.logger.error(f"Failed to fetch page {page_num + 1}")
                break

            jobs, next_url = self._parse_page(html, page_num)
            all_jobs.extend(jobs)

            self.logger.info(f"Extracted {len(jobs)} jobs from page {page_num + 1}")

            if not next_url:
                self.logger.info("No more pages available")
                break

            if page_num < max_pages - 1:
                url = next_url
                self.delay()

        self.logger.info(f"Green search complete. Total jobs found: {len(all_jobs)}")
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
