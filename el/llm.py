"""LLM provider abstraction.

A thin shim so nodes can call `provider.generate(system, user)` without caring
which API is on the other end. Iter 4 ships only `GeminiProvider`; an OpenAI
or Mistral provider would slot in as another class implementing `LLMProvider`.

Single-shot only — no tool-use loops, no chat memory. Those are separate
ports (the n8n original used a LangChain agent with a Tavily tool node and
Postgres chat memory; both will be reintroduced in later iterations).
"""
from __future__ import annotations

from typing import Protocol

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)


class LLMProvider(Protocol):
    name: str

    def generate(self, system: str, user: str) -> str:
        ...


class GeminiProvider:
    """Google Generative Language API — `generateContent` REST endpoint."""

    name = "gemini"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    DEFAULT_TIMEOUT = 60

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT):
        self.model = model
        self.api_key = api_key or config.require("GEMINI_API_KEY")
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        url = f"{self.BASE_URL}/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
        }
        resp = requests.post(
            url,
            params={"key": self.api_key},
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            log.warning("Gemini returned no candidates: %s", data)
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)


def default_provider() -> LLMProvider:
    """Return the configured provider. Currently Gemini-only."""
    return GeminiProvider()
