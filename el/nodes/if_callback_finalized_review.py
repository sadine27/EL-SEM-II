"""Port of n8n node `If Callback Finalized Review`."""
from __future__ import annotations

from el.logger import get_logger

log = get_logger(__name__)


def is_finalized(item: dict) -> bool:
    return item.get("message_should_finalize") is True


def run(ctx: dict) -> dict:
    answers = [item for item in (ctx.get("hil_callback_answers") or []) if isinstance(item, dict)]
    finalized = [item for item in answers if is_finalized(item)]
    not_finalized = [item for item in answers if not is_finalized(item)]
    ctx["hil_finalized_callbacks"] = finalized
    ctx["hil_non_finalized_callbacks"] = not_finalized
    ctx["if_callback_finalized_review_result"] = {
        "checked": len(answers),
        "finalized": len(finalized),
        "not_finalized": len(not_finalized),
    }
    log.info("If Callback Finalized Review: finalized %d/%d", len(finalized), len(answers))
    return ctx
