"""Port of n8n node `Merge Review Sources`."""
from __future__ import annotations

from el.logger import get_logger

log = get_logger(__name__)


def _items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def run(ctx: dict) -> dict:
    """Merge normalized review candidates from all supplier branches."""
    cj_items = _items(ctx.get("cj_review_items"))
    browserbase_items = _items(ctx.get("browserbase_review_items"))
    review_candidates = [*cj_items, *browserbase_items]
    ctx["review_candidates"] = review_candidates
    log.info(
        "Merge Review Sources: merged %d CJ and %d Browserbase candidates",
        len(cj_items),
        len(browserbase_items),
    )
    return ctx
