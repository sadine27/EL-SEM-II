"""Port of n8n node `Send HIL Telegram Photo`."""
from __future__ import annotations

from el.logger import get_logger
from el.telegram import TelegramProvider, default_provider

log = get_logger(__name__)


def build_reply_markup(card: dict) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": card.get("telegram_approve_callback")},
                {"text": "Reject", "callback_data": card.get("telegram_reject_callback")},
                {"text": "Skip", "callback_data": card.get("telegram_skip_callback")},
            ],
            [{"text": "Open Product", "url": card.get("product_url")}],
        ]
    }


def send_card(card: dict, provider: TelegramProvider) -> dict:
    response = provider.send_photo(
        chat_id=str(card.get("telegram_chat_id") or ""),
        photo=card.get("product_image") or {},
        caption=str(card.get("telegram_caption") or ""),
        file_name=str(card.get("telegram_file_name") or "hil-review-item.jpg"),
        reply_markup=build_reply_markup(card),
    )
    return {**card, "telegram_photo_response": response}


def run(ctx: dict, *, provider: TelegramProvider | None = None) -> dict:
    cards = [card for card in (ctx.get("telegram_photo_cards") or []) if isinstance(card, dict)]
    sent = []
    fallback_cards = [
        card for card in (ctx.get("telegram_text_fallback_cards") or []) if isinstance(card, dict)
    ]

    try:
        sender = provider or default_provider()
    except Exception as exc:  # noqa: BLE001 - node-level credential failures route to fallback.
        for card in cards:
            fallback_cards.append({**card, "telegram_photo_error": str(exc)})
        ctx["telegram_photo_sent"] = sent
        ctx["telegram_text_fallback_cards"] = fallback_cards
        ctx["send_hil_telegram_photo_result"] = {
            "ok": False,
            "attempted": len(cards),
            "sent": 0,
            "fallback": len(cards),
            "error": str(exc),
        }
        log.warning("Send HIL Telegram Photo skipped: %s", exc)
        return ctx

    for card in cards:
        try:
            sent.append(send_card(card, sender))
        except Exception as exc:  # noqa: BLE001 - n8n routes sendPhoto errors to text fallback.
            fallback_cards.append({**card, "telegram_photo_error": str(exc)})

    ctx["telegram_photo_sent"] = sent
    ctx["telegram_text_fallback_cards"] = fallback_cards
    ctx["send_hil_telegram_photo_result"] = {
        "ok": True,
        "attempted": len(cards),
        "sent": len(sent),
        "fallback": len(fallback_cards),
    }
    log.info("Send HIL Telegram Photo: sent %d/%d", len(sent), len(cards))
    return ctx
