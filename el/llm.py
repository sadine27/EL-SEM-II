"""LLM provider abstraction.

Two tiers:
- `LLMProvider`: single-shot generation (no tools, no chat history)
- `LLMAgentProvider`: function-calling loop for tool-use workflows

Iter 14 swapped from AI Studio (`generativelanguage.googleapis.com` + API key)
to Vertex AI (`aiplatform.googleapis.com` + service-account OAuth). Body schema
and model IDs are unchanged — only the host and auth header differ.
"""
from __future__ import annotations

import json
from typing import Protocol

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)

_VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class VertexAuth:
    """Mints + caches OAuth tokens for Vertex AI from the configured SA JSON."""

    def __init__(self, sa_info: dict | None = None, location: str | None = None):
        if sa_info is None:
            sa_info = json.loads(config.require("GOOGLE_SERVICE_ACCOUNT_JSON"))
        self._sa_info = sa_info
        self.project_id = sa_info.get("project_id", "")
        self.location = location or config.get("VERTEX_LOCATION", "global")
        self._creds = None

    def get_token(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        if self._creds is None:
            self._creds = service_account.Credentials.from_service_account_info(
                self._sa_info, scopes=[_VERTEX_SCOPE]
            )
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token


def vertex_url(auth: VertexAuth, model: str) -> str:
    host = (
        "https://aiplatform.googleapis.com"
        if auth.location == "global"
        else f"https://{auth.location}-aiplatform.googleapis.com"
    )
    return (
        f"{host}/v1/projects/{auth.project_id}/locations/{auth.location}"
        f"/publishers/google/models/{model}:generateContent"
    )


def default_vertex_auth() -> VertexAuth:
    return VertexAuth()


class LLMProvider(Protocol):
    name: str

    def generate(self, system: str, user: str) -> str:
        ...


class GeminiProvider:
    """Gemini via Vertex AI `generateContent` REST endpoint."""

    name = "gemini"
    DEFAULT_TIMEOUT = 60

    def __init__(self, model: str = "gemini-2.5-flash", auth: VertexAuth | None = None,
                 timeout: int = DEFAULT_TIMEOUT):
        self.model = model
        self.auth = auth or default_vertex_auth()
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
        }
        resp = requests.post(
            vertex_url(self.auth, self.model),
            headers={
                "Authorization": f"Bearer {self.auth.get_token()}",
                "Content-Type": "application/json",
            },
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
        ...


class GeminiAgentProvider:
    """Gemini with function-calling for curator web-search verification (Vertex AI)."""

    name = "gemini-agent"
    DEFAULT_TIMEOUT = 60

    def __init__(self, model: str = "gemini-2.5-flash", auth: VertexAuth | None = None,
                 timeout: int = DEFAULT_TIMEOUT, tavily_provider: object | None = None):
        self.model = model
        self.auth = auth or default_vertex_auth()
        self.timeout = timeout
        self._tavily_provider = tavily_provider

    def _get_tavily_provider(self):
        if self._tavily_provider is None:
            from el import tavily
            self._tavily_provider = tavily.default_provider()
        return self._tavily_provider

    def call_with_tools(self, system: str, user: str, tools: list[dict], max_turns: int = 5) -> str:
        url = vertex_url(self.auth, self.model)
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
                headers={
                    "Authorization": f"Bearer {self.auth.get_token()}",
                    "Content-Type": "application/json",
                },
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

            tool_calls = [p for p in parts if isinstance(p, dict) and "functionCall" in p]
            if not tool_calls:
                text_parts = [p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p]
                return "".join(text_parts)

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

            contents.append({"role": "model", "parts": parts})
            contents.append({"role": "user", "parts": tool_results})

        log.warning("Curator agent loop reached max turns (%d)", max_turns)
        return ""

    def _execute_web_search(self, query: str) -> dict:
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
    return GeminiProvider()


def default_agent_provider() -> LLMAgentProvider:
    return GeminiAgentProvider()
