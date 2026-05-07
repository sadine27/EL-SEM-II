"""Tests for el/nodes/merge_review_sources.py."""
from __future__ import annotations

from el.nodes import merge_review_sources


def test_merge_review_sources_combines_cj_and_browserbase_items_in_order():
    ctx = merge_review_sources.run({
        "cj_review_items": [{"product_url": "cj-1"}, {"product_url": "cj-2"}],
        "browserbase_review_items": [{"product_url": "bb-1"}],
    })

    assert ctx["review_candidates"] == [
        {"product_url": "cj-1"},
        {"product_url": "cj-2"},
        {"product_url": "bb-1"},
    ]


def test_merge_review_sources_handles_missing_future_branch():
    ctx = merge_review_sources.run({
        "cj_review_items": [{"product_url": "cj-1"}],
    })

    assert ctx["review_candidates"] == [{"product_url": "cj-1"}]


def test_merge_review_sources_ignores_non_dict_items():
    ctx = merge_review_sources.run({
        "cj_review_items": [{"product_url": "cj-1"}, "bad"],
        "browserbase_review_items": None,
    })

    assert ctx["review_candidates"] == [{"product_url": "cj-1"}]
