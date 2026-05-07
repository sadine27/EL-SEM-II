"""Port of n8n node `Send HIL Telegram Text Fallback`."""
from __future__ import annotations

from el.logger import get_logger
from el.nodes.send_hil_telegram_photo import build_reply_markup
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def send_card(card: dict, provider: TelegramProvider) -> dict:
    response = provider.send_message(
        chat_id=str(card.get("telegram_chat_id") or ""),
        text=str(card.get("telegram_text") or ""),
        reply_markup=build_reply_markup(card),
        disable_web_page_preview=False,
    )
    return {**card, "telegram_text_response": response}


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    cards = [
        card for card in (ctx.get("telegram_text_fallback_cards") or []) if isinstance(card, dict)
    ]
    sent = []
    errors = []

    try:
        sender = provider or default_provider()
    except Exception as exc:  # noqa: BLE001 - node error output goes to Error Formatter in n8n.
        for card in cards:
            errors.append({**card, "telegram_text_error": str(exc)})
        ctx["telegram_text_fallback_sent"] = sent
        ctx["telegram_text_fallback_errors"] = errors
        ctx["send_hil_telegram_text_fallback_result"] = {
            "ok": False,
            "attempted": len(cards),
            "sent": 0,
            "errors": len(errors),
            "error": str(exc),
        }
        log.warning("Send HIL Telegram Text Fallback skipped: %s", exc)
        return ctx

    for card in cards:
        try:
            sent.append(send_card(card, sender))
        except Exception as exc:  # noqa: BLE001 - continueOnFail-style error collection.
            errors.append({**card, "telegram_text_error": str(exc)})

    ctx["telegram_text_fallback_sent"] = sent
    ctx["telegram_text_fallback_errors"] = errors
    ctx["send_hil_telegram_text_fallback_result"] = {
        "ok": not errors,
        "attempted": len(cards),
        "sent": len(sent),
        "errors": len(errors),
    }
    log.info("Send HIL Telegram Text Fallback: sent %d/%d", len(sent), len(cards))
    return ctx
