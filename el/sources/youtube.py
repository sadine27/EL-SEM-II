"""Trend source: YouTube Trending IN.

Thin wrapper over `el/nodes/youtube_trending.run` that adapts the existing
node's output to the `TrendCandidate` shape. No new network calls.
"""
from __future__ import annotations

from el.logger import get_logger
from el.nodes import youtube_trending
from el.sources import TrendCandidate

SOURCE_ID = "youtube"

log = get_logger(__name__)


def fetch_trends(ctx: dict) -> list[TrendCandidate]:
    try:
        youtube_trending.run(ctx)
    except Exception:
        log.exception("youtube source: youtube_trending.run crashed")
        return []
    items = ctx.get("youtube_items") or []
    candidates: list[TrendCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get("snippet") or {}
        title = snippet.get("title") if isinstance(snippet, dict) else None
        if not title:
            continue
        candidates.append(TrendCandidate(
            title=str(title),
            source_id=SOURCE_ID,
            raw_payload=item,
        ))
    return candidates
