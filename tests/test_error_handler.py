"""Tests for el/error_handler.py — the port of el_error_handler.json."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from el import error_handler as eh


def test_format_error_message_contains_node_and_message():
    ts = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    text = eh.format_error_message("youtube_trending", ValueError("boom"), ts)
    assert "youtube_trending" in text
    assert "boom" in text
    assert "Time (IST)" in text
    assert text.startswith("🚨 *EL Node Failed*")


def test_format_error_message_truncates_long_messages():
    ts = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    long_msg = "x" * 1000
    text = eh.format_error_message("n", RuntimeError(long_msg), ts)
    assert "x" * eh.MSG_TRUNCATE in text
    assert "x" * (eh.MSG_TRUNCATE + 1) not in text


def test_send_telegram_alert_skips_when_creds_missing(monkeypatch):
    monkeypatch.setattr(eh.config, "get", lambda name, default=None: None)
    assert eh.send_telegram_alert("hi") is False


def test_send_telegram_alert_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(
        eh.config,
        "get",
        lambda name, default=None: {"EL_DEVELOPER_ALERT_TOKEN_KEY": "TKN", "EL_DEVELOPER_ALERT_CHAT_ID": "CID"}.get(name),
    )
    with patch.object(eh.requests, "post") as mock_post:
        mock_post.return_value.ok = True
        ok = eh.send_telegram_alert("hello")
        assert ok is True
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.telegram.org/botTKN/sendMessage"
        assert kwargs["json"] == {"chat_id": "CID", "text": "hello", "parse_mode": "Markdown"}


def test_error_handler_reraises_and_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(eh, "send_telegram_alert", lambda text: sent.append(text) or True)
    with pytest.raises(RuntimeError, match="kaboom"):
        with eh.error_handler():
            raise RuntimeError("kaboom")
    assert len(sent) == 1
    assert "kaboom" in sent[0]


def test_error_handler_no_exception_no_alert(monkeypatch):
    sent = []
    monkeypatch.setattr(eh, "send_telegram_alert", lambda text: sent.append(text) or True)
    with eh.error_handler():
        pass
    assert sent == []
