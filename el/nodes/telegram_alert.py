"""Send formatted error alert to Telegram."""
from __future__ import annotations

from el import config
from el.telegram import TelegramProvider, TelegramBotProvider


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    """Send formatted error to Telegram personal chat.

    Input: ctx["formatted_error"] — list of items with "text" field
    Output: ctx["telegram_alert_result"] — result dict with ok/error fields
    """
    result = {"ok": False, "error": "No alert to send"}

    if not ctx.get("formatted_error"):
        ctx["telegram_alert_result"] = result
        return ctx

    formatted_error = ctx["formatted_error"][0]
    text = formatted_error.get("text", "")

    if not text:
        result["error"] = "Missing error text"
        ctx["telegram_alert_result"] = result
        return ctx

    chat_id = config.get("TELEGRAM_ALERT_CHAT_ID", "8243518279")

    # Use provided provider or create default
    if provider is None:
        provider = TelegramBotProvider()

    try:
        alert_result = provider.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup={},
            parse_mode="Markdown",
        )
        ctx["telegram_alert_result"] = alert_result
    except Exception as e:
        error_result = {
            "ok": False,
            "error": str(e),
        }
        ctx["telegram_alert_result"] = error_result

    return ctx
