"""SP4 web-app settings.

Settings are loaded from environment variables via ``Settings.from_env()``.
Tests construct a ``Settings`` directly with fake providers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Runtime configuration for the FastAPI app.

    Provider fields are typed as ``Any`` because real and fake providers
    share a duck-typed contract rather than a single class.
    """

    web_secret_key: str
    rate_limit_per_minute: int = 30
    chat_top_k: int = 5
    llm_model: str = "gemini-2.0-flash"
    embedding_provider: Any | None = None
    db_provider: Any | None = None
    llm_stream: Callable[[str], Any] | None = None
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        secret = os.environ.get("WEB_SECRET_KEY")
        if not secret:
            raise RuntimeError(
                "WEB_SECRET_KEY is required to start the SP4 web app. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
            )
        return cls(
            web_secret_key=secret,
            rate_limit_per_minute=int(os.environ.get("WEB_RATE_LIMIT_PER_MINUTE", "30")),
            chat_top_k=int(os.environ.get("WEB_CHAT_TOP_K", "5")),
            llm_model=os.environ.get("WEB_LLM_MODEL", "gemini-2.0-flash"),
            enabled=_truthy(os.environ.get("EL_WEB_ENABLED"), default=False),
        )
