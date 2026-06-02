"""Trend source: Amazon India Movers & Shakers.

Scrapes Amazon IN's "Movers & Shakers" pages — the fastest-rising products
in each category by sales rank.  These are by-definition trending UP, so
candidates get a high velocity hint.  No API key required.

pip install beautifulsoup4 lxml
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "amazon_in_movers"
log = get_logger(__name__)

_TIMEOUT = 20
_MAX_PER_CATEGORY = 12

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# Amazon India Movers & Shakers URLs by category
_CATEGORIES: dict[str, str] = {
    "electronics": "https://www.amazon.in/gp/movers-and-shakers/electronics/",
    "clothing": "https://www.amazon.in/gp/movers-and-shakers/apparel/",
    "beauty": "https://www.amazon.in/gp/movers-and-shakers/beauty/",
    "sports": "https://www.amazon.in/gp/movers-and-shakers/sports/",
    "home_kitchen": "https://www.amazon.in/gp/movers-and-shakers/kitchen/",
    "health": "https://www.amazon.in/gp/movers-and-shakers/hpc/",
    "baby": "https://www.amazon.in/gp/movers-and-shakers/baby/",
    "toys": "https://www.amazon.in/gp/movers-and-shakers/toys/",
    "office": "https://www.amazon.in/gp/movers-and-shakers/office/",
    "automotive": "https://www.amazon.in/gp/movers-and-shakers/automotive/",
}

# CSS selectors tried in order (Amazon periodically tweaks class names)
_SELECTORS = [
    ".zg-item-immersion .p13n-sc-truncate-desktop-type2",
    ".zg-item-immersion span.a-truncate-cut",
    ".p13n-sc-truncate",
    "span[class*='_cDEzb_p13n-sc-css-line-clamp']",
    ".zg-item .a-link-normal span",
]


def _extract_product_names(html: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "lxml")
    for sel in _SELECTORS:
        items = soup.select(sel)
        if items:
            names = [el.get_text(strip=True) for el in items[:_MAX_PER_CATEGORY]]
            return [n for n in names if n]
    return []


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    try:
        from bs4 import BeautifulSoup  # noqa: F401
    except ImportError:
        log.warning("beautifulsoup4 not installed — run: pip install beautifulsoup4 lxml")
        return []

    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    session = requests.Session()
    session.headers.update(_HEADERS)

    for category, url in _CATEGORIES.items():
        try:
            resp = session.get(url, timeout=_TIMEOUT)
            if resp.status_code != 200:
                log.debug("amazon movers %s → HTTP %d", category, resp.status_code)
                continue
            names = _extract_product_names(resp.text)
            if not names:
                log.debug("amazon movers %s: no products parsed (selector may have changed)", category)
                continue
            for name in names:
                candidates.append(TrendCandidate(
                    title=name,
                    source_id=SOURCE_ID,
                    velocity=0.65,  # movers & shakers = definitionally rising
                    raw_payload={"amazon_category": category, "amazon_url": url},
                    fetched_at=now,
                ))
        except Exception as exc:
            log.debug("amazon movers %s: %s", category, exc)

    log.info("amazon_in_movers: %d candidates across %d categories",
             len(candidates), len(_CATEGORIES))
    return candidates
