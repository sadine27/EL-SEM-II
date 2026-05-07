"""Port of n8n node `Prepare Sheet Rows`."""
from __future__ import annotations

from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)

SHEET_ROW_COLUMNS = (
    "run_date",
    "rank",
    "topic",
    "source",
    "traffic_estimate",
    "product_intent_score",
    "related_queries",
    "suggested_categories",
)


def _run_date(payload: dict) -> str:
    scraped_at = (payload.get("metadata") or {}).get("scraped_at")
    if scraped_at:
        return scraped_at[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run(ctx: dict) -> dict:
    payload = ctx.get("ranked_payload") or {}
    run_date = _run_date(payload)
    rows = []
    for trend in payload.get("trends") or []:
        traffic = trend.get("traffic_estimate")
        rows.append({
            "run_date": run_date,
            "rank": trend.get("rank"),
            "topic": trend.get("topic"),
            "source": trend.get("source"),
            "traffic_estimate": traffic if traffic is not None else "N/A",
            "product_intent_score": trend.get("product_intent_score"),
            "related_queries": ", ".join(trend.get("related_queries") or []),
            "suggested_categories": ", ".join(trend.get("suggested_categories") or []),
        })
    log.info("Prepare Sheet Rows: prepared %d rows", len(rows))
    ctx["sheet_rows"] = rows
    return ctx
