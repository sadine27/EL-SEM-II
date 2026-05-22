"""SP4 — Settings.from_env tests."""
from __future__ import annotations

import pytest

from el.web.settings import Settings


def test_from_env_reads_required_secret(monkeypatch):
    monkeypatch.setenv("WEB_SECRET_KEY", "abc123")
    monkeypatch.delenv("WEB_RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("WEB_CHAT_TOP_K", raising=False)
    monkeypatch.delenv("WEB_LLM_MODEL", raising=False)
    monkeypatch.delenv("EL_WEB_ENABLED", raising=False)

    s = Settings.from_env()

    assert s.web_secret_key == "abc123"
    assert s.rate_limit_per_minute == 30
    assert s.chat_top_k == 5
    assert s.llm_model == "gemini-2.0-flash"
    assert s.enabled is False


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("WEB_SECRET_KEY", "secret")
    monkeypatch.setenv("WEB_RATE_LIMIT_PER_MINUTE", "7")
    monkeypatch.setenv("WEB_CHAT_TOP_K", "9")
    monkeypatch.setenv("WEB_LLM_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("EL_WEB_ENABLED", "true")

    s = Settings.from_env()

    assert s.rate_limit_per_minute == 7
    assert s.chat_top_k == 9
    assert s.llm_model == "gemini-2.5-pro"
    assert s.enabled is True


def test_from_env_raises_without_secret(monkeypatch):
    monkeypatch.delenv("WEB_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="WEB_SECRET_KEY"):
        Settings.from_env()


def test_from_env_empty_secret_raises(monkeypatch):
    monkeypatch.setenv("WEB_SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        Settings.from_env()
