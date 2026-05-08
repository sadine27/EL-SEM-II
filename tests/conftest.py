"""Pytest config: isolate tests from the developer's local .env.

Without this, `.env` is auto-loaded by `el.config` at import time and leaks
real credentials into every test's `os.environ`. Tests then accidentally hit
real APIs (Vertex, Tavily, etc.) instead of their injected fakes. Each test
that needs a specific var sets it explicitly via monkeypatch.setenv.
"""
from __future__ import annotations

import pytest

_PIPELINE_ENV_VARS = (
    "YOUTUBE_API_KEY",
    "TAVILY_API_KEY",
    "GEMINI_API_KEY",
    "VERTEX_LOCATION",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "CJ_EMAIL",
    "CJ_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_KEY",
    "BROWSERBASE_API_KEY",
    "TELEGRAM_HIL_BOT_TOKEN",
    "TELEGRAM_HIL_CHAT_ID",
    "TELEGRAM_ALERT_CHAT_ID",
    "EL_DEVELOPER_ALERT_TOKEN_KEY",
    "EL_DEVELOPER_ALERT_CHAT_ID",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for var in _PIPELINE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
