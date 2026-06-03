"""End-to-end SP1 integration: phase4 → stochastic_logger → hil_reviews insert.

External IO mocked. Verifies the full ctx contract between the three nodes
that SP1 touches.
"""
from __future__ import annotations

import json

from el.nodes import (
    phase4_candidate_selection,
    stochastic_logger,
    supabase_insert_hil_reviews,
)


class _UnifiedFakeProvider:
    """Single fake implementing both insert_rows (logging events)
    and upsert_rows (hil_reviews)."""

    def __init__(self):
        self.inserts: list[dict] = []
        self.upserts: list[dict] = []

    def insert_rows(self, *, schema, table, rows):
        self.inserts.append({"schema": schema, "table": table, "rows": rows})
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]

    def upsert_rows(self, *, schema, table, rows, conflict_columns, resolution="merge-duplicates"):
        self.upserts.append({
            "schema": schema, "table": table, "rows": rows,
            "conflict_columns": conflict_columns, "resolution": resolution,
        })
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _candidate(idx: int, topic: str | None = None) -> dict:
    raw_payload = {
        "source": "cj_dropshipping",
        "offer": {"listedNum": 20, "categoryName": "Collectibles"},
        "raw_payload": {"pid": f"PID{idx}", "productNameEn": f"Wireless Earbuds {idx}"},
    }
    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": "EL:2026-05-10:test",
        "run_date": "2026-05-10",
        "source_provider": "cj_dropshipping",
        "source_topic": topic if topic is not None else f"Wireless Earbuds {idx}",
        "source_pick_rank": 1,
        "opportunity_score": 8.5,
        "product_name": f"Wireless Earbuds Pro {idx}",
        "product_url": f"https://app.cjdropshipping.com/product/PID{idx}.html",
        "product_sku": f"SKU{idx}",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": f"https://img.example/{idx}.jpg",
        "image_urls": json.dumps([f"https://img.example/{idx}.jpg"]),
        "description": "Bluetooth earbuds with compact charging case",
        "supplier_name": "Supplier",
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": json.dumps(raw_payload),
        "scraped_at": "2026-05-10T10:00:00Z",
    }


def test_end_to_end_pipeline_writes_logging_rows_and_stamps_reviews(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "1")

    # 12 candidates with distinct topics so phase4 dedupe doesn't collapse them.
    # phase4 TOTAL_CAP=10 trims to 10; eligible_pool=12. Pool > slate → greedy at ε=0.
    rows = [_candidate(i) for i in range(12)]
    ctx = {"review_candidates": rows}

    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    assert "phase4_candidates" in ctx and "eligible_pool" in ctx
    assert len(ctx["phase4_candidates"]) >= 1
    assert len(ctx["eligible_pool"]) > len(ctx["phase4_candidates"])

    provider = _UnifiedFakeProvider()
    stochastic_logger.run(ctx, provider=provider)
    assert ctx["logging_event_id"] != ""
    assert ctx["hil_slate_branch"] == "greedy"

    inserted = provider.inserts[0]["rows"]
    assert len(inserted) == len(ctx["phase4_candidates"])
    for row in inserted:
        assert row["propensity"] == 1.0
        assert row["was_shown"] is True
        assert row["branch"] == "greedy"
        assert row["event_id"] == ctx["logging_event_id"]

    supabase_insert_hil_reviews.run(ctx, provider=provider)

    upserted = provider.upserts[0]["rows"]
    assert len(upserted) == len(ctx["phase4_candidates"])
    for row in upserted:
        assert row["logging_event_id"] == ctx["logging_event_id"]


def test_end_to_end_explore_branch_logs_full_pool(monkeypatch):
    """ε=1 forces explore branch; every eligible_pool item must be logged."""
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "1.0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "13")

    rows = [_candidate(i) for i in range(15)]
    ctx = {"review_candidates": rows}

    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    pool_size = len(ctx["eligible_pool"])

    provider = _UnifiedFakeProvider()
    stochastic_logger.run(ctx, provider=provider)

    if ctx["hil_slate_branch"] == "degenerate":
        inserted = provider.inserts[0]["rows"]
        assert len(inserted) == pool_size
    else:
        assert ctx["hil_slate_branch"] == "explore"
        inserted = provider.inserts[0]["rows"]
        assert len(inserted) == pool_size
        out_greedy_shown = [r for r in inserted if not r["in_greedy_slate"] and r["was_shown"]]
        assert len(out_greedy_shown) > 0
