"""Tests for el/nodes/parse_hil_callback.py."""
from __future__ import annotations

from el.nodes import parse_hil_callback


TOKEN = "123e4567-e89b-12d3-a456-426614174000"


def _update(data=f"a:42:{TOKEN}", **overrides) -> dict:
    update = {
        "callback_query": {
            "id": "cb-1",
            "data": data,
            "from": {
                "id": 99,
                "username": "reviewer",
                "first_name": "Review",
                "last_name": "User",
            },
            "message": {
                "message_id": 501,
                "chat": {"id": 8243518279},
                "photo": [{"file_id": "photo-1"}],
                "caption": "<b>Wireless Earbuds</b>",
            },
        }
    }
    update["callback_query"].update(overrides)
    return update


def test_parse_payload_accepts_valid_callback_payload():
    parsed = parse_hil_callback.parse_payload(f"r:123:{TOKEN.upper()}")

    assert parsed == {
        "valid": True,
        "action_code": "r",
        "review_id": "123",
        "callback_token": TOKEN,
    }


def test_parse_payload_rejects_invalid_callback_payload():
    parsed = parse_hil_callback.parse_payload("approve:42:not-a-token")

    assert parsed == {
        "valid": False,
        "action_code": "x",
        "review_id": "0",
        "callback_token": parse_hil_callback.ZERO_UUID,
    }


def test_sanitize_param_removes_sql_replacement_separators():
    assert parse_hil_callback.sanitize_param("a,b\n<c>", 20) == "a b c"


def test_actor_label_prefers_username_then_name_then_id():
    assert parse_hil_callback.actor_label({"username": "@reviewer"}) == "@reviewer"
    assert parse_hil_callback.actor_label({"first_name": "Review", "last_name": "User"}) == (
        "Review User"
    )
    assert parse_hil_callback.actor_label({"id": 99}) == "99"


def test_parse_update_maps_telegram_callback_fields():
    parsed = parse_hil_callback.parse_update(_update())

    assert parsed["callback_payload_valid"] is True
    assert parsed["action_code"] == "a"
    assert parsed["review_id"] == "42"
    assert parsed["callback_token"] == TOKEN
    assert parsed["callback_query_id"] == "cb-1"
    assert parsed["actor_id"] == "99"
    assert parsed["actor_label"] == "@reviewer"
    assert parsed["chat_id"] == "8243518279"
    assert parsed["message_id"] == "501"
    assert parsed["message_has_photo"] is True
    assert parsed["message_text_preview"] == "b Wireless Earbuds /b"


def test_parse_update_handles_text_messages_and_missing_photo():
    message = {
        "message_id": 502,
        "chat": {"id": 8243518279},
        "text": "Text fallback card",
    }
    parsed = parse_hil_callback.parse_update(_update(message=message))

    assert parsed["message_has_photo"] is False
    assert parsed["message_text_preview"] == "Text fallback card"


def test_run_stores_hil_callbacks():
    ctx = parse_hil_callback.run({"telegram_updates": [_update(), None, "bad"]})

    assert len(ctx["hil_callbacks"]) == 1
    assert ctx["hil_callbacks"][0]["review_id"] == "42"
