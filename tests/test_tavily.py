"""Tests for el/tavily.py."""
from __future__ import annotations

from el import tavily


class FakeTavilyResponse:
    def __init__(self, ok=True, results=None, answer=""):
        self.ok = ok
        self.results = results or []
        self.answer = answer
        self.status_code = 200 if ok else 500
        self.text = "" if ok else "error"

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP error")

    def json(self):
        if self.ok:
            return {
                "answer": self.answer,
                "results": self.results,
            }
        raise RuntimeError("JSON error")


def test_tavily_search_successful_query(monkeypatch):
    results = [
        {"title": "Wireless Earbuds", "url": "https://example.com/1", "content": "Popular in 2026"},
        {"title": "Reviews", "url": "https://example.com/2", "content": "Great reviews"},
    ]
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def fake_post(url, json=None, timeout=None):
        return FakeTavilyResponse(ok=True, results=results, answer="High demand")

    monkeypatch.setattr("requests.post", fake_post)
    provider = tavily.TavilySearchProvider(api_key="test-key")
    result = provider.search("wireless earbuds india")

    assert result["ok"] is True
    assert result["query"] == "wireless earbuds india"
    assert result["answer"] == "High demand"
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "Wireless Earbuds"
    assert result["results"][0]["url"] == "https://example.com/1"


def test_tavily_search_error_handling(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")

    def fake_post(url, json=None, timeout=None):
        raise RuntimeError("Connection timeout")

    monkeypatch.setattr("requests.post", fake_post)
    provider = tavily.TavilySearchProvider(api_key="test-key")
    result = provider.search("test query")

    assert result["ok"] is False
    assert result["error"] == "Connection timeout"
    assert result["results"] == []


def test_tavily_requires_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    try:
        tavily.TavilySearchProvider()
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "TAVILY_API_KEY" in str(e)
