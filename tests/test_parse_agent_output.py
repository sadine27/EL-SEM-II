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


def test_handles_nested_arrays_in_picks():
    """Nested arrays inside the top-level array must not truncate the match.

    Regression: a non-greedy `\\[.*?\\]` regex would stop at the first inner
    `]` (e.g. inside a "tags" field), losing the rest of the picks.
    """
    ctx = {
        "ranked_payload": [
            {
                "json": {
                    "output": (
                        'Picks: [{"rank": 1, "tags": ["a", "b"]}, '
                        '{"rank": 2, "tags": ["c"]}]'
                    )
                }
            }
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 2
    assert ctx["parsed_agent_picks"][0]["tags"] == ["a", "b"]
    assert ctx["parsed_agent_picks"][1]["rank"] == 2


def test_handles_empty_ranked_payload_list():
    """Empty list must not IndexError."""
    ctx = {"ranked_payload": [], "filter_top30_result": {"run_date": "2026-05-07"}}
    pao.run(ctx)
    assert ctx["parsed_agent_picks"] == []


def test_picks_first_of_multiple_arrays():
    """When LLM emits two arrays, parser must return the FIRST balanced one.

    Regression: a greedy `\\[.*\\]` regex would span both arrays and fail
    JSON parsing. The balanced-bracket extractor stops at the first matching
    ']'.
    """
    ctx = {
        "ranked_payload": [
            {"json": {"output": '[{"rank":1}] and also [{"rank":2}]'}}
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 1
    assert ctx["parsed_agent_picks"][0]["rank"] == 1


def test_brackets_inside_strings_are_ignored():
    """A '[' or ']' inside a JSON string must not affect bracket depth."""
    ctx = {
        "ranked_payload": [
            {"json": {"output": '[{"name":"foo [bar] baz","rank":1}]'}}
        ],
        "filter_top30_result": {"run_date": "2026-05-07"},
    }
    pao.run(ctx)
    assert len(ctx["parsed_agent_picks"]) == 1
    assert ctx["parsed_agent_picks"][0]["name"] == "foo [bar] baz"


def test_handles_non_dict_payload_item():
    """Malformed payload items (e.g. None) must not crash."""
    ctx = {"ranked_payload": [None], "filter_top30_result": {}}
    pao.run(ctx)
    assert ctx["parsed_agent_picks"] == []


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
