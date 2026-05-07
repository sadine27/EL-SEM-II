"""Tests for el/nodes/filter_top_30.py."""
from __future__ import annotations

from el.nodes import filter_top_30 as ft


def _trend(rank: int, topic: str = "x", score: float = 0.5,
           cats: list[str] | None = None, source: str = "youtube_trending") -> dict:
    return {
        "rank": rank, "topic": topic, "product_intent_score": score,
        "suggested_categories": cats if cats is not None else ["electronics"],
        "source": source,
    }


def test_filter_slices_to_30_and_preserves_order():
    trends = [_trend(i, f"t{i}") for i in range(1, 50)]
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": trends,
    }}
    ft.run(ctx)
    assert ctx["filtered"]["total"] == 30
    assert ctx["filtered"]["topics_text"].splitlines()[0].startswith('1. "t1"')
    assert ctx["filtered"]["topics_text"].splitlines()[-1].startswith('30. "t30"')


def test_filter_extracts_run_date_from_scraped_at():
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [_trend(1)],
    }}
    ft.run(ctx)
    assert ctx["filtered"]["run_date"] == "2026-05-07"


def test_filter_falls_back_to_today_without_scraped_at():
    ctx = {"ranked_payload": {"metadata": {}, "trends": [_trend(1)]}}
    ft.run(ctx)
    rd = ctx["filtered"]["run_date"]
    assert len(rd) == 10 and rd[4] == "-" and rd[7] == "-"


def test_filter_handles_empty_payload():
    ctx: dict = {}
    ft.run(ctx)
    assert ctx["filtered"]["total"] == 0
    assert ctx["filtered"]["topics_text"] == ""


def test_filter_topics_text_format():
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [_trend(1, "Wireless Earbuds", 0.85,
                          ["electronics", "accessories"], "youtube_trending")],
    }}
    ft.run(ctx)
    assert ctx["filtered"]["topics_text"] == (
        '1. "Wireless Earbuds" | intent:0.85 | '
        'cats:electronics,accessories | src:youtube_trending'
    )


def test_filter_handles_missing_categories():
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [{"rank": 1, "topic": "x", "product_intent_score": 0.1,
                    "source": "youtube_trending"}],
    }}
    ft.run(ctx)
    assert "cats: |" in ctx["filtered"]["topics_text"]
