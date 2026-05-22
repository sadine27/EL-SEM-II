"""Tests for el/nodes/notify_business.py."""
from __future__ import annotations

from el.nodes import notify_business


class FakeTelegram:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[dict] = []

    def send_message(self, *, chat_id, text, reply_markup, parse_mode="HTML", disable_web_page_preview=False):
        self.calls.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})
        if self.fail:
            raise RuntimeError("telegram down")
        return {"ok": True, "result": {"message_id": 1}}


def test_sends_summary_with_request_id_niche_and_link():
    ctx = {
        "request_id": "r-42",
        "niche": "yoga mats",
        "hil_review_rows": [{"product_name": "A"}, {"product_name": "B"}],
    }
    tg = FakeTelegram()
    notify_business.run(ctx, provider=tg)
    assert ctx["notify_business_result"]["ok"] is True
    text = tg.calls[0]["text"]
    assert "r-42" in text
    assert "yoga mats" in text
    assert "2 picks" in text
    assert "/r-42" in text


def test_failure_sets_formatted_error_and_result_not_ok():
    ctx = {"request_id": "r1", "niche": "n", "hil_review_rows": [{"product_name": "A"}]}
    tg = FakeTelegram(fail=True)
    notify_business.run(ctx, provider=tg)
    assert ctx["notify_business_result"]["ok"] is False
    assert ctx["formatted_error"][0]["text"].startswith("notify_business failed")


def test_falls_back_to_run_request_id_when_no_request_id():
    ctx = {"run_request_id": "rr-99", "curated_picks": [{"topic": "T"}]}
    tg = FakeTelegram()
    notify_business.run(ctx, provider=tg)
    assert "rr-99" in tg.calls[0]["text"]


def test_uses_business_chat_id_when_set(monkeypatch):
    monkeypatch.setenv("BUSINESS_NOTIFY_TELEGRAM_CHAT_ID", "999")
    ctx = {"request_id": "r1", "niche": "n"}
    tg = FakeTelegram()
    notify_business.run(ctx, provider=tg)
    assert tg.calls[0]["chat_id"] == "999"
