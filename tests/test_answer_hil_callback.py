"""Tests for el/nodes/answer_hil_callback.py."""
from __future__ import annotations

from el.nodes import answer_hil_callback


class FakeTelegramProvider:
    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.calls = []

    def answer_callback(self, *, callback_query_id, text, show_alert=False, cache_time=0):
        self.calls.append({
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
            "cache_time": cache_time,
        })
        if callback_query_id in self.fail_ids:
            raise RuntimeError("telegram callback failed")
        return {"ok": True, "result": True}


def _result(**overrides) -> dict:
    result = {
        "review_id": 42,
        "callback_query_id": "cb-1",
        "callback_answer_text": "Approved recorded.",
        "message_should_finalize": True,
    }
    result.update(overrides)
    return result


def test_answer_result_calls_telegram_callback_api():
    provider = FakeTelegramProvider()
    answered = answer_hil_callback.answer_result(_result(), provider)

    assert provider.calls == [{
        "callback_query_id": "cb-1",
        "text": "Approved recorded.",
        "show_alert": False,
        "cache_time": 0,
    }]
    assert answered["telegram_callback_answer_response"] == {"ok": True, "result": True}


def test_run_answers_callback_results():
    provider = FakeTelegramProvider()
    ctx = answer_hil_callback.run({"hil_callback_results": [_result()]}, provider=provider)

    assert len(ctx["hil_callback_answers"]) == 1
    assert ctx["answer_hil_callback_errors"] == []
    assert ctx["answer_hil_callback_result"] == {
        "ok": True,
        "attempted": 1,
        "answered": 1,
        "errors": 0,
    }


def test_run_collects_answer_errors():
    provider = FakeTelegramProvider(fail_ids={"cb-1"})
    ctx = answer_hil_callback.run({"hil_callback_results": [_result()]}, provider=provider)

    assert ctx["hil_callback_answers"] == []
    assert len(ctx["answer_hil_callback_errors"]) == 1
    assert ctx["answer_hil_callback_errors"][0]["answer_hil_callback_error"] == (
        "telegram callback failed"
    )
    assert ctx["answer_hil_callback_result"] == {
        "ok": False,
        "attempted": 1,
        "answered": 0,
        "errors": 1,
    }


def test_run_ignores_non_dict_results():
    provider = FakeTelegramProvider()
    ctx = answer_hil_callback.run({"hil_callback_results": [_result(), None, "bad"]}, provider=provider)

    assert len(ctx["hil_callback_answers"]) == 1
    assert ctx["answer_hil_callback_result"]["attempted"] == 1
