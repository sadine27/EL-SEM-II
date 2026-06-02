"""Trend source: Google News India, segmented by commerce-relevant topics.

Google News exposes a free, key-less RSS endpoint that accepts an arbitrary
search query (`/rss/search?q=...`). We hit it once per commercial-intent topic
(deals, gadgets, launches, sports merch, entertainment) so the firehose surfaces
event-driven products the moment they trend — e.g. a team wins and "<team>
jersey" articles spike, or a new toy like "Labubu" goes viral.

No API key required. Each query is isolated so one failing topic cannot sink
the rest; missing network → empty list (fail-soft).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import requests

from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "google_news_india"
log = get_logger(__name__)

_TIMEOUT = 20
_MAX_PER_TOPIC = 15
_BASE = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# Commerce-intent angles. "when:2d" scopes Google News to the last 2 days so we
# catch what is trending *now*, not stale evergreen articles.
_TOPICS: list[tuple[str, str]] = [
    ("trending product india when:2d", "trending"),
    ("best selling gadget india when:2d", "gadgets"),
    ("new launch sale deal india when:2d", "deals"),
    ("viral product india when:2d", "viral"),
    ("jersey merchandise fans india when:2d", "sports_merch"),
    ("movie series merch india when:2d", "entertainment"),
]

_TITLE_RE = re.compile(
    r"<title>(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?</title>",
    re.IGNORECASE,
)


def _parse_titles(xml: str) -> list[str]:
    """Extract up to _MAX_PER_TOPIC <title> entries, skipping the channel title."""
    matches = _TITLE_RE.findall(xml or "")
    titles: list[str] = []
    for raw in matches[1 : _MAX_PER_TOPIC + 1]:
        title = raw.strip()
        if title and len(title) > 5:
            titles.append(title)
    return titles


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    seen: set[str] = set()

    for query, topic_id in _TOPICS:
        url = _BASE.format(q=quote_plus(query))
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            if resp.status_code != 200:
                log.debug("google_news_india %s → HTTP %d", topic_id, resp.status_code)
                continue
            for title in _parse_titles(resp.text):
                if title in seen:
                    continue
                seen.add(title)
                candidates.append(TrendCandidate(
                    title=title,
                    source_id=f"{SOURCE_ID}:{topic_id}",
                    raw_payload={"gnews_topic": topic_id, "gnews_query": query},
                    fetched_at=now,
                ))
        except Exception as exc:
            log.debug("google_news_india %s: %s", topic_id, exc)

    log.info("google_news_india: %d candidates across %d topics",
             len(candidates), len(_TOPICS))
    return candidates
