"""Job board scrapers."""

from .base import BaseScraper
from .doda import DodaScraper
from .green import GreenScraper
from .indeed import IndeedScraper

__all__ = ["BaseScraper", "DodaScraper", "GreenScraper", "IndeedScraper"]
