"""Port of n8n node `Normalize CJ Review`."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from el.logger import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_date_from_now(now_iso: str) -> str:
    return now_iso[:10]


def parse_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json_string(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _truncate_description(value: Any) -> str | None:
    if not value:
        return None
    return str(value)[:300]


def normalize_row(
    row: dict,
    *,
    now_iso: str | None = None,
    execution_id: str = "manual",
) -> dict | None:
    """Normalize one CJ product row into the HIL review contract."""
    if not row.get("product_url") or not row.get("source_topic") or not row.get("product_name"):
        return None

    now_value = now_iso or _now_iso()
    run_date = row.get("run_date") or _run_date_from_now(now_value)
    image_urls = (
        row.get("image_urls")
        if isinstance(row.get("image_urls"), list)
        else parse_json(row.get("image_urls") or "[]", [])
    )
    offers = (
        row.get("offers")
        if isinstance(row.get("offers"), list)
        else parse_json(row.get("offers") or "[]", [])
    )
    if not isinstance(image_urls, list):
        image_urls = []
    if not isinstance(offers, list):
        offers = []

    offer = offers[0] if offers and isinstance(offers[0], dict) else {}
    raw_payload = (
        parse_json(row["raw_payload"], row["raw_payload"])
        if isinstance(row.get("raw_payload"), str)
        else (row.get("raw_payload") or {})
    )

    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": f"EL:{run_date}:{execution_id or 'manual'}",
        "run_date": run_date,
        "source_provider": "cj_dropshipping",
        "source_topic": row.get("source_topic"),
        "source_pick_rank": row.get("source_pick_rank"),
        "opportunity_score": row.get("opportunity_score"),
        "product_name": row.get("product_name"),
        "product_url": row.get("product_url"),
        "product_sku": row.get("product_sku"),
        "price_text": row.get("price_text"),
        "price_numeric": row.get("price_numeric"),
        "currency": row.get("currency") or "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": image_urls[0] if image_urls else None,
        "image_urls": _json_string(image_urls),
        "description": _truncate_description(row.get("description")),
        "supplier_name": offer.get("supplierName"),
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": _json_string({
            "source": "cj_dropshipping",
            "offer": offer,
            "raw_payload": raw_payload,
        }),
        "scraped_at": row.get("scraped_at") or now_value,
    }


def run(ctx: dict, *, now_iso: str | None = None, execution_id: str = "manual") -> dict:
    rows = []
    now_value = now_iso or _now_iso()
    for item in ctx.get("cj_top_products") or []:
        normalized = normalize_row(item, now_iso=now_value, execution_id=execution_id)
        if normalized is not None:
            rows.append(normalized)
    ctx["cj_review_items"] = rows
    log.info("Normalize CJ Review: normalized %d review candidates", len(rows))
    return ctx
