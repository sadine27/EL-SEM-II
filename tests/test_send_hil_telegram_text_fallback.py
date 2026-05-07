"""Tests for el/nodes/send_hil_telegram_text_fallback.py."""
from __future__ import annotations

from el.nodes import send_hil_telegram_text_fallback


class FakeTelegramProvider:
    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls = []

    def send_message(self, *, chat_id, text, reply_markup, disable_web_page_preview=False):
        self.calls.append({
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "disable_web_page_preview": disable_web_page_preview,
        })
        if chat_id in self.fail_ids:
            raise RuntimeError("telegram text failed")
        return {"ok": True, "result": {"chat": {"id": int(chat_id)}, "message_id": 601}}


def _card(**overrides) -> dict:
    card = {
        "review_id": 42,
        "telegram_chat_id": "8243518279",
        "telegram_text": "<b>Wireless Earbuds</b>\n\nImage unavailable: sending text card.",
        "telegram_approve_callback": "a:42:123e4567-e89b-12d3-a456-426614174000",
        "telegram_reject_callback": "r:42:123e4567-e89b-12d3-a456-426614174000",
        "telegram_skip_callback": "s:42:123e4567-e89b-12d3-a456-426614174000",
        "product_url": "https://example.com/product",
    }
    card.update(overrides)
    return card


def test_send_card_calls_provider_with_text_fallback_fields():
    provider = FakeTelegramProvider()
    sent = send_hil_telegram_text_fallback.send_card(_card(), provider)

    assert provider.calls[0]["chat_id"] == "8243518279"
    assert provider.calls[0]["text"].endswith("Image unavailable: sending text card.")
    assert provider.calls[0]["disable_web_page_preview"] is False
    assert provider.calls[0]["reply_markup"]["inline_keyboard"][1][0]["text"] == "Open Product"
    assert sent["telegram_text_response"]["result"]["message_id"] == 601


def test_run_sends_fallback_cards():
    provider = FakeTelegramProvider()
    ctx = send_hil_telegram_text_fallback.run(
        {"telegram_text_fallback_cards": [_card()]},
        provider=provider,
    )

    assert len(ctx["telegram_text_fallback_sent"]) == 1
    assert ctx["telegram_text_fallback_errors"] == []
    assert ctx["send_hil_telegram_text_fallback_result"] == {
        "ok": True,
        "attempted": 1,
        "sent": 1,
        "errors": 0,
    }


def test_run_collects_text_send_errors():
    provider = FakeTelegramProvider(fail_ids={"8243518279"})
    ctx = send_hil_telegram_text_fallback.run(
        {"telegram_text_fallback_cards": [_card()]},
        provider=provider,
    )

    assert ctx["telegram_text_fallback_sent"] == []
    assert len(ctx["telegram_text_fallback_errors"]) == 1
    assert ctx["telegram_text_fallback_errors"][0]["telegram_text_error"] == "telegram text failed"
    assert ctx["send_hil_telegram_text_fallback_result"] == {
        "ok": False,
        "attempted": 1,
        "sent": 0,
        "errors": 1,
    }


def test_run_ignores_non_dict_cards():
    provider = FakeTelegramProvider()
    ctx = send_hil_telegram_text_fallback.run(
        {"telegram_text_fallback_cards": [_card(), None, "bad"]},
        provider=provider,
    )

    assert len(ctx["telegram_text_fallback_sent"]) == 1
    assert ctx["send_hil_telegram_text_fallback_result"]["attempted"] == 1
