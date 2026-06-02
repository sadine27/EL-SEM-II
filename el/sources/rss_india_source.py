"""Trend source: Indian tech & commerce RSS network.

Aggregates RSS feeds from major Indian tech, gadget, and commerce publications.
No API keys required — all feeds are publicly available.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import requests

from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "rss_india"
log = get_logger(__name__)

_TIMEOUT = 20
_MAX_PER_FEED = 20

# (url, feed_id) — covering tech, gadgets, deals, finance, consumer products
_FEEDS: list[tuple[str, str]] = [
    # Tech & Gadgets
    ("https://gadgets.ndtv.com/rss/feeds", "ndtv_gadgets"),
    ("https://www.bgr.in/feed/", "bgr_india"),
    ("https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms", "et_tech"),
    ("https://www.digit.in/rss/news/rss.xml", "digit_in"),
    # Commerce & Industry
    ("https://economictimes.indiatimes.com/small-biz/rssfeeds/13357468.cms", "et_retail"),
    ("https://www.financialexpress.com/feed/", "financial_express"),
    # Consumer & Lifestyle
    ("https://www.livemint.com/rss/industry", "mint_industry"),
    ("https://www.thehindu.com/sci-tech/technology/feeder/default.rss", "the_hindu_tech"),
    # Deals & Offers (Indian deal aggregators)
    ("https://www.dealnloot.com/feed", "dealnloot"),
    ("https://www.desidime.com/feed", "desidime"),
]

_TITLE_RE = re.compile(
    r"<title>(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?</title>",
    re.IGNORECASE,
)


def _parse_titles(xml: str) -> list[str]:
    """Extract up to _MAX_PER_FEED <title> entries, skipping the channel title."""
    matches = _TITLE_RE.findall(xml or "")
    titles = []
    for raw in matches[1 : _MAX_PER_FEED + 1]:
        title = raw.strip()
        if title and len(title) > 5:
            titles.append(title)
    return titles


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    seen: set[str] = set()

    for url, feed_id in _FEEDS:
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code != 200:
                log.debug("rss_india %s → HTTP %d", feed_id, resp.status_code)
                continue
            for title in _parse_titles(resp.text):
                if title in seen:
                    continue
                seen.add(title)
                candidates.append(TrendCandidate(
                    title=title,
                    source_id=f"{SOURCE_ID}:{feed_id}",
                    raw_payload={"rss_feed": feed_id, "rss_url": url},
                    fetched_at=now,
                ))
        except Exception as exc:
            log.debug("rss_india %s: %s", feed_id, exc)

    log.info("rss_india: %d candidates across %d feeds", len(candidates), len(_FEEDS))
    return candidates
