"""Tests for el/nodes/apply_hil_callback.py."""
from __future__ import annotations

from datetime import datetime, timezone

from el.nodes import apply_hil_callback


TOKEN = "123e4567-e89b-12d3-a456-426614174000"
NOW = datetime(2026, 5, 7, 10, 30, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, review=None, update_result=None, fail=False):
        self.review = review
        self.update_result = update_result
        self.fail = fail
        self.events = []
        self.find_calls = []
        self.update_calls = []

    def find_review(self, review_id, callback_token):
        self.find_calls.append((review_id, callback_token))
        if self.fail:
            raise RuntimeError("database down")
        return self.review

    def update_pending_review(self, review_id, callback_token, updates):
        self.update_calls.append((review_id, callback_token, updates))
        if self.update_result is None:
            return None
        return {**self.update_result, **updates}

    def insert_event(self, row):
        self.events.append(row)
        return {"id": len(self.events), **row}


def _callback(**overrides) -> dict:
    callback = {
        "action_code": "a",
        "review_id": "42",
        "callback_token": TOKEN,
        "actor_id": "99",
        "actor_label": "@reviewer",
        "callback_query_id": "cb-1",
        "chat_id": "8243518279",
        "message_id": "501",
        "callback_data": f"a:42:{TOKEN}",
    }
    callback.update(overrides)
    return callback


def test_apply_callback_updates_pending_review_and_writes_events():
    store = FakeStore(
        review={"id": 42, "approval_status": "pending"},
        update_result={"id": 42, "approval_status": "approved"},
    )

    result = apply_hil_callback.apply_callback(_callback(), store, now=NOW)

    assert store.find_calls == [("42", TOKEN)]
    assert store.update_calls[0][2]["approval_status"] == "approved"
    assert store.update_calls[0][2]["reviewed_by"] == "@reviewer"
    assert len(store.events) == 2
    assert store.events[0]["event_type"] == "callback_received"
    assert store.events[0]["payload"]["was_pending"] is True
    assert store.events[1]["event_type"] == "approved"
    assert result["approval_status"] == "approved"
    assert result["message_should_finalize"] is True
    assert result["callback_answer_text"] == "Approved recorded."
    assert result["telegram_edit_text"] == "<b>Review approved</b>\nID: <code>42</code>\nBy: @reviewer"


def test_apply_callback_reports_already_reviewed_without_action_event():
    store = FakeStore(review={"id": 42, "approval_status": "rejected", "reviewed_by": "old"})

    result = apply_hil_callback.apply_callback(_callback(action_code="r"), store, now=NOW)

    assert store.update_calls == [("42", TOKEN, {
        "approval_status": "rejected",
        "reviewed_by": "@reviewer",
        "reviewed_at": "2026-05-07T10:30:00+00:00",
        "updated_at": "2026-05-07T10:30:00+00:00",
    })]
    assert len(store.events) == 1
    assert result["approval_status"] == "rejected"
    assert result["message_should_finalize"] is False
    assert result["callback_answer_text"] == "Already reviewed: rejected."


def test_apply_callback_reports_invalid_action_without_update():
    store = FakeStore(review={"id": 42, "approval_status": "pending"})

    result = apply_hil_callback.apply_callback(_callback(action_code="x"), store, now=NOW)

    assert store.find_calls == [("42", TOKEN)]
    assert store.update_calls == []
    assert result["approval_status"] == "pending"
    assert result["callback_answer_text"] == "Invalid review action."
    assert result["message_should_finalize"] is False


def test_apply_callback_reports_invalid_token_or_expired():
    store = FakeStore(review=None)

    result = apply_hil_callback.apply_callback(_callback(), store, now=NOW)

    assert result["review_id"] == "42"
    assert result["approval_status"] == "invalid"
    assert result["callback_answer_text"] == "Review token is invalid or expired."
    assert result["telegram_edit_text"] is None


def test_run_stores_results_and_errors():
    store = FakeStore(fail=True)
    ctx = apply_hil_callback.run({"hil_callbacks": [_callback(), None]}, store=store)

    assert ctx["hil_callback_results"] == []
    assert len(ctx["apply_hil_callback_errors"]) == 1
    assert ctx["apply_hil_callback_errors"][0]["apply_hil_callback_error"] == "database down"
    assert ctx["apply_hil_callback_result"] == {
        "ok": False,
        "attempted": 1,
        "applied": 0,
        "errors": 1,
    }
