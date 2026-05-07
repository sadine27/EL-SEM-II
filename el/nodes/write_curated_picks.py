"""Port of n8n node `Write Curated Picks`."""
from __future__ import annotations

from el import google_sheets
from el.logger import get_logger
from el.nodes.create_curated_picks_tab import CURATED_PICKS_SHEET

log = get_logger(__name__)

CURATED_PICK_COLUMNS = (
    "run_date",
    "rank",
    "topic",
    "opportunity_score",
    "reason",
    "suggested_product_type",
    "target_audience",
    "search_query_in",
)


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    rows = ctx.get("curated_picks") or []
    if not rows:
        ctx["curated_picks_append_result"] = {
            "sheet_title": CURATED_PICKS_SHEET,
            "rows": 0,
            "ok": True,
        }
        log.warning("Write Curated Picks: no curated_picks to append")
        return ctx

    p = provider or google_sheets.default_provider()
    try:
        response = p.append_rows(CURATED_PICKS_SHEET, rows, CURATED_PICK_COLUMNS)
        ctx["curated_picks_append_result"] = {
            "sheet_title": CURATED_PICKS_SHEET,
            "rows": len(rows),
            "ok": True,
            "response": response,
        }
        log.info("Write Curated Picks: appended %d rows", len(rows))
    except Exception as exc:
        ctx["curated_picks_append_result"] = {
            "sheet_title": CURATED_PICKS_SHEET,
            "rows": len(rows),
            "ok": False,
            "error": str(exc),
        }
        log.warning("Write Curated Picks failed; continuing: %s", exc)
    return ctx
