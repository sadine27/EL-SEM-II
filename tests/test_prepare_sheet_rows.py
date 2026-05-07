"""Tests for el/nodes/prepare_sheet_rows.py."""
from __future__ import annotations

from el.nodes import prepare_sheet_rows as psr


def test_prepare_sheet_rows_maps_ranked_payload_fields():
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [{
            "rank": 1,
            "topic": "Wireless Earbuds",
            "source": "youtube_trending",
            "traffic_estimate": None,
            "product_intent_score": 0.8,
            "related_queries": ["bluetooth", "best earbuds"],
            "suggested_categories": ["electronics", "accessories"],
        }],
    }}
    psr.run(ctx)
    assert ctx["sheet_rows"] == [{
        "run_date": "2026-05-07",
        "rank": 1,
        "topic": "Wireless Earbuds",
        "source": "youtube_trending",
        "traffic_estimate": "N/A",
        "product_intent_score": 0.8,
        "related_queries": "bluetooth, best earbuds",
        "suggested_categories": "electronics, accessories",
    }]


def test_prepare_sheet_rows_preserves_non_null_traffic_estimate():
    ctx = {"ranked_payload": {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [{"traffic_estimate": "", "related_queries": [],
                    "suggested_categories": []}],
    }}
    psr.run(ctx)
    assert ctx["sheet_rows"][0]["traffic_estimate"] == ""


def test_prepare_sheet_rows_handles_empty_payload():
    ctx: dict = {}
    psr.run(ctx)
    assert ctx["sheet_rows"] == []


def test_sheet_row_columns_match_n8n_output_order():
    assert psr.SHEET_ROW_COLUMNS == (
        "run_date",
        "rank",
        "topic",
        "source",
        "traffic_estimate",
        "product_intent_score",
        "related_queries",
        "suggested_categories",
    )
