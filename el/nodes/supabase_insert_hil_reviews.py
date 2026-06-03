"""Port of n8n node `Supabase Insert (HIL Reviews)`."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from el import supabase
from el.logger import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    if not prepared.get("scraped_at"):
        prepared["scraped_at"] = _now_iso()
    return prepared


def run(ctx: dict, provider: supabase.SupabaseRestProvider | None = None) -> dict:
    source = ctx.get("hil_slate")
    if source is None:
        source = ctx.get("phase4_candidates") or []
    rows = [prepare_row(row) for row in source if isinstance(row, dict)]

    logging_event_id = ctx.get("logging_event_id") or ""
    if logging_event_id:
        for row in rows:
            row["logging_event_id"] = logging_event_id

    if not rows:
        ctx["hil_reviews_upsert_result"] = {"ok": True, "rows": 0, "data": []}
        log.info("Supabase Insert (HIL Reviews): no rows to upsert")
        return ctx

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        # ignore-duplicates: skip rows that already exist (reviewed or still-pending
        # from an earlier same-day run). merge-duplicates would reset approval_status
        # back to pending on already-reviewed rows, violating the coherence constraint.
        data = active_provider.upsert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.HIL_REVIEWS_TABLE,
            rows=rows,
            conflict_columns=supabase.HIL_REVIEWS_CONFLICT_COLUMNS,
            resolution="ignore-duplicates",
        )
    except Exception as exc:
        ctx["hil_reviews_upsert_result"] = {
            "ok": False,
            "rows": len(rows),
            "error": str(exc),
        }
        # Set empty list so upload_shopify_products knows HIL is active
        # but has no approved rows — prevents fallback to curated_picks.
        ctx["hil_review_rows"] = []
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
