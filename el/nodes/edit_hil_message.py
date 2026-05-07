"""Port of n8n node `Edit HIL Review Message`."""
from __future__ import annotations

from el.logger import get_logger
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    callback_data = ctx.get("hil_finalized_callbacks") or {}
    chat_id = callback_data.get("chat_id")
    message_id = callback_data.get("message_id")
    text = callback_data.get("telegram_edit_text")

    if not all([chat_id, message_id, text]):
        ctx["edit_hil_message_result"] = {
            "ok": False,
            "error": "Missing chat_id, message_id, or telegram_edit_text",
        }
        log.warning("Edit HIL Message skipped: missing required fields")
        return ctx

    try:
        sender = provider or default_provider()
    except Exception as exc:  # noqa: BLE001
        ctx["edit_hil_message_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.warning("Edit HIL Message skipped: %s", exc)
        return ctx

    try:
        response = sender.edit_message_text(
            chat_id=str(chat_id),
            message_id=int(message_id),
            text=str(text),
            disable_web_page_preview=True,
        )
        ctx["edit_hil_message_response"] = response
        ctx["edit_hil_message_result"] = {"ok": True}
        log.info("Edit HIL Message: edited message %s in chat %s", message_id, chat_id)
    except Exception as exc:  # noqa: BLE001
        ctx["edit_hil_message_error"] = str(exc)
        ctx["edit_hil_message_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.error("Edit HIL Message failed: %s", exc)
        ctx["message_edit_failed"] = True

    return ctx
