"""Tests for wiring Sentinel-vetted picks into the HIL review pool."""
from __future__ import annotations

import json

from el import pipeline
from el.nodes import (
    merge_review_sources,
    normalize_sentinel_review,
    phase4_candidate_selection,
)


# --------------------------------------------------------------------------- #
# builders                                                                    #
# --------------------------------------------------------------------------- #
def _sentinel_match(**overrides) -> dict:
    base = {
        "title": "Wireless Earbuds Pro",
        "source_id": "cj",
        "supplier_product_id": "PID1",
        "product_url": "https://cjdropshipping.com/product/earbuds-1",
        "image_url": "https://img.cj.com/earbuds-1.jpg",
        "currency": "USD",
        "stock": 50,
        "rating": 4.6,
        "landed_cost": 10.0,
        "match_score": 0.82,
        "sentinel_score": 0.8,
        "sentinel_decision": "pass",
        "sentinel_warnings": [],
        "sentinel_rejection_reasons": [],
        "projected_sell_price": 22.0,
        "projected_margin_pct": 0.55,
    }
    base.update(overrides)
    return base


def _sentinel_ctx(matches, *, query="wireless earbuds") -> dict:
    return {
        "sentinel_matches": [
            {"trend": {"topic": query, "rank": 1}, "query": query, "matches": matches,
             "rejected": [], "summary": {"evaluated": len(matches), "passed": len(matches), "rejected": 0}}
        ]
    }


# --------------------------------------------------------------------------- #
# normalize_sentinel_review                                                   #
# --------------------------------------------------------------------------- #
def test_normalize_maps_passing_match_to_hil_contract():
    ctx = _sentinel_ctx([_sentinel_match()])
    normalize_sentinel_review.run(ctx, now_iso="2026-06-02T00:00:00Z", execution_id="exec1")
    rows = ctx["sentinel_review_items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["review_schema_version"] == "hil_v1"
    assert row["source_provider"] == "forge_sentinel"
    assert row["source_topic"] == "wireless earbuds"
    assert row["product_name"] == "Wireless Earbuds Pro"
    assert row["product_url"] == "https://cjdropshipping.com/product/earbuds-1"
    assert row["price_numeric"] == 22.0
    assert row["availability_status"] == "in_stock"
    # sentinel_score (0.8) maps to opportunity on a 0..10 scale
    assert row["opportunity_score"] == 8.0
    assert row["source_pick_rank"] == 1
    # raw_payload carries the sentinel provenance
    raw = json.loads(row["raw_payload"])
    assert raw["source"] == "forge_sentinel"
    assert raw["sentinel_score"] == 0.8


def test_normalize_drops_non_passing_and_incomplete():
    ctx = _sentinel_ctx([
        _sentinel_match(sentinel_decision="reject"),
        _sentinel_match(title=""),
        _sentinel_match(product_url=None),
    ])
    normalize_sentinel_review.run(ctx)
    assert ctx["sentinel_review_items"] == []


def test_normalize_unknown_stock_marks_availability_unknown():
    ctx = _sentinel_ctx([_sentinel_match(stock=None)])
    normalize_sentinel_review.run(ctx)
    assert ctx["sentinel_review_items"][0]["availability_status"] == "unknown"


def test_normalize_empty_when_no_sentinel_matches():
    ctx = {}
    normalize_sentinel_review.run(ctx)
    assert ctx["sentinel_review_items"] == []


# --------------------------------------------------------------------------- #
# merge_review_sources                                                        #
# --------------------------------------------------------------------------- #
def test_merge_includes_sentinel_items():
    ctx = {
        "cj_review_items": [{"product_name": "CJ thing"}],
        "sentinel_review_items": [{"product_name": "Sentinel thing"}],
    }
    merge_review_sources.run(ctx)
    names = [r["product_name"] for r in ctx["review_candidates"]]
    assert names == ["CJ thing", "Sentinel thing"]


# --------------------------------------------------------------------------- #
# phase4: a vetted row clears the gate, and the provider is capped            #
# --------------------------------------------------------------------------- #
def test_vetted_row_passes_phase4_score_gate_and_is_selected():
    ctx = _sentinel_ctx([_sentinel_match()])
    normalize_sentinel_review.run(ctx)
    merge_review_sources.run(ctx)
    phase4_candidate_selection.run(ctx)
    selected = ctx["phase4_candidates"]
    assert any(r.get("source_provider") == "forge_sentinel" for r in selected)


def test_phase4_caps_forge_sentinel_provider():
    matches = [
        _sentinel_match(
            title=f"Wireless Earbuds Model {i}",
            product_url=f"https://cjdropshipping.com/product/earbuds-{i}",
            image_url=f"https://img.cj.com/earbuds-{i}.jpg",
        )
        for i in range(8)
    ]
    ctx = _sentinel_ctx(matches)
    normalize_sentinel_review.run(ctx)
    merge_review_sources.run(ctx)
    phase4_candidate_selection.run(ctx)
    sentinel_selected = [r for r in ctx["phase4_candidates"] if r.get("source_provider") == "forge_sentinel"]
    assert len(sentinel_selected) <= phase4_candidate_selection.SENTINEL_PROVIDER_CAP


# --------------------------------------------------------------------------- #
# pipeline gate                                                               #
# --------------------------------------------------------------------------- #
def test_forge_pipeline_enabled_default_on(monkeypatch):
    monkeypatch.delenv("EL_FORGE_PIPELINE_ENABLED", raising=False)
    assert pipeline._forge_pipeline_enabled() is True


def test_forge_pipeline_can_be_disabled(monkeypatch):
    monkeypatch.setenv("EL_FORGE_PIPELINE_ENABLED", "false")
    assert pipeline._forge_pipeline_enabled() is False
