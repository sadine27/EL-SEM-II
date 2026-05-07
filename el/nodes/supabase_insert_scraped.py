"""Port of n8n node `Supabase Insert (Scraped)`.

Upserts `ctx["cj_top_products"]` into `public.scraped_products` with conflict
resolution on (`product_url`, `source_topic`).
"""
from __future__ import annotations

import json
from typing import Any

from el import supabase
from el.logger import get_logger

log = get_logger(__name__)

SCRAPED_PRODUCTS_SCHEMA = "public"
SCRAPED_PRODUCTS_TABLE = "scraped_products"
SCRAPED_PRODUCTS_CONFLICT_COLUMNS = ("product_url", "source_topic")


def _parse_json_field(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def prepare_row(row: dict) -> dict:
    prepared = dict(row)
    prepared["image_urls"] = _parse_json_field(prepared.get("image_urls"), [])
    prepared["offers"] = _parse_json_field(prepared.get("offers"), [])
    prepared["raw_payload"] = _parse_json_field(prepared.get("raw_payload"), {})
    return prepared


def run(ctx: dict, provider: supabase.SupabaseRestProvider | None = None) -> dict:
    rows = [
        prepare_row(row)
        for row in (ctx.get("cj_top_products") or [])
        if isinstance(row, dict)
    ]
    if not rows:
        ctx["scraped_upsert_result"] = {"ok": True, "rows": 0, "data": []}
        log.info("Supabase Insert (Scraped): no rows to upsert")
        return ctx

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        data = active_provider.upsert_rows(
            schema=SCRAPED_PRODUCTS_SCHEMA,
            table=SCRAPED_PRODUCTS_TABLE,
            rows=rows,
            conflict_columns=SCRAPED_PRODUCTS_CONFLICT_COLUMNS,
        )
    except Exception as exc:
        ctx["scraped_upsert_result"] = {
            "ok": False,
            "rows": len(rows),
            "error": str(exc),
        }
        log.exception("Supabase Insert (Scraped) failed")
        return ctx

    ctx["scraped_upsert_result"] = {"ok": True, "rows": len(rows), "data": data}
    log.info("Supabase Insert (Scraped): upserted %d rows", len(rows))
    return ctx
