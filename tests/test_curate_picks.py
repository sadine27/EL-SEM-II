"""Tests for el/nodes/curate_picks.py."""
from __future__ import annotations

import json

from el.nodes import curate_picks as cp


class FakeProvider:
    name = "fake"

    def __init__(self, output: str = ""):
        self.output = output
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.output


def _picks_json(n: int = 2) -> str:
    return json.dumps([
        {"rank": i + 1, "topic": f"t{i}", "opportunity_score": 8.0,
         "reason": "r", "suggested_product_type": "p",
         "target_audience": "a", "search_query_in": "q"}
        for i in range(n)
    ])


def test_parse_agent_output_extracts_json_array():
    raw = "Here are picks: " + _picks_json(2) + "\nDone."
    picks = cp.parse_agent_output(raw, "2026-05-07")
    assert len(picks) == 2
    assert picks[0]["run_date"] == "2026-05-07"
    assert picks[0]["topic"] == "t0"


def test_parse_agent_output_handles_pure_array():
    raw = _picks_json(3)
    picks = cp.parse_agent_output(raw, "2026-05-07")
    assert len(picks) == 3


def test_parse_agent_output_returns_error_on_no_array():
    picks = cp.parse_agent_output("totally not json", "2026-05-07")
    assert len(picks) == 1
    assert picks[0]["error"] == "No picks parsed"
    assert picks[0]["raw"] == "totally not json"
    assert picks[0]["run_date"] == "2026-05-07"


def test_parse_agent_output_returns_error_on_invalid_json():
    picks = cp.parse_agent_output("[not, valid, json,]", "2026-05-07")
    assert picks[0]["error"] == "No picks parsed"


def test_parse_agent_output_returns_error_on_empty_array():
    picks = cp.parse_agent_output("[]", "2026-05-07")
    assert picks[0]["error"] == "No picks parsed"


def test_parse_agent_output_truncates_long_raw():
    raw = "x" * 1000
    picks = cp.parse_agent_output(raw, "2026-05-07")
    assert len(picks[0]["raw"]) == 500


def test_run_calls_provider_with_system_and_topics():
    fake = FakeProvider(output=_picks_json(1))
    ctx = {"filtered": {
        "topics_text": '1. "x" | intent:0.5 | cats:electronics | src:yt',
        "run_date": "2026-05-07", "total": 1,
    }}
    cp.run(ctx, provider=fake)
    assert len(fake.calls) == 1
    system, user = fake.calls[0]
    assert "dropshipping product curator" in system
    assert "Today's date is" in system
    assert user == '1. "x" | intent:0.5 | cats:electronics | src:yt'


def test_run_attaches_run_date_to_picks():
    fake = FakeProvider(output=_picks_json(2))
    ctx = {"filtered": {"topics_text": "1. x", "run_date": "2026-05-07", "total": 1}}
    cp.run(ctx, provider=fake)
    assert all(p["run_date"] == "2026-05-07" for p in ctx["curated_picks"])


def test_run_skips_when_no_topics_text():
    fake = FakeProvider(output="should not be called")
    ctx = {"filtered": {"topics_text": "", "run_date": "2026-05-07", "total": 0}}
    cp.run(ctx, provider=fake)
    assert ctx["curated_picks"] == []
    assert fake.calls == []


def test_run_skips_when_filtered_missing():
    fake = FakeProvider(output="x")
    ctx: dict = {}
    cp.run(ctx, provider=fake)
    assert ctx["curated_picks"] == []
    assert fake.calls == []


def test_run_falls_back_when_parse_fails():
    fake = FakeProvider(output="model said no JSON here")
    ctx = {"filtered": {"topics_text": "1. x", "run_date": "2026-05-07", "total": 1}}
    cp.run(ctx, provider=fake)
    assert ctx["curated_picks"][0]["error"] == "No picks parsed"
