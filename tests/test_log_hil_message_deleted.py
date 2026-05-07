"""Tests for el/nodes/log_hil_message_deleted.py."""
from __future__ import annotations

from el.nodes import log_hil_message_deleted as lhmd


class FakeHilMessageDeleteLogger:
    def __init__(self, response: dict | None = ..., error: Exception | None = None):  # type: ignore
        self.response = response if response is not ... else {"id": 1, "event_type": "message_deleted"}
        self.error = error
        self.calls: list[tuple] = []

    def log_message_deleted(self, review_id: int | str, delete_result: dict) -> dict | None:
        self.calls.append(("log_message_deleted", review_id, delete_result))
        if self.error:
            raise self.error
        return self.response


def test_log_hil_message_deleted_success():
    fake = FakeHilMessageDeleteLogger()
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "delete_hil_message_result": {
            "ok": True,
        },
    }
    lhmd.run(ctx, logger=fake)
    assert ctx["log_hil_message_deleted_result"]["ok"] is True
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == 123


def test_log_hil_message_deleted_missing_review_id():
    fake = FakeHilMessageDeleteLogger()
    ctx = {
        "hil_finalized_callbacks": {},
        "delete_hil_message_result": {"ok": True},
    }
    lhmd.run(ctx, logger=fake)
    assert ctx["log_hil_message_deleted_result"]["ok"] is False
    assert "Missing review_id" in ctx["log_hil_message_deleted_result"]["error"]


def test_log_hil_message_deleted_logger_error():
    fake = FakeHilMessageDeleteLogger(error=RuntimeError("DB error"))
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "delete_hil_message_result": {"ok": True},
    }
    lhmd.run(ctx, logger=fake)
    assert ctx["log_hil_message_deleted_result"]["ok"] is False
    assert "DB error" in ctx["log_hil_message_deleted_result"]["error"]


def test_log_hil_message_deleted_insertion_returns_none():
    fake = FakeHilMessageDeleteLogger(response=None)
    ctx = {
        "hil_finalized_callbacks": {
            "review_id": 123,
        },
        "delete_hil_message_result": {"ok": True},
    }
    lhmd.run(ctx, logger=fake)
    assert ctx["log_hil_message_deleted_result"]["ok"] is False
    assert "Failed to insert" in ctx["log_hil_message_deleted_result"]["error"]
