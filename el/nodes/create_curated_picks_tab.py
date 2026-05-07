"""Port of n8n node `Create Curated Picks Tab`."""
from __future__ import annotations

from el import google_sheets
from el.logger import get_logger

log = get_logger(__name__)

CURATED_PICKS_SHEET = "Curated Picks"


def run(ctx: dict, provider: google_sheets.SheetsProvider | None = None) -> dict:
    p = provider or google_sheets.default_provider()
    try:
        response = p.create_sheet(CURATED_PICKS_SHEET)
        ctx["curated_picks_tab"] = {
            "title": CURATED_PICKS_SHEET,
            "created": True,
            "response": response,
        }
        log.info("Create Curated Picks Tab: created %s", CURATED_PICKS_SHEET)
    except Exception as exc:
        ctx["curated_picks_tab"] = {
            "title": CURATED_PICKS_SHEET,
            "created": False,
            "error": str(exc),
        }
        log.warning("Create Curated Picks Tab failed; continuing: %s", exc)
    return ctx
