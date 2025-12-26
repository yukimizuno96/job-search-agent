"""Wantedly job board scraper."""

import json
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper


class WantedlyScraper(BaseScraper):
    """Scraper for wantedly.com job board."""

    BASE_URL = "https://www.wantedly.com"
    SEARCH_URL = "https://www.wantedly.com/projects"

    @property
    def job_board_name(self) -> str:
        return "wantedly"

    def _build_search_url(self, keywords: list[str], location: str = None, page: int = 1) -> str:
        """Build the search URL with keywords and location.

        Note: Wantedly's search is JavaScript-based, so we use category URLs instead.

        Args:
            keywords: List of keywords to search for.
            location: Optional location filter.
            page: Page number.

        Returns:
            Search URL string.
        """
        # Wantedly search is JS-based, so we use occupation category URLs
        # Map common keywords to Wantedly occupation slugs
        occupation_map = {
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

        # Find matching occupation
        occupation = None
        for kw in keywords:
            if kw in occupation_map:
                occupation = occupation_map[kw]
                break

        # Build URL with occupation filter
        if occupation:
            base_url = f"https://www.wantedly.com/projects?occupation_types%5B%5D={occupation}"
        else:
            base_url = self.SEARCH_URL

        # Add page
        if page > 1:
            separator = "&" if "?" in base_url else "?"
            return f"{base_url}{separator}page={page}"

        return base_url

    def _extract_apollo_state(self, html: str) -> dict:
        """Extract Apollo GraphQL state from the page.

        Args:
            html: HTML content.

        Returns:
            Apollo state dictionary.
        """
        soup = BeautifulSoup(html, "lxml")

        for script in soup.find_all("script"):
            if script.string and "window.__APOLLO_STATE__" in script.string:
                # Extract JSON from the script
                match = re.search(r'window\.__APOLLO_STATE__\s*=\s*({.*?});', script.string, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        pass

        return {}

    def _parse_apollo_projects(self, apollo_state: dict) -> list[dict]:
        """Parse project data from Apollo state.

        Args:
            apollo_state: Apollo GraphQL state dictionary.

        Returns:
            List of job dictionaries.
        """
        jobs = []

        for key, value in apollo_state.items():
            # Look for Project entries
            if key.startswith("Project:") and isinstance(value, dict):
                try:
                    project_id = value.get("id")
                    if not project_id:
                        continue

                    title = value.get("title", "")

                    # Get company info
                    company_ref = value.get("company")
                    company_name = ""
                    if company_ref and isinstance(company_ref, dict):
                        company_id = company_ref.get("id")
                        if company_id:
                            company_key = f"Company:{company_id}"
                            company_data = apollo_state.get(company_key, {})
                            company_name = company_data.get("name", "")

                    # Get location
                    location = value.get("locationName", "")

                    # Get description/excerpt
                    description = value.get("excerpt", "") or value.get("description", "")

                    # Build URL
                    url = f"{self.BASE_URL}/projects/{project_id}"

                    jobs.append({
                        "job_id": str(project_id),
                        "title": title,
                        "company": company_name,
                        "location": location,
                        "description": description,
                        "salary_text": None,  # Wantedly typically doesn't show salary
                        "salary_annual_min": None,
                        "salary_annual_max": None,
                        "url": url,
                        "job_board": self.job_board_name,
                    })

                except Exception as e:
                    self.logger.warning(f"Failed to parse project {key}: {e}")
                    continue

        return jobs

    def _parse_html_fallback(self, html: str) -> list[dict]:
        """Fallback parser using HTML structure.

        Args:
            html: HTML content.

        Returns:
            List of job dictionaries.
        """
        soup = BeautifulSoup(html, "lxml")
        jobs = []

        # Find all project links
        project_links = soup.select('a[href*="/projects/"]')
        seen_ids = set()

        for link in project_links:
            try:
                href = link.get("href", "")

                # Extract project ID
                match = re.search(r'/projects/(\d+)', href)
                if not match:
                    continue

                project_id = match.group(1)
                if project_id in seen_ids:
                    continue
                seen_ids.add(project_id)

                # Get title from link text or nearby elements
                title = link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                # Try to find company name (usually in parent or sibling)
                company = ""
                parent = link.find_parent("div") or link.find_parent("article")
                if parent:
                    # Look for company-related elements
                    company_elem = parent.select_one('[class*="company"], [class*="Company"]')
                    if company_elem:
                        company = company_elem.get_text(strip=True)

                url = urljoin(self.BASE_URL, href.split("?")[0])

                jobs.append({
                    "job_id": project_id,
                    "title": title[:200],  # Truncate long titles
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
                self.logger.warning(f"Failed to parse project link: {e}")
                continue

        return jobs

    def _has_next_page(self, html: str, current_page: int) -> bool:
        """Check if there's a next page.

        Args:
            html: HTML content.
            current_page: Current page number.

        Returns:
            True if there's a next page.
        """
        soup = BeautifulSoup(html, "lxml")

        # Look for pagination links
        next_link = soup.select_one(f'a[href*="page={current_page + 1}"]')
        if next_link:
            return True

        # Check for "次へ" or "Next" links
        next_text = soup.find("a", string=re.compile(r"次|Next", re.IGNORECASE))
        if next_text:
            return True

        return False

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
        seen_ids = set()

        self.logger.info(f"Starting Wantedly search: keywords={keywords}, location={location}")

        for page_num in range(1, max_pages + 1):
            url = self._build_search_url(keywords, location, page_num)
            self.logger.info(f"Scraping page {page_num}/{max_pages}: {url}")

            html = self.fetch(url)
            if not html:
                self.logger.error(f"Failed to fetch page {page_num}")
                break

            # Try Apollo state first
            apollo_state = self._extract_apollo_state(html)
            if apollo_state:
                jobs = self._parse_apollo_projects(apollo_state)
                self.logger.info(f"Extracted {len(jobs)} jobs from Apollo state")
            else:
                # Fallback to HTML parsing
                jobs = self._parse_html_fallback(html)
                self.logger.info(f"Extracted {len(jobs)} jobs from HTML fallback")

            # Deduplicate
            new_jobs = []
            for job in jobs:
                if job["job_id"] not in seen_ids:
                    seen_ids.add(job["job_id"])
                    new_jobs.append(job)

            all_jobs.extend(new_jobs)
            self.logger.info(f"Added {len(new_jobs)} new jobs from page {page_num}")

            # Check for next page
            if page_num < max_pages:
                if not self._has_next_page(html, page_num):
                    self.logger.info("No more pages available")
                    break
                self.delay()

        self.logger.info(f"Wantedly search complete. Total jobs found: {len(all_jobs)}")
        return all_jobs
