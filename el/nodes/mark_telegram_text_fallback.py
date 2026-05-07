"""Port of n8n node `Mark Telegram Text Fallback`."""
from __future__ import annotations

from datetime import datetime, timezone

from el.logger import get_logger
from el.nodes.mark_telegram_photo_sent import HilReviewUpdateProvider
from el.supabase import HIL_REVIEWS_SCHEMA, HIL_REVIEWS_TABLE, SupabaseRestProvider

log = get_logger(__name__)


def _telegram_result(card: dict) -> dict:
    response = card.get("telegram_text_response") or {}
    result = response.get("result") or {}
    return result if isinstance(result, dict) else {}


def build_update(card: dict, *, sent_at: datetime | None = None) -> dict:
    result = _telegram_result(card)
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    chat_id = chat.get("id")
    message_id = result.get("message_id")
    if chat_id is None or message_id is None:
        raise ValueError("Telegram text response is missing chat.id or message_id")

    ts = (sent_at or datetime.now(timezone.utc)).isoformat()
    return {
        "telegram_chat_id": int(chat_id),
        "telegram_message_id": int(message_id),
        "telegram_media_status": "text_only",
        "telegram_sent_at": ts,
        "updated_at": ts,
    }


def mark_card(card: dict, provider: HilReviewUpdateProvider) -> dict:
    review_id = card.get("review_id") or card.get("id")
    if review_id is None:
        raise ValueError("review_id is missing")
    updates = build_update(card)
    rows = provider.update_row_by_id(
        schema=HIL_REVIEWS_SCHEMA,
        table=HIL_REVIEWS_TABLE,
        row_id=review_id,
        updates=updates,
    )
    return {**card, "telegram_text_mark_result": rows}


def run(ctx: dict, *, provider: HilReviewUpdateProvider | None = None) -> dict:
    cards = [
        card for card in (ctx.get("telegram_text_fallback_sent") or []) if isinstance(card, dict)
    ]
    updater = provider or SupabaseRestProvider()
    marked = []
    errors = []

    for card in cards:
        try:
            marked.append(mark_card(card, updater))
        except Exception as exc:  # noqa: BLE001 - n8n node is continueOnFail.
            errors.append({**card, "mark_telegram_text_fallback_error": str(exc)})

    ctx["telegram_text_fallback_marked"] = marked
    ctx["mark_telegram_text_fallback_errors"] = errors
    ctx["mark_telegram_text_fallback_result"] = {
        "ok": not errors,
        "attempted": len(cards),
        "marked": len(marked),
        "errors": len(errors),
    }
    log.info("Mark Telegram Text Fallback: marked %d/%d", len(marked), len(cards))
    return ctx
