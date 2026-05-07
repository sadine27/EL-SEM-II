"""Port of n8n node `Answer HIL Callback`."""
from __future__ import annotations

from el.logger import get_logger
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def answer_result(result: dict, provider: TelegramProvider) -> dict:
    response = provider.answer_callback(
        callback_query_id=str(result.get("callback_query_id") or ""),
        text=str(result.get("callback_answer_text") or ""),
        show_alert=False,
        cache_time=0,
    )
    return {**result, "telegram_callback_answer_response": response}


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    results = [item for item in (ctx.get("hil_callback_results") or []) if isinstance(item, dict)]
    answered = []
    errors = []

    try:
        sender = provider or default_provider()
    except Exception as exc:  # noqa: BLE001 - n8n node failure routes to workflow error handling.
        for result in results:
            errors.append({**result, "answer_hil_callback_error": str(exc)})
        ctx["hil_callback_answers"] = answered
        ctx["answer_hil_callback_errors"] = errors
        ctx["answer_hil_callback_result"] = {
            "ok": False,
            "attempted": len(results),
            "answered": 0,
            "errors": len(errors),
            "error": str(exc),
        }
        log.warning("Answer HIL Callback skipped: %s", exc)
        return ctx

    for result in results:
        try:
            answered.append(answer_result(result, sender))
        except Exception as exc:  # noqa: BLE001 - collect failures for caller/error formatter.
            errors.append({**result, "answer_hil_callback_error": str(exc)})

    ctx["hil_callback_answers"] = answered
    ctx["answer_hil_callback_errors"] = errors
    ctx["answer_hil_callback_result"] = {
        "ok": not errors,
        "attempted": len(results),
        "answered": len(answered),
        "errors": len(errors),
    }
    log.info("Answer HIL Callback: answered %d/%d callbacks", len(answered), len(results))
    return ctx
