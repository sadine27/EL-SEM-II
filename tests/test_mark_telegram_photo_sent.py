"""Tests for el/nodes/mark_telegram_photo_sent.py."""
from __future__ import annotations

from datetime import datetime, timezone

from el.nodes import mark_telegram_photo_sent


class FakeSupabaseProvider:
    def __init__(self, fail_ids: set[int] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls = []

    def update_row_by_id(self, *, schema, table, row_id, updates):
        self.calls.append({
            "schema": schema,
            "table": table,
            "row_id": row_id,
            "updates": updates,
        })
        if row_id in self.fail_ids:
            raise RuntimeError("database update failed")
        return [{"id": row_id, **updates}]


def _card(**overrides) -> dict:
    card = {
        "review_id": 42,
        "telegram_photo_response": {
            "ok": True,
            "result": {
                "chat": {"id": 8243518279},
                "message_id": 501,
            },
        },
    }
    card.update(overrides)
    return card


def test_build_update_maps_telegram_response_fields():
    sent_at = datetime(2026, 5, 7, 10, 30, tzinfo=timezone.utc)
    updates = mark_telegram_photo_sent.build_update(_card(), sent_at=sent_at)

    assert updates == {
        "telegram_chat_id": 8243518279,
        "telegram_message_id": 501,
        "telegram_media_status": "sent",
        "telegram_sent_at": "2026-05-07T10:30:00+00:00",
        "updated_at": "2026-05-07T10:30:00+00:00",
    }


def test_mark_card_updates_private_hil_reviews_by_review_id():
    provider = FakeSupabaseProvider()
    marked = mark_telegram_photo_sent.mark_card(_card(), provider)

    assert provider.calls[0]["schema"] == "private"
    assert provider.calls[0]["table"] == "hil_reviews"
    assert provider.calls[0]["row_id"] == 42
    assert provider.calls[0]["updates"]["telegram_media_status"] == "sent"
    assert marked["telegram_photo_mark_result"][0]["telegram_message_id"] == 501


def test_run_marks_successful_photo_sends():
    provider = FakeSupabaseProvider()
    ctx = mark_telegram_photo_sent.run({"telegram_photo_sent": [_card()]}, provider=provider)

    assert len(ctx["telegram_photo_marked"]) == 1
    assert ctx["mark_telegram_photo_sent_errors"] == []
    assert ctx["mark_telegram_photo_sent_result"] == {
        "ok": True,
        "attempted": 1,
        "marked": 1,
        "errors": 0,
    }


def test_run_continue_on_fail_shape():
    provider = FakeSupabaseProvider(fail_ids={42})
    ctx = mark_telegram_photo_sent.run({"telegram_photo_sent": [_card()]}, provider=provider)

    assert ctx["telegram_photo_marked"] == []
    assert len(ctx["mark_telegram_photo_sent_errors"]) == 1
    assert ctx["mark_telegram_photo_sent_errors"][0]["mark_telegram_photo_sent_error"] == (
        "database update failed"
    )
    assert ctx["mark_telegram_photo_sent_result"] == {
        "ok": False,
        "attempted": 1,
        "marked": 0,
        "errors": 1,
    }


def test_run_handles_missing_telegram_response_as_error():
    provider = FakeSupabaseProvider()
    ctx = mark_telegram_photo_sent.run(
        {"telegram_photo_sent": [_card(telegram_photo_response={"ok": True})]},
        provider=provider,
    )

    assert ctx["telegram_photo_marked"] == []
    assert "missing chat.id" in ctx["mark_telegram_photo_sent_errors"][0][
        "mark_telegram_photo_sent_error"
    ]
