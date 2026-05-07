"""Tests for el/nodes/parse_agent_output.py."""
from __future__ import annotations

from el.nodes import parse_agent_output as pao


def test_parses_valid_json_array():
    ctx = {
        "ranked_payload": [
            {
                "json": {
                    "output": 'Here are the top picks: [{"rank": 1, "product": "Item A"}, {"rank": 2, "product": "Item B"}]'
                }
            }
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 2
    assert ctx["parsed_agent_picks"][0]["rank"] == 1
    assert ctx["parsed_agent_picks"][1]["rank"] == 2


def test_handles_malformed_json():
    ctx = {
        "ranked_payload": [
            {
                "json": {
                    "output": 'Picks: [{"rank": 1, "product": "Item A", invalid json}]'
                }
            }
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 1
    assert "error" in ctx["parsed_agent_picks"][0]
    assert "JSON parse failed" in ctx["parsed_agent_picks"][0]["error"]


def test_handles_missing_json_array():
    ctx = {
        "ranked_payload": [
            {
                "json": {
                    "output": "No picks were found in this search."
                }
            }
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 1
    assert "error" in ctx["parsed_agent_picks"][0]
    assert "No picks parsed" in ctx["parsed_agent_picks"][0]["error"]


def test_handles_empty_output():
    ctx = {
        "ranked_payload": [{"json": {"output": ""}}],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 0


def test_stamps_run_date():
    ctx = {
        "ranked_payload": [
            {
                "json": {
                    "output": '[{"rank": 1, "category": "Marvel"}]'
                }
            }
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert ctx["parsed_agent_picks"][0]["run_date"] == "2026-05-07"
