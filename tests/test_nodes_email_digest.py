"""Tests for el/nodes/email_digest.py."""
from __future__ import annotations

from email.message import EmailMessage

from el.nodes import email_digest


class FakeSmtp:
    def __init__(self, *, raise_on_send: bool = False):
        self.raise_on_send = raise_on_send
        self.sent: list[EmailMessage] = []

    def send(self, msg):
        if self.raise_on_send:
            raise RuntimeError("smtp boom")
        self.sent.append(msg)
        return "<msgid@local>"


class FakeDrive:
    def __init__(self, *, raise_on_export: bool = False, content: bytes = b"xlsx"):
        self.raise_on_export = raise_on_export
        self.content = content
        self.calls: list[tuple[str, str]] = []

    def export_file(self, file_id, mime_type="x"):
        self.calls.append((file_id, mime_type))
        if self.raise_on_export:
            raise RuntimeError("drive 403")
        return self.content


class FakeLLM:
    def generate(self, system, user):
        return "Narrative."


def _ctx_with_picks():
    return {
        "request_id": "r1",
        "niche": "earbuds",
        "business_email": "owner@example.com",
        "hil_review_rows": [
            {"product_name": "Buds Pro", "price_text": "$25", "source_url": "https://x.com/1"},
            {"product_name": "Buds Air", "price_numeric": 19, "currency": "USD"},
        ],
        "sheet_id": "sheet-abc",
    }


def test_happy_path_sends_with_xlsx():
    ctx = _ctx_with_picks()
    smtp = FakeSmtp()
    drive = FakeDrive()
    email_digest.run(ctx, provider=smtp, drive_provider=drive, llm_provider=FakeLLM())
    res = ctx["email_digest_result"]
    assert res["ok"] is True
    assert res["pick_count"] == 2
    assert res["xlsx"] == "xlsx_ok"
    assert drive.calls == [("sheet-abc", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
    assert len(smtp.sent) == 1


def test_xlsx_export_failure_still_sends_no_formatted_error():
    ctx = _ctx_with_picks()
    smtp = FakeSmtp()
    drive = FakeDrive(raise_on_export=True)
    email_digest.run(ctx, provider=smtp, drive_provider=drive, llm_provider=FakeLLM())
    assert ctx["email_digest_result"]["ok"] is True
    assert ctx["email_digest_result"]["xlsx"].startswith("xlsx_export_failed")
    assert "formatted_error" not in ctx


def test_smtp_failure_sets_formatted_error():
    ctx = _ctx_with_picks()
    smtp = FakeSmtp(raise_on_send=True)
    email_digest.run(ctx, provider=smtp, drive_provider=FakeDrive(), llm_provider=FakeLLM())
    assert ctx["email_digest_result"]["ok"] is False
    assert ctx["formatted_error"][0]["text"].startswith("email_digest failed")


def test_no_picks_skips_send():
    ctx = {"business_email": "x@y.com", "hil_review_rows": [], "curated_picks": []}
    smtp = FakeSmtp()
    email_digest.run(ctx, provider=smtp, drive_provider=FakeDrive(), llm_provider=FakeLLM())
    assert ctx["email_digest_result"]["ok"] is True
    assert ctx["email_digest_result"].get("skipped") == "no picks"
    assert smtp.sent == []


def test_no_recipient_skips_with_error():
    ctx = {"hil_review_rows": [{"product_name": "P"}]}
    smtp = FakeSmtp()
    # Override config getters by clearing any default email — for the unit test
    # we rely on the ctx not having business_email and config typically not set.
    import el.config as cfg
    orig = cfg.get

    def fake_get(name, default=None):
        if name in {"GMAIL_SMTP_USER", "BUSINESS_NOTIFY_EMAIL"}:
            return None
        return orig(name, default)

    cfg.get = fake_get
    try:
        email_digest.run(ctx, provider=smtp, drive_provider=FakeDrive(), llm_provider=FakeLLM())
    finally:
        cfg.get = orig
    assert ctx["email_digest_result"]["ok"] is False
    assert "recipient" in ctx["email_digest_result"]["error"]


def test_falls_back_to_curated_picks_when_no_hil_rows():
    ctx = {
        "business_email": "x@y.com",
        "curated_picks": [{"topic": "T1", "rank": 1}],
    }
    smtp = FakeSmtp()
    email_digest.run(ctx, provider=smtp, drive_provider=None, llm_provider=FakeLLM())
    assert ctx["email_digest_result"]["ok"] is True
    assert ctx["email_digest_result"]["pick_count"] == 1
