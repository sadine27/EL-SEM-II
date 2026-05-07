"""Port of n8n node `Create Day Tab (Scraped)`."""
from __future__ import annotations

from datetime import datetime, timezone

from el import google_sheets
from el.logger import get_logger

log = get_logger(__name__)


def _today_title() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _default_provider() -> google_sheets.SheetsProvider:
    return google_sheets.GoogleSheetsProvider(
        spreadsheet_id=google_sheets.SCRAPED_SPREADSHEET_ID,
    )


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    title = _today_title()
    p = provider or _default_provider()
    try:
        response = p.create_sheet(title)
        ctx["scraped_sheet_tab"] = {"title": title, "created": True, "response": response}
        log.info("Create Day Tab (Scraped): created %s", title)
    except Exception as exc:
        ctx["scraped_sheet_tab"] = {"title": title, "created": False, "error": str(exc)}
        log.warning("Create Day Tab (Scraped) failed; continuing: %s", exc)
    return ctx
