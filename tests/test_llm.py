"""Tests for el/llm.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from el import llm


def _fake_response(json_payload: dict, ok: bool = True, status_code: int = 200):
    resp = MagicMock(spec=requests.Response)
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_payload
    if not ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_gemini_provider_calls_expected_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    payload = {
        "candidates": [{"content": {"parts": [{"text": "hello"}]}}]
    }
    with patch.object(llm.requests, "post") as mock_post:
        mock_post.return_value = _fake_response(payload)
        out = llm.GeminiProvider().generate("sys", "user")
        url, = mock_post.call_args.args
        kwargs = mock_post.call_args.kwargs
    assert "generativelanguage.googleapis.com" in url
    assert "gemini-2.5-flash:generateContent" in url
    assert kwargs["params"]["key"] == "TESTKEY"
    body = kwargs["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["contents"][0]["parts"][0]["text"] == "user"
    assert out == "hello"


def test_gemini_provider_concatenates_multiple_parts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    payload = {
        "candidates": [{"content": {"parts": [
            {"text": "part1 "}, {"text": "part2"}
        ]}}]
    }
    with patch.object(llm.requests, "post") as mock_post:
        mock_post.return_value = _fake_response(payload)
        out = llm.GeminiProvider().generate("s", "u")
    assert out == "part1 part2"


def test_gemini_provider_handles_empty_candidates(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    with patch.object(llm.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({"candidates": []})
        out = llm.GeminiProvider().generate("s", "u")
    assert out == ""


def test_gemini_provider_propagates_http_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    with patch.object(llm.requests, "post") as mock_post:
        mock_post.return_value = _fake_response({}, ok=False, status_code=429)
        with pytest.raises(requests.HTTPError):
            llm.GeminiProvider().generate("s", "u")


def test_gemini_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.GeminiProvider()


def test_gemini_provider_accepts_explicit_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    p = llm.GeminiProvider(api_key="DIRECT")
    assert p.api_key == "DIRECT"


def test_default_provider_returns_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    p = llm.default_provider()
    assert p.name == "gemini"


def test_gemini_agent_provider_no_tool_use_returns_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    monkeypatch.setenv("TAVILY_API_KEY", "TAVILY_KEY")
    payload = {
        "candidates": [{"content": {"parts": [{"text": "Final answer"}]}}]
    }
    with patch.object(llm.requests, "post") as mock_post:
        mock_post.return_value = _fake_response(payload)
        agent = llm.GeminiAgentProvider()
        out = agent.call_with_tools("sys", "user", [{"name": "web_search"}])
    assert out == "Final answer"
    assert mock_post.call_count == 1


def test_gemini_agent_provider_tool_call_executes_web_search(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    monkeypatch.setenv("TAVILY_API_KEY", "TAVILY_KEY")

    turn1_payload = {
        "candidates": [{
            "content": {"parts": [
                {"functionCall": {
                    "name": "web_search",
                    "args": {"query": "wireless earbuds india market"}
                }}
            ]}
        }]
    }
    turn2_payload = {
        "candidates": [{
            "content": {"parts": [{"text": "High demand found"}]}
        }]
    }

    call_count = [0]
    def fake_post(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return _fake_response(turn1_payload)
        else:
            return _fake_response(turn2_payload)

    fake_tavily = MagicMock()
    fake_tavily.search.return_value = {
        "ok": True,
        "answer": "Growing market",
        "results": [{"title": "News", "url": "http://example.com"}],
    }

    with patch.object(llm.requests, "post", side_effect=fake_post):
        agent = llm.GeminiAgentProvider(tavily_provider=fake_tavily)
        out = agent.call_with_tools("sys", "user", [{"name": "web_search"}], max_turns=3)

    assert out == "High demand found"
    assert call_count[0] == 2
    fake_tavily.search.assert_called_once()


def test_default_agent_provider_returns_gemini_agent(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "TESTKEY")
    monkeypatch.setenv("TAVILY_API_KEY", "TAVILY_KEY")
    p = llm.default_agent_provider()
    assert p.name == "gemini-agent"
