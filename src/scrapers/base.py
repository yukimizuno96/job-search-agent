"""Base scraper class with common functionality."""

import logging
import random
import time
from abc import ABC, abstractmethod

import requests


class BaseScraper(ABC):
    """Base class for job board scrapers."""

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, delay_range: tuple[float, float] = (2.0, 3.0)):
        """Initialize scraper with delay settings.

        Args:
            delay_range: Tuple of (min_delay, max_delay) seconds between requests.
        """
        self.delay_range = delay_range
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Set up logger for this scraper."""
        logger = logging.getLogger(self.__class__.__name__)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def delay(self) -> None:
        """Sleep for a random duration within the delay range."""
        sleep_time = random.uniform(*self.delay_range)
        self.logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)

    def fetch(self, url: str, params: dict = None) -> str | None:
        """Fetch a URL and return the HTML content.

        Args:
            url: The URL to fetch.
            params: Optional query parameters.

        Returns:
            HTML content as string, or None if request failed.
        """
        try:
            self.logger.debug(f"Fetching: {url}")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            self.logger.error(f"Failed to fetch {url}: {e}")
            return None

    @property
    @abstractmethod
    def job_board_name(self) -> str:
        """Return the name of the job board."""
        pass

    @abstractmethod
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
        pass
