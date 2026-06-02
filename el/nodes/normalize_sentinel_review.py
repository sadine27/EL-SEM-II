"""Convert Sentinel's passing matches into HIL review rows (the `hil_v1` contract).

This is the bridge that lets Sentinel-vetted products join the human-in-the-loop
approval queue. It mirrors ``normalize_cj_review``: each *passing* match from
``ctx["sentinel_matches"]`` becomes a review row in the same shape
``phase4_candidate_selection`` consumes, tagged ``source_provider="forge_sentinel"``
so it merges alongside CJ candidates rather than replacing them.

Reads ``ctx["sentinel_matches"]``; writes ``ctx["sentinel_review_items"]``. Only
matches with ``sentinel_decision == "pass"`` are normalized — rejects are dropped.

Scoring note: ``phase4`` reads ``opportunity_score`` on a **0..10** scale
(``clamp(opportunity, 0, 10) * 6``), so the 0..1 ``sentinel_score`` is mapped
``× 10`` — a 0.62 vetting score becomes opportunity 6.2, comfortably clearing the
phase-4 ``MIN_SCORE`` threshold.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)

SOURCE_PROVIDER = "forge_sentinel"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_string(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def _availability(stock) -> str:
    if stock is None:
        return "unknown"
    try:
        return "in_stock" if int(stock) > 0 else "out_of_stock"
    except (TypeError, ValueError):
        return "unknown"


def normalize_row(
    match: dict,
    query: str | None,
    *,
    rank: int | None = None,
    now_iso: str | None = None,
    execution_id: str = "manual",
) -> dict | None:
    """Normalize one passing Sentinel match into the HIL review contract."""
    title = (match.get("title") or "").strip()
    product_url = (match.get("product_url") or "").strip()
    topic = (query or "").strip()
    if not title or not product_url or not topic:
        return None

    now_value = now_iso or _now_iso()
    run_date = now_value[:10]
    score = match.get("sentinel_score")
    # phase4 reads opportunity on a 0..10 scale (×6); sentinel_score is 0..1.
    opportunity = round((score or 0.0) * 10, 2)
    price = match.get("projected_sell_price")
    if price is None:
        price = match.get("landed_cost")
    image_url = match.get("image_url")
    image_urls = [image_url] if image_url else []

    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": f"EL:{run_date}:{execution_id or 'manual'}",
        "run_date": run_date,
        "source_provider": SOURCE_PROVIDER,
        "source_topic": topic,
        "source_pick_rank": rank,
        "opportunity_score": opportunity,
        "product_name": title,
        "product_url": product_url,
        "product_sku": match.get("supplier_product_id"),
        "price_text": None,
        "price_numeric": price,
        "currency": match.get("currency") or "USD",
        "product_rating": match.get("rating"),
        "reviews_count": None,
        "image_url": image_url,
        "image_urls": _json_string(image_urls),
        "description": None,
        "supplier_name": match.get("source_id"),
        "marketplace": match.get("source_id"),
        "availability_status": _availability(match.get("stock")),
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": _json_string({
            "source": SOURCE_PROVIDER,
            "supplier_source": match.get("source_id"),
            "sentinel_score": score,
            "sentinel_warnings": match.get("sentinel_warnings"),
            "projected_sell_price": match.get("projected_sell_price"),
            "projected_margin_pct": match.get("projected_margin_pct"),
            "landed_cost": match.get("landed_cost"),
        }),
        "scraped_at": now_value,
    }


def run(ctx: dict, *, now_iso: str | None = None, execution_id: str = "manual") -> dict:
    rows: list[dict] = []
    now_value = now_iso or _now_iso()
    for group in ctx.get("sentinel_matches") or []:
        query = group.get("query") or (group.get("trend") or {}).get("topic")
        for rank, match in enumerate(group.get("matches") or [], start=1):
            if not isinstance(match, dict) or match.get("sentinel_decision") != "pass":
                continue
            normalized = normalize_row(
                match, query, rank=rank, now_iso=now_value, execution_id=execution_id,
            )
            if normalized is not None:
                rows.append(normalized)
    ctx["sentinel_review_items"] = rows
    log.info("Normalize Sentinel Review: normalized %d review candidates", len(rows))
    return ctx
