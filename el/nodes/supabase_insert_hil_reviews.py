"""Port of n8n node `Supabase Insert (HIL Reviews)`."""
from __future__ import annotations

import json
from typing import Any

from el import supabase
from el.logger import get_logger

log = get_logger(__name__)


def _parse_json_field(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value if value is not None else fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def prepare_row(row: dict) -> dict:
    prepared = dict(row)
    prepared["image_urls"] = _parse_json_field(prepared.get("image_urls"), [])
    prepared["raw_payload"] = _parse_json_field(prepared.get("raw_payload"), {})
    return prepared


def run(ctx: dict, provider: supabase.SupabaseRestProvider | None = None) -> dict:
    rows = [prepare_row(row) for row in (ctx.get("phase4_candidates") or []) if isinstance(row, dict)]
    if not rows:
        ctx["hil_reviews_upsert_result"] = {"ok": True, "rows": 0, "data": []}
        log.info("Supabase Insert (HIL Reviews): no rows to upsert")
        return ctx

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        data = active_provider.upsert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.HIL_REVIEWS_TABLE,
            rows=rows,
            conflict_columns=supabase.HIL_REVIEWS_CONFLICT_COLUMNS,
        )
    except Exception as exc:
        ctx["hil_reviews_upsert_result"] = {
            "ok": False,
            "rows": len(rows),
            "error": str(exc),
        }
        log.exception("Supabase Insert (HIL Reviews) failed")
        return ctx

    ctx["hil_reviews_upsert_result"] = {
        "ok": True,
        "rows": len(rows),
        "data": data,
    }
    ctx["hil_review_rows"] = data
    log.info("Supabase Insert (HIL Reviews): upserted %d rows", len(rows))
    return ctx
