"""Tests for el/nodes/email_product_detail.py."""
from __future__ import annotations

from el.nodes import email_product_detail


class FakeSmtp:
    def __init__(self, fail_names: set[str] | None = None):
        self.fail_names = fail_names or set()
        self.sent: list = []

    def send(self, msg):
        subj = msg["Subject"]
        if any(name in subj for name in self.fail_names):
            raise RuntimeError(f"fail: {subj}")
        self.sent.append(msg)
        return f"<id-{len(self.sent)}@local>"


def test_sends_one_per_pick_all_ok():
    ctx = {
        "business_email": "x@y.com",
        "hil_review_rows": [
            {"product_name": "A"},
            {"product_name": "B"},
            {"product_name": "C"},
        ],
    }
    smtp = FakeSmtp()
    email_product_detail.run(ctx, provider=smtp)
    res = ctx["email_product_detail_results"]
    assert len(res) == 3
    assert all(r["ok"] for r in res)
    assert len(smtp.sent) == 3
    assert "formatted_error" not in ctx


def test_partial_failure_aggregates_once():
    ctx = {
        "business_email": "x@y.com",
        "hil_review_rows": [
            {"product_name": "Good1"},
            {"product_name": "BadBoy"},
            {"product_name": "Good2"},
        ],
    }
    smtp = FakeSmtp(fail_names={"BadBoy"})
    email_product_detail.run(ctx, provider=smtp)
    res = ctx["email_product_detail_results"]
    assert len(res) == 3
    assert sum(1 for r in res if r["ok"]) == 2
    assert ctx["formatted_error"][0]["text"] == "email_product_detail: 1/3 sends failed"


def test_no_picks_emits_nothing():
    ctx = {"business_email": "x@y.com", "hil_review_rows": [], "curated_picks": []}
    smtp = FakeSmtp()
    email_product_detail.run(ctx, provider=smtp)
    assert ctx["email_product_detail_results"] == []
    assert smtp.sent == []
    assert "formatted_error" not in ctx


def test_falls_back_to_curated_picks_when_no_hil():
    ctx = {
        "business_email": "x@y.com",
        "curated_picks": [{"topic": "T1"}, {"topic": "T2"}],
    }
    smtp = FakeSmtp()
    email_product_detail.run(ctx, provider=smtp)
    assert len(smtp.sent) == 2
