"""Tests for el/nodes/send_hil_telegram_photo.py."""
from __future__ import annotations

from el.nodes import send_hil_telegram_photo


class FakeTelegramProvider:
    def __init__(self, fail_ids: set[int] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls = []

    def send_photo(self, *, chat_id, photo, caption, file_name, reply_markup):
        self.calls.append({
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption,
            "file_name": file_name,
            "reply_markup": reply_markup,
        })
        if chat_id in self.fail_ids:
            raise RuntimeError("telegram send failed")
        return {"ok": True, "result": {"chat": {"id": int(chat_id)}, "message_id": 501}}


def _card(**overrides) -> dict:
    card = {
        "review_id": 42,
        "telegram_chat_id": "8243518279",
        "telegram_caption": "<b>Wireless Earbuds</b>",
        "telegram_file_name": "hil-review-42.jpg",
        "telegram_approve_callback": "a:42:123e4567-e89b-12d3-a456-426614174000",
        "telegram_reject_callback": "r:42:123e4567-e89b-12d3-a456-426614174000",
        "telegram_skip_callback": "s:42:123e4567-e89b-12d3-a456-426614174000",
        "product_url": "https://example.com/product",
        "product_image": {
            "data": b"image-bytes",
            "mimeType": "image/jpeg",
            "fileName": "hil-review-42.jpg",
        },
    }
    card.update(overrides)
    return card


def test_build_reply_markup_matches_n8n_inline_keyboard_shape():
    markup = send_hil_telegram_photo.build_reply_markup(_card())

    assert markup["inline_keyboard"][0][0] == {
        "text": "Approve",
        "callback_data": "a:42:123e4567-e89b-12d3-a456-426614174000",
    }
    assert markup["inline_keyboard"][0][1]["text"] == "Reject"
    assert markup["inline_keyboard"][0][2]["text"] == "Skip"
    assert markup["inline_keyboard"][1][0] == {
        "text": "Open Product",
        "url": "https://example.com/product",
    }


def test_send_card_calls_provider_and_attaches_response():
    provider = FakeTelegramProvider()
    sent = send_hil_telegram_photo.send_card(_card(), provider)

    assert provider.calls[0]["chat_id"] == "8243518279"
    assert provider.calls[0]["photo"]["data"] == b"image-bytes"
    assert provider.calls[0]["caption"] == "<b>Wireless Earbuds</b>"
    assert sent["telegram_photo_response"]["result"]["message_id"] == 501


def test_run_routes_successful_photo_sends_to_photo_sent():
    provider = FakeTelegramProvider()
    ctx = send_hil_telegram_photo.run({"telegram_photo_cards": [_card()]}, provider=provider)

    assert len(ctx["telegram_photo_sent"]) == 1
    assert ctx["telegram_text_fallback_cards"] == []
    assert ctx["send_hil_telegram_photo_result"] == {
        "ok": True,
        "attempted": 1,
        "sent": 1,
        "fallback": 0,
    }


def test_run_routes_failed_photo_sends_to_text_fallback():
    provider = FakeTelegramProvider(fail_ids={"8243518279"})
    ctx = send_hil_telegram_photo.run({"telegram_photo_cards": [_card()]}, provider=provider)

    assert ctx["telegram_photo_sent"] == []
    assert len(ctx["telegram_text_fallback_cards"]) == 1
    assert ctx["telegram_text_fallback_cards"][0]["telegram_photo_error"] == "telegram send failed"
    assert ctx["send_hil_telegram_photo_result"]["fallback"] == 1


def test_run_preserves_existing_download_fallback_cards():
    provider = FakeTelegramProvider()
    existing = {"review_id": 1, "image_download_error": "download failed"}
    ctx = send_hil_telegram_photo.run(
        {
            "telegram_photo_cards": [_card()],
            "telegram_text_fallback_cards": [existing],
        },
        provider=provider,
    )

    assert ctx["telegram_text_fallback_cards"] == [existing]
    assert ctx["send_hil_telegram_photo_result"]["fallback"] == 1
