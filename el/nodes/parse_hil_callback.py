"""Port of n8n node `Parse HIL Callback`."""
from __future__ import annotations

import re

from el.logger import get_logger

log = get_logger(__name__)

ZERO_UUID = "00000000-0000-0000-0000-000000000000"
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def compact(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def sanitize_param(value: object, max_length: int = 120) -> str:
    text = compact(value)
    text = re.sub(r"[,\r\n<>]", " ", text)
    return " ".join(text.split())[:max_length]


def actor_label(user: dict | None) -> str:
    if not isinstance(user, dict):
        return ""
    username = user.get("username")
    if username:
        return "@" + sanitize_param(username, 64).lstrip("@")
    name = sanitize_param(" ".join(str(part) for part in [user.get("first_name"), user.get("last_name")] if part), 80)
    return name or sanitize_param(user.get("id"), 40)


def parse_payload(data: object) -> dict:
    parts = compact(data).split(":")
    valid = (
        len(parts) == 3
        and re.fullmatch(r"[ars]", parts[0]) is not None
        and re.fullmatch(r"\d{1,19}", parts[1]) is not None
        and UUID_RE.fullmatch(parts[2]) is not None
    )
    return {
        "valid": valid,
        "action_code": parts[0] if valid else "x",
        "review_id": parts[1] if valid else "0",
        "callback_token": parts[2].lower() if valid else ZERO_UUID,
    }


def parse_update(update: dict) -> dict:
    callback = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else {}
    from_user = callback.get("from") if isinstance(callback.get("from"), dict) else {}
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    parsed = parse_payload(callback.get("data"))
    callback_data = sanitize_param(callback.get("data"), 80)
    return {
        **parsed,
        "callback_payload_valid": parsed["valid"],
        "callback_query_id": sanitize_param(callback.get("id"), 120),
        "callback_data": callback_data,
        "actor_id": sanitize_param(from_user.get("id"), 40),
        "actor_label": actor_label(from_user),
        "chat_id": sanitize_param(chat.get("id"), 40),
        "message_id": sanitize_param(message.get("message_id"), 40),
        "message_has_photo": isinstance(message.get("photo"), list) and len(message.get("photo")) > 0,
        "message_text_preview": sanitize_param(message.get("text") or message.get("caption") or "", 180),
    }


def run(ctx: dict) -> dict:
    updates = [
        update
        for update in (ctx.get("telegram_updates") or ctx.get("telegram_trigger_updates") or [])
        if isinstance(update, dict)
    ]
    callbacks = [parse_update(update) for update in updates]
    ctx["hil_callbacks"] = callbacks
    log.info("Parse HIL Callback: parsed %d updates", len(callbacks))
    return ctx
