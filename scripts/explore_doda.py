#!/usr/bin/env python3
"""Explore Doda job board structure for scraper development.

Usage:
    python scripts/explore_doda.py              # Fetch from web
    python scripts/explore_doda.py --local FILE # Analyze local HTML file

If the site is inaccessible, manually save the page:
1. Open https://doda.jp/DodaFront/View/JobSearchList.action in browser
2. Search for "デザイナー 東京"
3. Save page as HTML (Cmd+S) to data/exploration/doda_search_results.html
4. Run: python scripts/explore_doda.py --local data/exploration/doda_search_results.html
"""

import argparse
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Output directory for saved HTML
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "exploration"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_search_page(keyword: str = "デザイナー", location: str = "東京") -> str | None:
    """Fetch Doda search results page."""
    url = "https://doda.jp/DodaFront/View/JobSearchList.action"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
    }

    params = {
        "keyword": keyword,
        "area": location,
    }

    print(f"Fetching: {url}")
    print(f"Search: keyword='{keyword}', location='{location}'")

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()

    print(f"Status: {response.status_code}")
    print(f"Content length: {len(response.text):,} bytes")

    return response.text


def load_local_html(filepath: str) -> str:
    """Load HTML from a local file."""
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    html = path.read_text(encoding="utf-8")
    print(f"Loaded local file: {filepath}")
    print(f"Content length: {len(html):,} bytes")
    return html


def save_html(html: str, filename: str = "doda_search_results.html") -> Path:
    """Save HTML to file for manual inspection."""
    filepath = OUTPUT_DIR / filename
    filepath.write_text(html, encoding="utf-8")
    print(f"Saved HTML to: {filepath}")
    return filepath


