"""Port of n8n node `Create Day Tab`."""
from __future__ import annotations

from datetime import datetime, timezone

from el import google_sheets
from el.logger import get_logger

log = get_logger(__name__)


def _today_title() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    title = _today_title()
    p = provider or google_sheets.default_provider()
    try:
        response = p.create_sheet(title)
        ctx["sheet_tab"] = {"title": title, "created": True, "response": response}
        log.info("Create Day Tab: created %s", title)
    except Exception as exc:
        body = getattr(getattr(exc, "response", None), "text", "") or ""
        if "already exists" in body or "already exists" in str(exc):
            ctx["sheet_tab"] = {"title": title, "created": False, "existed": True}
            log.info("Create Day Tab: %s already exists, reusing", title)
        else:
            ctx["sheet_tab"] = {"title": title, "created": False, "error": str(exc)}
            log.warning("Create Day Tab failed; continuing: %s", exc)
    return ctx
