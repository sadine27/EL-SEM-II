"""Port of n8n node `Sheet Append (Scraped)`."""
from __future__ import annotations

from datetime import datetime, timezone

from el import google_sheets
from el.logger import get_logger
from el.nodes.prepare_sheet_rows_scraped import SCRAPED_SHEET_ROW_COLUMNS

log = get_logger(__name__)


def _sheet_title(ctx: dict) -> str:
    title = (ctx.get("scraped_sheet_tab") or {}).get("title")
    if title:
        return title
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _default_provider() -> google_sheets.SheetsProvider:
    return google_sheets.GoogleSheetsProvider(
        spreadsheet_id=google_sheets.SCRAPED_SPREADSHEET_ID,
    )


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    rows = ctx.get("scraped_sheet_rows") or []
    title = _sheet_title(ctx)
    if not rows:
        ctx["scraped_sheet_append_result"] = {"sheet_title": title, "rows": 0, "ok": True}
        log.warning("Sheet Append (Scraped): no rows to append")
        return ctx

    p = provider or _default_provider()
    try:
        response = p.append_rows(title, rows, SCRAPED_SHEET_ROW_COLUMNS)
        ctx["scraped_sheet_append_result"] = {
            "sheet_title": title,
            "rows": len(rows),
            "ok": True,
            "response": response,
        }
        log.info("Sheet Append (Scraped): appended %d rows to %s", len(rows), title)
    except Exception as exc:
        ctx["scraped_sheet_append_result"] = {
            "sheet_title": title,
            "rows": len(rows),
            "ok": False,
            "error": str(exc),
        }
        log.warning("Sheet Append (Scraped) failed; continuing: %s", exc)
    return ctx
