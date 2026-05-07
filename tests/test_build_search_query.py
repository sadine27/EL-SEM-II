"""Tests for el/nodes/build_search_query.py."""
from __future__ import annotations

from el.nodes import build_search_query as bsq


def test_clean_keyword_prefers_search_query_in():
    assert bsq.clean_keyword({
        "search_query_in": "Wireless Earbuds!!! India under 1000 best deals now",
        "suggested_product_type": "ignored",
    }) == "wireless earbuds india under 1000 best"


def test_clean_keyword_falls_back_to_parenthetical_product_type():
    assert bsq.clean_keyword({
        "suggested_product_type": "Themed accessories (IPL CSK jersey cap)",
        "topic": "ignored",
    }) == "ipl csk jersey"


def test_clean_keyword_removes_legacy_filler_words():
    assert bsq.clean_keyword({
        "suggested_product_type": "official movie merchandise t shirt apparel",
    }) == "shirt"


def test_build_query_maps_n8n_output_shape():
    query = bsq.build_query({
        "run_date": "2026-05-07",
        "rank": 2,
        "topic": "IPL merch",
        "opportunity_score": 8.2,
        "search_query_in": "ipl csk jersey",
    })
    assert query == {
        "keyword": "ipl csk jersey",
        "source_topic": "IPL merch",
        "source_pick_rank": 2,
        "opportunity_score": 8.2,
        "run_date": "2026-05-07",
    }


def test_build_query_skips_error_rows():
    assert bsq.build_query({"error": "No picks parsed", "raw": "bad"}) is None


def test_build_query_skips_empty_keyword():
    assert bsq.build_query({"topic": ""}) is None


def test_run_builds_queries_from_curated_picks():
    ctx = bsq.run({
        "curated_picks": [
            {"topic": "T1", "rank": 1, "search_query_in": "wireless earbuds"},
            {"error": "No picks parsed"},
            {"topic": "T2", "rank": 2, "suggested_product_type": "phone case"},
        ]
    })
    assert ctx["cj_search_queries"] == [
        {
            "keyword": "wireless earbuds",
            "source_topic": "T1",
            "source_pick_rank": 1,
            "opportunity_score": None,
            "run_date": ctx["cj_search_queries"][0]["run_date"],
        },
        {
            "keyword": "phone case",
            "source_topic": "T2",
            "source_pick_rank": 2,
            "opportunity_score": None,
            "run_date": ctx["cj_search_queries"][1]["run_date"],
        },
    ]
    assert len(ctx["cj_search_queries"][0]["run_date"]) == 10
