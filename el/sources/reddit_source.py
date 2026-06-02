"""Trend source: Reddit India subreddits.

Monitors hot posts across India-focused subreddits. Velocity is computed
from upvote score per hour since post creation (log-normalised to [0, 1]).

Requires env vars:
  REDDIT_CLIENT_ID      — from reddit.com/prefs/apps (free)
  REDDIT_CLIENT_SECRET  — same app
  REDDIT_USER_AGENT     — e.g. "EL-TrendBot/2.0"

pip install praw
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from math import log10

from el import config
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


def _upvote_velocity(post) -> float:
    """Upvotes per hour since creation, log-normalised to [0, 1].

    100 upvotes/hr ≈ 1.0 (log10(100)/2 = 1.0).
    """
    age_hours = max(0.1, (time.time() - post.created_utc) / 3600)
    ups_per_hour = post.score / age_hours
    return round(min(1.0, log10(max(1.0, ups_per_hour)) / 2.0), 3)


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    client_id = config.get("REDDIT_CLIENT_ID")
    client_secret = config.get("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        log.info("Reddit source skipped — REDDIT_CLIENT_ID/SECRET not set")
        return []

    try:
        import praw  # noqa: F401
    except ImportError:
        log.warning("praw not installed — run: pip install praw")
        return []

    import praw as _praw  # re-import so pyright is happy

    candidates: list[TrendCandidate] = []
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    try:
        reddit = _praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=config.get("REDDIT_USER_AGENT") or "EL-TrendBot/2.0 (el_pipeline)",
            read_only=True,
        )

        for sub_name in SUBREDDITS:
            try:
                for post in reddit.subreddit(sub_name).hot(limit=POSTS_PER_SUB):
                    if post.score < MIN_SCORE:
                        continue
                    candidates.append(TrendCandidate(
                        title=post.title,
                        source_id=SOURCE_ID,
                        velocity=_upvote_velocity(post),
                        raw_payload={
                            "subreddit": sub_name,
                            "reddit_score": post.score,
                            "upvote_ratio": post.upvote_ratio,
                            "url": post.url,
                        },
                        fetched_at=now,
                    ))
            except Exception as exc:
                log.debug("reddit r/%s: %s", sub_name, exc)

    except Exception:
        log.exception("reddit source: unexpected error")

    log.info("reddit: %d candidates from %d subreddits", len(candidates), len(SUBREDDITS))
    return candidates