def analyze_structure(html: str) -> dict:
    """Analyze the HTML structure to find job listing elements."""
    soup = BeautifulSoup(html, "lxml")
    results = {
        "job_containers": [],
        "pagination": [],
        "sample_jobs": [],
    }

    print("\n" + "=" * 60)
    print("STRUCTURE ANALYSIS")
    print("=" * 60)

    # Try common job listing container patterns
    container_selectors = [
        ("article", {}),
        ("div", {"class": lambda x: x and "job" in " ".join(x).lower()}),
        ("div", {"class": lambda x: x and "card" in " ".join(x).lower()}),
        ("div", {"class": lambda x: x and "list" in " ".join(x).lower() and "item" in " ".join(x).lower()}),
        ("li", {"class": lambda x: x and "job" in " ".join(x).lower()}),
        ("div", {"class": "jobCard"}),
        ("div", {"class": "searchList"}),
    ]

    print("\n--- Searching for job containers ---")
    for tag, attrs in container_selectors:
        elements = soup.find_all(tag, attrs)
        if elements:
            sample_classes = [" ".join(el.get("class", [])) for el in elements[:3]]
            print(f"  {tag} with {attrs}: found {len(elements)} elements")
            for cls in sample_classes:
                if cls:
                    print(f"    - class: {cls}")

    # Look for any element with 'job' in class name
    print("\n--- Elements with 'job' in class name ---")
    all_elements = soup.find_all(class_=lambda x: x and any("job" in c.lower() for c in x))
    class_counts = {}
    for el in all_elements:
        cls = " ".join(el.get("class", []))
        class_counts[cls] = class_counts.get(cls, 0) + 1

    for cls, count in sorted(class_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  {count}x: {cls}")

    # Look for links that might be job links
    print("\n--- Potential job links ---")
    job_links = soup.find_all("a", href=lambda x: x and "/DodaFront/View/JobSearch" in x)
    if not job_links:
        job_links = soup.find_all("a", href=lambda x: x and "/job/" in x.lower())
    if not job_links:
        job_links = soup.find_all("a", href=lambda x: x and "detail" in x.lower())

    print(f"  Found {len(job_links)} potential job links")
    for link in job_links[:5]:
        href = link.get("href", "")[:80]
        text = link.get_text(strip=True)[:50]
        print(f"    - {text}: {href}...")

    # Look for pagination
    print("\n--- Pagination elements ---")
    pagination_selectors = [
        ("nav", {"class": lambda x: x and "pag" in " ".join(x).lower()}),
        ("ul", {"class": lambda x: x and "pag" in " ".join(x).lower()}),
        ("div", {"class": lambda x: x and "pag" in " ".join(x).lower()}),
        ("a", {"class": lambda x: x and "next" in " ".join(x).lower()}),
        ("a", {"rel": "next"}),
    ]

    for tag, attrs in pagination_selectors:
        elements = soup.find_all(tag, attrs)
        if elements:
            print(f"  {tag} with {attrs}: found {len(elements)} elements")
            for el in elements[:2]:
                cls = " ".join(el.get("class", []))
                print(f"    - class: {cls}")

    # Look for page numbers
    page_links = soup.find_all("a", href=lambda x: x and "page" in x.lower())
    if page_links:
        print(f"  Found {len(page_links)} links with 'page' in URL")
        for link in page_links[:3]:
            print(f"    - {link.get('href', '')[:60]}")

    # Try to extract sample job data
    print("\n--- Sample job extraction attempt ---")

    # Look for structured data
    scripts = soup.find_all("script", type="application/ld+json")
    if scripts:
        print(f"  Found {len(scripts)} JSON-LD scripts (structured data)")

    # Find headings that might be job titles
    headings = soup.find_all(["h1", "h2", "h3", "h4"])
    job_headings = [h for h in headings if len(h.get_text(strip=True)) > 10 and len(h.get_text(strip=True)) < 200]
    print(f"  Found {len(job_headings)} potential job title headings")
    for h in job_headings[:5]:
        print(f"    - <{h.name}>: {h.get_text(strip=True)[:60]}...")

    # Check page title
    title = soup.find("title")
    if title:
        print(f"\n--- Page title ---")
        print(f"  {title.get_text(strip=True)}")

    # Check for "no results" indicators
    print("\n--- Checking for 'no results' indicators ---")
    no_result_patterns = ["見つかりませんでした", "0件", "該当する求人", "検索結果なし"]
    page_text = soup.get_text()
    for pattern in no_result_patterns:
        if pattern in page_text:
            print(f"  Warning: Found '{pattern}' - may be no results page")

    return results


def print_raw_structure(html: str, max_depth: int = 4):
    """Print a simplified view of the HTML structure."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")

    print("\n" + "=" * 60)
    print("SIMPLIFIED DOM STRUCTURE (first few levels)")
    print("=" * 60)

    def print_element(el, depth=0):
        if depth > max_depth:
            return
        if el.name is None:
            return

        indent = "  " * depth
        classes = " ".join(el.get("class", []))[:40]
        el_id = el.get("id", "")[:20]

        id_str = f" id='{el_id}'" if el_id else ""
        class_str = f" class='{classes}'" if classes else ""

        # Only print structural elements
        if el.name in ["div", "section", "article", "main", "nav", "ul", "ol", "header", "footer"]:
            print(f"{indent}<{el.name}{id_str}{class_str}>")
            for child in el.children:
                if hasattr(child, "name"):
                    print_element(child, depth + 1)

    if body:
        print_element(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Explore Doda job board structure")
    parser.add_argument(
        "--local",
        type=str,
        help="Path to local HTML file to analyze instead of fetching from web"
    )
    args = parser.parse_args()

    try:
        if args.local:
            # Load from local file
            html = load_local_html(args.local)
        else:
            # Fetch from web
            html = fetch_search_page()
            if html:
                save_html(html)

        if not html:
            print("\nCould not get HTML. Try saving the page manually:")
            print("1. Open https://doda.jp/DodaFront/View/JobSearchList.action")
            print("2. Search for 'デザイナー 東京'")
            print("3. Save page as: data/exploration/doda_search_results.html")
            print("4. Run: python scripts/explore_doda.py --local data/exploration/doda_search_results.html")
            sys.exit(1)

        # Analyze structure
        analyze_structure(html)

        # Print simplified structure
        print_raw_structure(html)

        print("\n" + "=" * 60)
        print("NEXT STEPS")
        print("=" * 60)
        if not args.local:
            print("1. Open data/exploration/doda_search_results.html in a browser")
        print("2. Use browser DevTools to inspect job listing elements")
        print("3. Identify the correct CSS selectors based on the analysis above")

    except requests.RequestException as e:
        print(f"Error fetching page: {e}")
        print("\nThe site may be blocking requests. Try the local file method:")
        print("1. Open https://doda.jp/DodaFront/View/JobSearchList.action in your browser")
        print("2. Search for 'デザイナー 東京'")
        print("3. Save page as: data/exploration/doda_search_results.html")
        print("4. Run: python scripts/explore_doda.py --local data/exploration/doda_search_results.html")
        sys.exit(1)
