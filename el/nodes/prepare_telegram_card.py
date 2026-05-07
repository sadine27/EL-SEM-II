"""Port of n8n node `Prepare Telegram Card`."""
from __future__ import annotations

import html
import json

from el import config
from el.logger import get_logger

log = get_logger(__name__)

DEFAULT_CHAT_ID = "8243518279"
MAX_CAPTION_LENGTH = 900


def compact(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def truncate(value: object, max_length: int) -> str:
    text = compact(value)
    return text[: max_length - 3] + "..." if len(text) > max_length else text


def escape_html(value: object) -> str:
    return html.escape(compact(value), quote=True)


def _raw_payload(row: dict) -> dict:
    raw = row.get("raw_payload") or {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def money(row: dict) -> str:
    price_text = compact(row.get("price_text"))
    if price_text:
        return price_text
    try:
        numeric = float(row.get("price_numeric"))
    except (TypeError, ValueError):
        return "price n/a"
    currency = compact(row.get("currency")).upper()
    if currency == "INR":
        return f"INR {numeric:g}"
    return f"{numeric:g} {currency}" if currency else f"{numeric:g}"


def rating(row: dict) -> str:
    try:
        value = float(row.get("product_rating"))
    except (TypeError, ValueError):
        return "rating n/a"
    try:
        reviews = float(row.get("reviews_count"))
    except (TypeError, ValueError):
        reviews = None
    value_text = f"{value:g}/5"
    return f"{value_text} ({reviews:g})" if reviews is not None else value_text


def source(row: dict) -> str:
    return compact(row.get("marketplace") or row.get("source_provider") or "source n/a")


def build_callback(action: str, row: dict) -> str:
    payload = f"{action}:{row.get('id')}:{row.get('callback_token')}"
    if len(payload.encode("utf-8")) > 64:
        raise ValueError(f"Telegram callback payload is over 64 bytes for review {row.get('id')}")
    return payload


def build_caption(row: dict) -> str:
    raw_payload = _raw_payload(row)
    score = (
        ((raw_payload.get("phase4_selection") or {}).get("confidence_score"))
        if isinstance(raw_payload.get("phase4_selection"), dict)
        else None
    )
    if score is None and isinstance(raw_payload.get("phase4_debug"), dict):
        score = raw_payload["phase4_debug"].get("score")
    score_text = "" if score is None else f"\nScore: <b>{escape_html(score)}</b>"
    lines = [
        f"<b>{escape_html(truncate(row.get('product_name'), 140))}</b>",
        f"Price: <b>{escape_html(money(row))}</b>",
        f"Rating: {escape_html(rating(row))}",
        f"Source: {escape_html(source(row))}",
        f"Topic: {escape_html(truncate(row.get('source_topic'), 120))}",
        score_text.strip(),
    ]
    return truncate("\n".join(line for line in lines if line), MAX_CAPTION_LENGTH)


def build_card(row: dict, *, chat_id: str | None = None) -> dict:
    caption = build_caption(row)
    review_id = row.get("id")
    return {
        **row,
        "review_id": review_id,
        "telegram_chat_id": chat_id or config.get("TELEGRAM_HIL_CHAT_ID") or DEFAULT_CHAT_ID,
        "telegram_caption": caption,
        "telegram_text": caption + "\n\nImage unavailable: sending text card.",
        "telegram_file_name": f"hil-review-{review_id or 'item'}.jpg",
        "telegram_approve_callback": build_callback("a", row),
        "telegram_reject_callback": build_callback("r", row),
        "telegram_skip_callback": build_callback("s", row),
        "image_url": compact(row.get("image_url")),
    }


def run(ctx: dict, *, chat_id: str | None = None) -> dict:
    rows = [row for row in (ctx.get("hil_review_rows") or []) if isinstance(row, dict)]
    cards = [build_card(row, chat_id=chat_id) for row in rows]
    ctx["telegram_cards"] = cards
    log.info("Prepare Telegram Card: prepared %d cards", len(cards))
    return ctx
