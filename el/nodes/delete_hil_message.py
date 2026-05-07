"""Port of n8n node `Delete HIL Review Message After Edit Failure`."""
from __future__ import annotations

from el.logger import get_logger
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    if not ctx.get("message_edit_failed"):
        ctx["delete_hil_message_result"] = {"ok": True, "skipped": True}
        log.info("Delete HIL Message: skipped (message edit succeeded)")
        return ctx

    callback_data = ctx.get("hil_finalized_callbacks") or {}
    if not isinstance(callback_data, dict):
        callback_data = {}
    chat_id = callback_data.get("chat_id")
    message_id = callback_data.get("message_id")

    if not all([chat_id, message_id]):
        ctx["delete_hil_message_result"] = {
            "ok": False,
            "error": "Missing chat_id or message_id",
        }
        log.warning("Delete HIL Message skipped: missing required fields")
        return ctx

    try:
        sender = provider or default_provider()
    except Exception as exc:  # noqa: BLE001
        ctx["delete_hil_message_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.warning("Delete HIL Message skipped: %s", exc)
        return ctx

    try:
        response = sender.delete_message(
            chat_id=str(chat_id),
            message_id=int(message_id),
        )
        ctx["delete_hil_message_response"] = response
        ctx["delete_hil_message_result"] = {"ok": True}
        log.info("Delete HIL Message: deleted message %s in chat %s", message_id, chat_id)
    except Exception as exc:  # noqa: BLE001
        ctx["delete_hil_message_error"] = str(exc)
        ctx["delete_hil_message_result"] = {
            "ok": False,
            "error": str(exc),
        }
        log.error("Delete HIL Message failed: %s", exc)

    return ctx
