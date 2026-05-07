"""Port of n8n node `Prepare Sheet Rows (Scraped)`.

Flattens `ctx["cj_top_products"]` (output of `Pick Top 3`) into wide-format
rows for the scraped Google Sheet. Unpacks JSON-stringified `image_urls` and
`offers` and lifts the first offer's fields up to top-level columns.
"""
from __future__ import annotations

import json
from typing import Any

from el.logger import get_logger

log = get_logger(__name__)

SCRAPED_SHEET_ROW_COLUMNS = (
    "run_date",
    "source_pick_rank",
    "opportunity_score",
    "source_topic",
    "source_provider",
    "product_name",
    "product_url",
    "product_sku",
    "price_text",
    "price_numeric",
    "currency",
    "image_urls",
    "image_count",
    "listed_num",
    "supplier",
    "free_shipping",
    "shipping_countries",
    "category",
    "scraped_at",
)


def _parse_json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def run(ctx: dict) -> dict:
    rows: list[dict] = []
    for product in ctx.get("cj_top_products") or []:
        if not isinstance(product, dict):
            continue
        imgs = _parse_json_list(product.get("image_urls"))
        offers = _parse_json_list(product.get("offers"))
        offer = _safe_dict(offers[0]) if offers else {}
        rows.append({
            "run_date": product.get("run_date"),
            "source_pick_rank": product.get("source_pick_rank"),
            "opportunity_score": product.get("opportunity_score"),
            "source_topic": product.get("source_topic"),
            "source_provider": product.get("source_provider"),
            "product_name": product.get("product_name"),
            "product_url": product.get("product_url"),
            "product_sku": product.get("product_sku"),
            "price_text": product.get("price_text"),
            "price_numeric": product.get("price_numeric"),
            "currency": product.get("currency"),
            "image_urls": ", ".join(str(u) for u in imgs),
            "image_count": len(imgs),
            "listed_num": offer.get("listedNum", ""),
            "supplier": offer.get("supplierName", ""),
            "free_shipping": "YES" if offer.get("isFreeShipping") else "no",
            "shipping_countries": offer.get("shippingCountryCodes", ""),
            "category": offer.get("categoryName", ""),
            "scraped_at": product.get("scraped_at"),
        })
    log.info("Prepare Sheet Rows (Scraped): prepared %d rows", len(rows))
    ctx["scraped_sheet_rows"] = rows
    return ctx
