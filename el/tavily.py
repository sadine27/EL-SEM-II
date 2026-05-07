"""Tavily Search API helper for curator product verification."""
from __future__ import annotations

import requests

from el import config
from el.logger import get_logger

log = get_logger(__name__)


class TavilySearchProvider:
    """Tavily Search API — verify product demand in Indian market."""

    BASE_URL = "https://api.tavily.com/search"
    DEFAULT_TIMEOUT = 30

    def __init__(self, api_key: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key or config.require("TAVILY_API_KEY")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 5) -> dict:
        """Search Tavily for query. Returns {results: [{title, url, content}, ...], error?: str}."""
        try:
            body = {
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            }
            resp = requests.post(self.BASE_URL, json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or []
            answer = data.get("answer", "")
            return {
                "ok": True,
                "query": query,
                "answer": answer,
                "results": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", ""),
                    }
                    for r in results
                ],
            }
        except Exception as exc:
            log.warning("Tavily search failed for '%s': %s", query, exc)
            return {
                "ok": False,
                "query": query,
                "error": str(exc),
                "results": [],
            }


def default_provider() -> TavilySearchProvider:
    """Return the configured Tavily provider."""
    return TavilySearchProvider()
