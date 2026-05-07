"""Port of n8n node `Write Rows to Sheet`."""
from __future__ import annotations

from datetime import datetime, timezone

from el import google_sheets
from el.logger import get_logger
from el.nodes.prepare_sheet_rows import SHEET_ROW_COLUMNS

log = get_logger(__name__)


def _sheet_title(ctx: dict) -> str:
    title = (ctx.get("sheet_tab") or {}).get("title")
    if title:
        return title
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    rows = ctx.get("sheet_rows") or []
    title = _sheet_title(ctx)
    if not rows:
        ctx["sheet_append_result"] = {"sheet_title": title, "rows": 0, "ok": True}
        log.warning("Write Rows to Sheet: no sheet_rows to append")
        return ctx

    p = provider or google_sheets.default_provider()
    try:
        response = p.append_rows(title, rows, SHEET_ROW_COLUMNS)
        ctx["sheet_append_result"] = {
            "sheet_title": title,
            "rows": len(rows),
            "ok": True,
            "response": response,
        }
        log.info("Write Rows to Sheet: appended %d rows to %s", len(rows), title)
    except Exception as exc:
        ctx["sheet_append_result"] = {
            "sheet_title": title,
            "rows": len(rows),
            "ok": False,
            "error": str(exc),
        }
        log.warning("Write Rows to Sheet failed; continuing: %s", exc)
    return ctx
