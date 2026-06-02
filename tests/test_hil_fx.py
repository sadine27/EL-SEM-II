"""Tests for the HIL presentation FX (el/hil_fx.py + wired nodes)."""
from __future__ import annotations

import pytest

from el import hil_fx as fx
from el.nodes import answer_hil_callback
from el.nodes import edit_hil_message
from el.nodes import send_hil_fx


@pytest.fixture(autouse=True)
def _fx_env(monkeypatch):
    """Deterministic FX config + an instant buffer so tests stay fast."""
    monkeypatch.setenv("EL_HIL_FX_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_FX_ALERT", "false")
    monkeypatch.setenv("EL_HIL_FX_DING", "true")
    monkeypatch.setenv("EL_HIL_FX_BUFFER_MS", "1")  # ~1ms, exercises two-frame path


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

def test_flags_default_and_toggle(monkeypatch):
    assert fx.fx_enabled() is True
    assert fx.alert_enabled() is False
    assert fx.ding_enabled() is True

    monkeypatch.setenv("EL_HIL_FX_ENABLED", "off")
    monkeypatch.setenv("EL_HIL_FX_ALERT", "yes")
    monkeypatch.setenv("EL_HIL_FX_DING", "0")
    assert fx.fx_enabled() is False
    assert fx.alert_enabled() is True
    assert fx.ding_enabled() is False


def test_buffer_seconds_parses_and_floors(monkeypatch):
    monkeypatch.setenv("EL_HIL_FX_BUFFER_MS", "500")
    assert fx.buffer_seconds() == pytest.approx(0.5)
    monkeypatch.setenv("EL_HIL_FX_BUFFER_MS", "-9")
    assert fx.buffer_seconds() == 0.0
    monkeypatch.setenv("EL_HIL_FX_BUFFER_MS", "garbage")
    assert fx.buffer_seconds() == pytest.approx(0.4)


def test_toast_and_ding_per_status():
    assert "Approved" in fx.toast_text("approved")
    assert fx.toast_text("nonsense") == "Recorded ✅"
    assert fx.ding_emoji("approved") == "\U0001f389"
    assert fx.ding_emoji("rejected") == "\U0001f44e"
    assert fx.ding_emoji("nonsense") is None


def test_final_text_includes_card_fields_and_escapes():
    text = fx.final_text(
        "approved",
        review_id=42,
        reviewed_by="@reviewer",
        reviewed_at="2026-05-07T10:30:00+00:00",
        product_name="RCB Jersey",
    )
    assert "APPROVED" in text
    assert "RCB Jersey" in text
    assert "@reviewer" in text
    assert "#42" in text
    assert "10:30" in text


def test_final_text_html_escapes_untrusted_fields():
    text = fx.final_text("approved", product_name="<script>", reviewed_by="<b>x</b>")
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_buffer_text_names_the_action():
    assert "Approving" in fx.buffer_text("approved")
    assert "Rejecting" in fx.buffer_text("rejected")


# --------------------------------------------------------------------------- #
# answer_hil_callback FX
# --------------------------------------------------------------------------- #

class FakeAnswerProvider:
    def __init__(self):
        self.calls = []

    def answer_callback(self, *, callback_query_id, text, show_alert=False, cache_time=0):
        self.calls.append({"text": text, "show_alert": show_alert})
        return {"ok": True}


def test_answer_uses_spicy_toast_when_finalized():
    provider = FakeAnswerProvider()
    result = {
        "callback_query_id": "cb-1",
        "approval_status": "approved",
        "message_should_finalize": True,
        "callback_answer_text": "Approved recorded.",  # plain fallback, should be overridden
    }
    answer_hil_callback.answer_result(result, provider)
    assert provider.calls[0]["text"] == fx.toast_text("approved")
    assert provider.calls[0]["show_alert"] is False


def test_answer_show_alert_when_alert_mode(monkeypatch):
    monkeypatch.setenv("EL_HIL_FX_ALERT", "true")
    provider = FakeAnswerProvider()
    result = {
        "callback_query_id": "cb-1",
        "approval_status": "rejected",
        "message_should_finalize": True,
        "callback_answer_text": "Rejected recorded.",
    }
    answer_hil_callback.answer_result(result, provider)
    assert provider.calls[0]["show_alert"] is True


def test_answer_falls_back_to_plain_when_not_finalized():
    provider = FakeAnswerProvider()
    result = {
        "callback_query_id": "cb-1",
        "approval_status": "rejected",
        "message_should_finalize": False,
        "callback_answer_text": "Already reviewed: rejected.",
    }
    answer_hil_callback.answer_result(result, provider)
    assert provider.calls[0]["text"] == "Already reviewed: rejected."


