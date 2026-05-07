"""Tests for el/nodes/log_hil_message_edited.py."""
from __future__ import annotations

from el.nodes import log_hil_message_edited as lhme


class FakeHilMessageEditLogger:
    def __init__(self, response: dict | None = ..., error: Exception | None = None):  # type: ignore
        self.response = response if response is not ... else {"id": 1, "event_type": "message_edited"}
        self.error = error
        self.calls: list[tuple] = []

    def log_message_edited(self, review_id: int | str, edit_result: dict) -> dict | None:
        self.calls.append(("log_message_edited", review_id, edit_result))
        if self.error:
            raise self.error
        return self.response


def test_log_hil_message_edited_success():
    fake = FakeHilMessageEditLogger()
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "edit_hil_message_result": {
            "ok": True,
        },
    }
    lhme.run(ctx, logger=fake)
    assert ctx["log_hil_message_edited_result"]["ok"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == 123


def test_log_hil_message_edited_missing_review_id():
    fake = FakeHilMessageEditLogger()
    ctx = {
        "hil_finalized_callbacks": {},
        "edit_hil_message_result": {"ok": True},
    }
    lhme.run(ctx, logger=fake)
    assert ctx["log_hil_message_edited_result"]["ok"] is False
    assert "Missing review_id" in ctx["log_hil_message_edited_result"]["error"]


def test_log_hil_message_edited_logger_error():
    fake = FakeHilMessageEditLogger(error=RuntimeError("DB error"))
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "edit_hil_message_result": {"ok": True},
    }
    lhme.run(ctx, logger=fake)
    assert ctx["log_hil_message_edited_result"]["ok"] is False
    assert "DB error" in ctx["log_hil_message_edited_result"]["error"]


def test_log_hil_message_edited_insertion_returns_none():
    fake = FakeHilMessageEditLogger(response=None)
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "edit_hil_message_result": {"ok": True},
    }
    lhme.run(ctx, logger=fake)
    assert ctx["log_hil_message_edited_result"]["ok"] is False
    assert "Failed to insert" in ctx["log_hil_message_edited_result"]["error"]
