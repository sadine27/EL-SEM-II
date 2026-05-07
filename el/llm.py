"""LLM provider abstraction.

Two tiers:
- `LLMProvider`: single-shot generation (no tools, no chat history)
- `LLMAgentProvider`: function-calling loop for tool-use workflows

Iter 4 shipped `GeminiProvider` (single-shot). Iter 7 adds `GeminiAgentProvider`
for the curator's web-search loop. Postgres chat memory deferred to iter 8+.
"""
from __future__ import annotations

import json
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
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


class LLMAgentProvider(Protocol):
    """LLM with function-calling support for tool-use loops."""
    name: str

    def call_with_tools(self, system: str, user: str, tools: list[dict], max_turns: int = 5) -> str:
        """Call model with tools. Returns final text response after tool loop."""
        ...


class GeminiAgentProvider:
    """Gemini with function-calling for curator web-search verification."""

    name = "gemini-agent"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    DEFAULT_TIMEOUT = 60

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT, tavily_provider: object | None = None):
        self.model = model
        self.api_key = api_key or config.require("GEMINI_API_KEY")
        self.timeout = timeout
        self._tavily_provider = tavily_provider

    def _get_tavily_provider(self):
        """Lazy-load Tavily provider to avoid import cycle."""
        if self._tavily_provider is None:
            from el import tavily
            self._tavily_provider = tavily.default_provider()
        return self._tavily_provider

    def call_with_tools(self, system: str, user: str, tools: list[dict], max_turns: int = 5) -> str:
        """Run function-calling loop: call model → execute tools → loop until done."""
        url = f"{self.BASE_URL}/{self.model}:generateContent"
        contents = [{"role": "user", "parts": [{"text": user}]}]
        turn = 0

        while turn < max_turns:
            turn += 1
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": contents,
                "tools": [{"function_declarations": tools}] if tools else [],
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
                log.warning("Gemini returned no candidates on turn %d", turn)
                return ""

            first = candidates[0] if isinstance(candidates[0], dict) else {}
            content = first.get("content") if isinstance(first.get("content"), dict) else {}
            parts = content.get("parts") if isinstance(content.get("parts"), list) else []

            # Check for tool use
            tool_calls = [p for p in parts if isinstance(p, dict) and "functionCall" in p]
            if not tool_calls:
                # No more tool calls — extract final text response
                text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p]
                return "".join(text_parts)

            # Execute tool calls and append results to conversation
            tool_results = []
            for part in tool_calls:
                func_call = part.get("functionCall", {})
                if not isinstance(func_call, dict):
                    continue
                func_name = func_call.get("name", "")
                func_args = func_call.get("args", {})
                if not isinstance(func_args, dict):
                    func_args = {}

                if func_name == "web_search":
                    query = func_args.get("query", "")
                    result = self._execute_web_search(query)
                    tool_results.append({
                        "functionResponse": {
                            "name": "web_search",
                            "response": result,
                        }
                    })
                else:
                    log.warning("Unknown tool: %s", func_name)

            # Add assistant response and tool results back to contents
            contents.append({"role": "model", "parts": parts})
            contents.append({"role": "user", "parts": tool_results})

        log.warning("Curator agent loop reached max turns (%d)", max_turns)
        return ""

    def _execute_web_search(self, query: str) -> dict:
        """Execute web_search tool via Tavily."""
        tavily = self._get_tavily_provider()
        result = tavily.search(query, max_results=3)
        return {
            "query": query,
            "found": result.get("ok", False),
            "answer": result.get("answer", ""),
            "sources": [
                {"title": r.get("title", ""), "url": r.get("url", "")}
                for r in result.get("results", [])
            ],
        }


def default_provider() -> LLMProvider:
    """Return the configured provider. Currently Gemini-only."""
    return GeminiProvider()


def default_agent_provider() -> LLMAgentProvider:
    """Return the configured agent provider (with function-calling)."""
    return GeminiAgentProvider()
