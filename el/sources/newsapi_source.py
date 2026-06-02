"""Trend source: NewsAPI India — product launches, deals, viral items.

Searches NewsAPI for India-specific commerce signals across multiple query
angles.  Free tier: 100 requests/day at newsapi.org.

Requires env var:
  NEWSAPI_KEY   — free from newsapi.org

pip install newsapi-python
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "newsapi"
log = get_logger(__name__)

_ENDPOINT = "https://newsapi.org/v2/everything"
_TIMEOUT = 15
_MAX_PER_QUERY = 10

# Targeted queries covering different commercial intent angles for India
_QUERIES = [
    "trending products india",
    "best selling india 2026",
    "viral product india online",
    "new launch india sale deals",
    "top deals flipkart amazon india",
    "product review india worth buying",
    "india ecommerce trending category",
]


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    api_key = config.get("NEWSAPI_KEY")
    if not api_key:
        log.info("NewsAPI source skipped — NEWSAPI_KEY not set")
        return []

    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    seen: set[str] = set()

    for query in _QUERIES:
        try:
            resp = requests.get(
                _ENDPOINT,
                params={
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": _MAX_PER_QUERY,
                    "apiKey": api_key,
                },
                timeout=_TIMEOUT,
            )
            if resp.status_code == 429:
                log.warning("NewsAPI: rate limit hit — daily quota likely exhausted")
                break
            if resp.status_code != 200:
                log.debug("NewsAPI query %r → HTTP %d", query, resp.status_code)
                continue
            for article in resp.json().get("articles") or []:
                title = (article.get("title") or "").strip()
                if not title or title in seen or "[Removed]" in title:
                    continue
                seen.add(title)
                candidates.append(TrendCandidate(
                    title=title,
                    source_id=SOURCE_ID,
                    raw_payload={
                        "newsapi_url": article.get("url"),
                        "newsapi_source": (article.get("source") or {}).get("name"),
                        "newsapi_query": query,
                    },
                    fetched_at=now,
                ))
        except Exception as exc:
            log.debug("NewsAPI query %r: %s", query, exc)

    log.info("newsapi: %d candidates", len(candidates))
    return candidates