def test_answer_falls_back_when_fx_disabled(monkeypatch):
    monkeypatch.setenv("EL_HIL_FX_ENABLED", "false")
    provider = FakeAnswerProvider()
    result = {
        "callback_query_id": "cb-1",
        "approval_status": "approved",
        "message_should_finalize": True,
        "callback_answer_text": "Approved recorded.",
    }
    answer_hil_callback.answer_result(result, provider)
    assert provider.calls[0]["text"] == "Approved recorded."


# --------------------------------------------------------------------------- #
# edit_hil_message FX (two-frame animation + spicy final card)
# --------------------------------------------------------------------------- #

class FakeEditProvider:
    def __init__(self):
        self.calls = []

    def edit_message_text(self, *, chat_id, message_id, text, disable_web_page_preview=False):
        self.calls.append(text)
        return {"ok": True, "result": {"message_id": message_id}}


def test_edit_plays_buffer_then_final_when_spicy():
    provider = FakeEditProvider()
    ctx = {
        "hil_finalized_callbacks": {
            "chat_id": "1",
            "message_id": "2",
            "approval_status": "approved",
            "reviewed_by": "@reviewer",
            "review_id": 7,
            "product_name": "RCB Jersey",
            "telegram_edit_text": "<b>Review approved</b>",  # plain, should NOT be used
        }
    }
    edit_hil_message.run(ctx, provider=provider)
    assert len(provider.calls) == 2  # buffer frame + final card
    assert "Approving" in provider.calls[0]
    assert "APPROVED" in provider.calls[1]
    assert "RCB Jersey" in provider.calls[1]
    assert ctx["edit_hil_message_result"]["ok"] is True


def test_edit_single_frame_when_no_status():
    """Backward-compatible path: no approval_status => one plain edit."""
    provider = FakeEditProvider()
    ctx = {
        "hil_finalized_callbacks": {
            "chat_id": "1",
            "message_id": "2",
            "telegram_edit_text": "Updated text",
        }
    }
    edit_hil_message.run(ctx, provider=provider)
    assert provider.calls == ["Updated text"]


def test_edit_buffer_failure_does_not_block_final(monkeypatch):
    monkeypatch.setenv("EL_HIL_FX_BUFFER_MS", "5")

    class FlakyBufferProvider:
        def __init__(self):
            self.calls = []

        def edit_message_text(self, *, chat_id, message_id, text, disable_web_page_preview=False):
            self.calls.append(text)
            if len(self.calls) == 1:  # the buffer frame blows up
                raise RuntimeError("buffer boom")
            return {"ok": True}

    provider = FlakyBufferProvider()
    ctx = {
        "hil_finalized_callbacks": {
            "chat_id": "1",
            "message_id": "2",
            "approval_status": "rejected",
        }
    }
    edit_hil_message.run(ctx, provider=provider)
    assert ctx["edit_hil_message_result"]["ok"] is True  # final edit still landed
    assert "REJECTED" in provider.calls[-1]


# --------------------------------------------------------------------------- #
# send_hil_fx (the ding)
# --------------------------------------------------------------------------- #

class FakeSendProvider:
    def __init__(self):
        self.calls = []

    def send_message(self, *, chat_id, text, reply_markup, parse_mode="HTML", disable_web_page_preview=False):
        self.calls.append({"chat_id": chat_id, "text": text})
        return {"ok": True}


def test_ding_sends_emoji_on_finalize():
    provider = FakeSendProvider()
    ctx = send_hil_fx.run(
        {"hil_finalized_callbacks": {"chat_id": "55", "approval_status": "approved"}},
        provider=provider,
    )
    assert provider.calls == [{"chat_id": "55", "text": "\U0001f389"}]
    assert ctx["send_hil_fx_result"]["ok"] is True


def test_ding_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("EL_HIL_FX_DING", "false")
    provider = FakeSendProvider()
    ctx = send_hil_fx.run(
        {"hil_finalized_callbacks": {"chat_id": "55", "approval_status": "approved"}},
        provider=provider,
    )
    assert provider.calls == []
    assert ctx["send_hil_fx_result"]["skipped"] == "disabled"


def test_ding_skipped_for_unknown_status():
    provider = FakeSendProvider()
    ctx = send_hil_fx.run(
        {"hil_finalized_callbacks": {"chat_id": "55", "approval_status": "pending"}},
        provider=provider,
    )
    assert provider.calls == []
    assert ctx["send_hil_fx_result"]["skipped"] == "no-target"


def test_ding_swallows_provider_errors():
    class BoomProvider:
        def send_message(self, **kwargs):
            raise RuntimeError("network down")

    ctx = send_hil_fx.run(
        {"hil_finalized_callbacks": {"chat_id": "55", "approval_status": "approved"}},
        provider=BoomProvider(),
    )
    assert ctx["send_hil_fx_result"]["ok"] is False
    assert "network down" in ctx["send_hil_fx_result"]["error"]
