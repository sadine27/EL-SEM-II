"""Tests for el/nodes/delete_hil_message.py."""
from __future__ import annotations

from el.nodes import delete_hil_message as dhm


class FakeTelegramProvider:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"ok": True}
        self.error = error
        self.calls: list[tuple] = []

    def delete_message(
        self,
        *,
        chat_id: str,
        message_id: int,
    ) -> dict:
        self.calls.append(("delete_message", chat_id, message_id))
        if self.error:
            raise self.error
        return self.response


def test_delete_hil_message_skipped_on_success():
    fake = FakeTelegramProvider()
    ctx = {
        "hil_finalized_callbacks": {
            "chat_id": "12345",
            "message_id": "999",
        },
    }
    dhm.run(ctx, provider=fake)
    assert ctx["delete_hil_message_result"]["ok"] is True
    assert ctx["delete_hil_message_result"].get("skipped") is True
    assert len(fake.calls) == 0


def test_delete_hil_message_on_edit_failure():
    fake = FakeTelegramProvider()
    ctx = {
        "message_edit_failed": True,
        "hil_finalized_callbacks": {
            "chat_id": "12345",
            "message_id": "999",
        },
    }
    dhm.run(ctx, provider=fake)
    assert ctx["delete_hil_message_result"]["ok"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0] == ("delete_message", "12345", 999)


def test_delete_hil_message_missing_chat_id():
    fake = FakeTelegramProvider()
    ctx = {
        "message_edit_failed": True,
        "hil_finalized_callbacks": {
            "message_id": "999",
        },
    }
    dhm.run(ctx, provider=fake)
    assert ctx["delete_hil_message_result"]["ok"] is False
    assert "Missing" in ctx["delete_hil_message_result"]["error"]


def test_delete_hil_message_telegram_error():
    fake = FakeTelegramProvider(error=RuntimeError("Telegram error"))
    ctx = {
        "message_edit_failed": True,
        "hil_finalized_callbacks": {
            "chat_id": "12345",
            "message_id": "999",
        },
    }
    dhm.run(ctx, provider=fake)
    assert ctx["delete_hil_message_result"]["ok"] is False
    assert "Telegram error" in ctx["delete_hil_message_result"]["error"]
