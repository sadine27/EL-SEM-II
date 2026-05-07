"""Port of n8n node `YouTube Trending IN`.

n8n original: httpRequest → GET https://www.googleapis.com/youtube/v3/videos
with chart=mostPopular, regionCode=IN, maxResults=50, part=snippet, key=<YOUTUBE_API_KEY>.

Stores raw `items` list at ctx["youtube_items"]. Downstream node
`Fetch . Score . Dedupe . Rank` reads it from there.
"""
from __future__ import annotations

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_TIMEOUT = 30


def run(ctx: dict) -> dict:
    try:
        api_key = config.require("YOUTUBE_API_KEY")
    except Exception as exc:  # noqa: BLE001 - HTTP boundary nodes fail soft.
        ctx["youtube_items"] = []
        ctx["youtube_trending_result"] = {"ok": False, "error": str(exc)}
        return ctx
    params = {
        "chart": "mostPopular",
        "regionCode": "IN",
        "maxResults": "50",
        "part": "snippet",
        "key": api_key,
    }
    try:
        resp = requests.get(YOUTUBE_VIDEOS_URL, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - HTTP boundary nodes fail soft.
        ctx["youtube_items"] = []
        ctx["youtube_trending_result"] = {"ok": False, "error": str(exc)}
        log.warning("YouTube Trending IN failed: %s", exc)
        return ctx
    items = data.get("items", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        items = []
    log.info("YouTube Trending IN: fetched %d items", len(items))
    ctx["youtube_items"] = items
    ctx["youtube_trending_result"] = {"ok": True, "count": len(items)}
    return ctx
