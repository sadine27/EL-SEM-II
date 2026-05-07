"""Tests for el/nodes/telegram_alert.py."""
from __future__ import annotations

from el.nodes import telegram_alert as ta


class FakeTelegramProvider:
    """Fake Telegram provider for testing."""

    def __init__(self, should_error: bool = False, response: dict | None = None):
        self.should_error = should_error
        self.response = response or {"ok": True, "result": {"message_id": 123}}
        self.calls = []

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        reply_markup: dict,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = False,
    ) -> dict:
        self.calls.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        })
        if self.should_error:
            raise Exception("Telegram API error")
        return self.response


def test_sends_alert_successfully():
    provider = FakeTelegramProvider()
    ctx = {
        "formatted_error": [
            {"text": "⚠️ *EL Node Failed*\n\n🔴 *Node:* `browserbase_fetch`"}
        ]
    }
    ta.run(ctx, provider=provider)
    result = ctx["telegram_alert_result"]
    assert result["ok"] is True
    assert provider.calls[0]["parse_mode"] == "Markdown"


def test_handles_provider_error():
    provider = FakeTelegramProvider(should_error=True)
    ctx = {
        "formatted_error": [
            {"text": "Error message"}
        ]
    }
    ta.run(ctx, provider=provider)
    result = ctx["telegram_alert_result"]
    assert result["ok"] is False
    assert "error" in result


def test_handles_missing_text():
    ctx = {
        "formatted_error": [
            {"text": ""}
        ]
    }
    ta.run(ctx, provider=FakeTelegramProvider())
    result = ctx["telegram_alert_result"]
    assert result["ok"] is False
    assert "Missing error text" in result["error"]


def test_preserves_context():
    provider = FakeTelegramProvider()
    ctx = {
        "formatted_error": [
            {"text": "Test error"}
        ],
        "other_key": "other_value",
    }
    ta.run(ctx, provider=provider)
    assert ctx["other_key"] == "other_value"
    assert "telegram_alert_result" in ctx
