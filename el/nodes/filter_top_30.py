"""Port of n8n node `Filter Top 30`.

Slices the top 30 entries from `ranked_payload.trends`, formats them as a
numbered text block for the curator LLM, and derives a `run_date` (YYYY-MM-DD)
from the payload's `scraped_at` timestamp.

Stores `ctx["filtered"] = {topics_text, run_date, total}`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)

TOP_N = 30


def _categories(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(cat) for cat in value if cat]


def run(ctx: dict) -> dict:
    payload = ctx.get("ranked_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    trends = [
        trend for trend in (payload.get("trends") or [])
        if isinstance(trend, dict)
    ][:TOP_N]

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    scraped_at = metadata.get("scraped_at") or ""
    run_date = scraped_at[:10] if scraped_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    topics_text = "\n".join(
        f'{t.get("rank", "")}. "{t.get("topic", "")}" | intent:{t.get("product_intent_score", "")} '
        f'| cats:{",".join(_categories(t.get("suggested_categories")))} '
        f'| src:{t.get("source", "")}'
        for t in trends
    )

    log.info("Filter Top 30: %d topics for run_date=%s", len(trends), run_date)
    ctx["filtered"] = {
        "topics_text": topics_text,
        "run_date": run_date,
        "total": len(trends),
    }
    return ctx
