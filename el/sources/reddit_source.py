"""Trend source: Reddit India subreddit scraper.

Scrapes public subreddit JSON listing pages, so no Reddit developer app or API
credentials are needed. Velocity is computed from score per hour since post
creation (log-normalised to [0, 1]).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from math import log10
from typing import Any

import requests

from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "reddit"
log = get_logger(__name__)

# Subreddits covering Indian shopping, gaming, fashion, beauty, tech, entertainment
SUBREDDITS = [
    "india",
    "IndianGaming",
    "IndianFashion",
    "IndianBeautyDeals",
    "IndianSkincare",
    "frugalmalefashion",
    "BuyFromIndia",
    "indiasocial",
    "IndianCinema",
    "bollywood",
    "Cricket",
    "IndianStreetBets",
    "diwali",
    "BGMI",
]

POSTS_PER_SUB = 8
MIN_SCORE = 10  # ignore very-low-karma posts
_TIMEOUT = 15
_URLS = (
    "https://www.reddit.com/r/{sub}/hot/.json",
    "https://old.reddit.com/r/{sub}/hot/.json",
)
_HEADERS = {
    "User-Agent": "EL-FenixRedditScraper/1.0 (+https://github.com/sadine27/EL-SEM-II)",
    "Accept": "application/json",
}


def _upvote_velocity(score: int | float, created_utc: int | float | None) -> float:
    """Score/hour since creation, log-normalised to [0, 1]."""
    if not created_utc:
        return 0.0
    age_hours = max(0.1, (time.time() - float(created_utc)) / 3600)
    score_per_hour = float(score) / age_hours
    return round(min(1.0, log10(max(1.0, score_per_hour)) / 2.0), 3)


def _iter_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    children = payload.get("data", {}).get("children", [])
    posts: list[dict[str, Any]] = []
    for child in children:
        data = child.get("data", {}) if isinstance(child, dict) else {}
        if isinstance(data, dict):
            posts.append(data)
    return posts


def _fetch_subreddit(sub_name: str) -> list[dict[str, Any]]:
    params = {"limit": POSTS_PER_SUB, "raw_json": 1}
    last_status: int | None = None

    for template in _URLS:
        url = template.format(sub=sub_name)
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            last_status = resp.status_code
            if resp.status_code != 200:
                continue
            return _iter_posts(resp.json())
        except Exception as exc:
            log.debug("reddit scrape r/%s via %s: %s", sub_name, url, exc)

    if last_status is not None:
        log.debug("reddit scrape r/%s: final HTTP %d", sub_name, last_status)
    return []


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    seen_titles: set[str] = set()

    for sub_name in SUBREDDITS:
        for post in _fetch_subreddit(sub_name):
            title = str(post.get("title") or "").strip()
            score = int(post.get("score") or 0)
            if not title or title in seen_titles or score < MIN_SCORE:
                continue
            seen_titles.add(title)

            permalink = post.get("permalink") or ""
            candidates.append(TrendCandidate(
                title=title,
                source_id=SOURCE_ID,
                velocity=_upvote_velocity(score, post.get("created_utc")),
                raw_payload={
                    "subreddit": sub_name,
                    "reddit_score": score,
                    "upvote_ratio": post.get("upvote_ratio"),
                    "url": f"https://www.reddit.com{permalink}" if permalink else post.get("url"),
                },
                fetched_at=now,
            ))

    log.info("reddit scrape: %d candidates from %d subreddits", len(candidates), len(SUBREDDITS))
    return candidates
