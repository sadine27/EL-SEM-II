"""Integration smoke tests for representative node chains."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import requests

from el.nodes import (
    curate_picks,
    filter_top_30,
    parse_agent_output,
    score_rank,
    youtube_trending,
)


class FakeLLM:
    name = "fake-llm"

    def generate(self, system: str, user: str) -> str:
        assert "Wireless Earbuds" in user
        return json.dumps([
            {
                "rank": 1,
                "topic": "Wireless Earbuds",
                "opportunity_score": 8.7,
                "reason": "buyer intent",
                "suggested_product_type": "phone case",
                "target_audience": "students",
                "search_query_in": "wireless earbuds case",
            }
        ])


def _response(payload: dict):
    response = MagicMock(spec=requests.Response)
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_trend_to_agent_parse_chain(monkeypatch):
    """Regression: representative all-fake chain must preserve ctx handoffs."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")
    monkeypatch.setattr(youtube_trending.requests, "get", lambda *_, **__: _response({
        "items": [
            {"snippet": {"title": "Wireless Earbuds Price 2026", "tags": ["buy", "wireless"]}},
            {"snippet": {"title": "Movie Trailer", "tags": ["video"]}},
        ]
    }))
    monkeypatch.setattr(score_rank, "fetch_trends_rss", lambda: [])
    monkeypatch.setattr(score_rank, "fetch_news_rss", lambda: [])

    ctx: dict = {}
    youtube_trending.run(ctx)
    score_rank.run(ctx)
    filter_top_30.run(ctx)
    curate_picks.run(ctx, provider=FakeLLM(), agent_provider=None)

    ctx["ranked_payload"] = [{"json": {"output": json.dumps(ctx["curated_picks"])}}]
    ctx["filter_top30_result"] = ctx["filtered"]
    parse_agent_output.run(ctx)

    assert ctx["youtube_trending_result"]["ok"] is True
    assert ctx["filtered"]["total"] >= 1
    assert ctx["curated_picks"][0]["topic"] == "Wireless Earbuds"
    assert ctx["parsed_agent_picks"][0]["search_query_in"] == "wireless earbuds case"

