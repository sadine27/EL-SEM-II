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


# --------------------------------------------------------------------------- #
# pipeline.run() integration: normalized sentinel items reach review_candidates #
# --------------------------------------------------------------------------- #
def test_pipeline_run_forge_sentinel_bridge(monkeypatch):
    """Verify pipeline.run() wires normalize_sentinel_review + re-merge so
    Sentinel-vetted picks appear in ctx["review_candidates"] and
    ctx["phase4_candidates"] after Step 6."""
    from el.suppliers import SupplierCandidate

    # Disable all real sources and downstream nodes that need creds.
    monkeypatch.setattr(pipeline, "_load_enabled_sources", lambda: [])
    # Disable score_rank's inline RSS fetch.
    monkeypatch.setattr(pipeline.score_rank, "fetch_news_rss", lambda: [])
    # Disable CJ nodes so they don't try real API calls.
    monkeypatch.setattr(pipeline.cj_get_token, "run", lambda ctx: ctx)
    monkeypatch.setattr(pipeline.cj_product_list, "run", lambda ctx: ctx)
    # Disable all other downstream nodes.
    for name in (
        "embed_candidate_products", "create_day_tab", "prepare_sheet_rows",
        "write_rows_to_sheet", "drive_upload", "create_curated_picks_tab",
        "curate_picks", "build_search_query", "write_curated_picks",
        "download_product_image", "prepare_telegram_card",
        "email_digest", "email_product_detail", "notify_business",
        "record_niche_performance", "generate_shopify_theme",
        "upload_shopify_theme", "upload_shopify_products",
    ):
        monkeypatch.setattr(getattr(pipeline, name), "run", lambda ctx: ctx)

    # Populate supplier_matches directly (as if supplier_search already ran).
    sentinel_pass = {
        "title": "Wireless Earbuds Pro",
        "source_id": "cj",
        "supplier_product_id": "PID1",
        "product_url": "https://cjdropshipping.com/product/earbuds-1",
        "image_url": "https://img.cj.com/earbuds-1.jpg",
        "currency": "USD",
        "stock": 50,
        "rating": 4.6,
        "cost": 10.0,
        "shipping_cost": 2.0,
        "landed_cost": 12.0,
        "match_score": 0.82,
    }

    # We need to stub out supplier_search.run() to set supplier_matches, then
    # the real sentinel_vetting, normalize_sentinel_review, merge, phase4 should
    # all fire. To avoid sentinel_vetting needing real env config, stub its run.
    # Instead, let's feed sentinel_matches directly and let the rest flow.
    # Actually, the cleanest approach is to monkeypatch sentinel_vetting.run too,
    # but then we wouldn't test the bridge. Let's set sentinel_matches directly
    # and feed sentinel_review_items, then let merge + phase4 consume them.
    # But the point is to test pipeline.run()'s code path. Let me just inject
    # sentinel_matches into ctx before the pipeline reaches Step 5.

    # Strategy: monkeypatch supplier_search.run to write sentinel_matches directly
    def _fake_supplier_search(ctx):
        ctx["supplier_matches"] = [
            {"trend": {"topic": "wireless earbuds", "rank": 1},
             "query": "wireless earbuds",
             "matches": [dict(sentinel_pass)]}
        ]
        return ctx

    monkeypatch.setattr(pipeline.supplier_search, "run", _fake_supplier_search)

    # sentinel_vetting — keep real (it's gated by EL_SENTINEL_ENABLED which defaults true)
    # normalize_sentinel_review — keep real
    # merge_review_sources — keep real
    # phase4_candidate_selection — keep real but needs ai_score_trends to not crash
    monkeypatch.setattr(pipeline.ai_score_trends, "run", lambda ctx: ctx)
    monkeypatch.setattr(pipeline.filter_top_30, "run", lambda ctx: ctx)

    ctx = pipeline.run({})

    # After Step 6, phase4_candidates should exist and contain the forge_sentinel item
    selected = ctx.get("phase4_candidates", [])
    sentinel_items = [r for r in selected if r.get("source_provider") == "forge_sentinel"]
    assert len(sentinel_items) >= 1, (
        f"Expected at least one forge_sentinel item in phase4_candidates, "
        f"got {len(sentinel_items)} out of {len(selected)} total. "
        f"review_candidates={len(ctx.get('review_candidates', []))}, "
        f"sentinel_review_items={len(ctx.get('sentinel_review_items', []))}"
    )
    assert sentinel_items[0]["product_name"] == "Wireless Earbuds Pro"
    assert sentinel_items[0]["source_provider"] == "forge_sentinel"
    assert sentinel_items[0]["opportunity_score"] > 0
    assert sentinel_items[0]["source_topic"] == "wireless earbuds"
