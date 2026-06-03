"""Tests for el/nodes/supabase_insert_hil_reviews.py."""
from __future__ import annotations

import json

from el.nodes import supabase_insert_hil_reviews


class FakeProvider:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def upsert_rows(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("database down")
        return [{"id": 10, **kwargs["rows"][0]}]


def _row() -> dict:
    return {
        "workflow_run_id": "EL:2026-05-07:manual",
        "source_provider": "cj_dropshipping",
        "source_topic": "Wireless Earbuds",
        "product_url": "https://example.com/product",
        "product_name": "Wireless Earbuds",
        "image_urls": json.dumps(["https://img.example/1.jpg"]),
        "raw_payload": json.dumps({"phase4_selection": {"queue_rank": 1}}),
    }


def test_prepare_row_converts_json_object_fields():
    row = supabase_insert_hil_reviews.prepare_row(_row())

    assert row["image_urls"] == ["https://img.example/1.jpg"]
    assert row["raw_payload"] == {"phase4_selection": {"queue_rank": 1}}


def test_prepare_row_uses_safe_fallbacks_for_bad_json_fields():
    source = _row()
    source["image_urls"] = "{bad"
    source["raw_payload"] = "{bad"

    row = supabase_insert_hil_reviews.prepare_row(source)

    assert row["image_urls"] == []
    assert row["raw_payload"] == {}


def test_prepare_row_fills_missing_scraped_at():
    source = _row()
    source.pop("scraped_at", None)

    row = supabase_insert_hil_reviews.prepare_row(source)

    assert row["scraped_at"].endswith("Z")


def test_supabase_insert_hil_reviews_upserts_phase4_candidates():
    provider = FakeProvider()
    ctx = supabase_insert_hil_reviews.run(
        {"phase4_candidates": [_row()]},
        provider=provider,
    )

    assert provider.calls[0]["schema"] == "private"
    assert provider.calls[0]["table"] == "hil_reviews"
    assert provider.calls[0]["conflict_columns"] == (
        "workflow_run_id",
        "source_provider",
        "source_topic",
        "product_url",
    )
    assert provider.calls[0]["rows"][0]["image_urls"] == ["https://img.example/1.jpg"]
    assert ctx["hil_reviews_upsert_result"]["ok"] is True
    assert ctx["hil_reviews_upsert_result"]["rows"] == 1
    assert ctx["hil_review_rows"][0]["id"] == 10


def test_supabase_insert_hil_reviews_skips_empty_rows():
    provider = FakeProvider()
    ctx = supabase_insert_hil_reviews.run({"phase4_candidates": []}, provider=provider)

    assert provider.calls == []
    assert ctx["hil_reviews_upsert_result"] == {"ok": True, "rows": 0, "data": []}


def test_supabase_insert_hil_reviews_continue_on_fail_shape():
    provider = FakeProvider(fail=True)
    ctx = supabase_insert_hil_reviews.run(
        {"phase4_candidates": [_row()]},
        provider=provider,
    )

    assert ctx["hil_reviews_upsert_result"]["ok"] is False
    assert ctx["hil_reviews_upsert_result"]["rows"] == 1
    assert "database down" in ctx["hil_reviews_upsert_result"]["error"]
    # hil_review_rows set to [] on failure so upload_shopify_products
    # knows HIL is active but has no approved rows (blocks curated_picks fallback).
    assert ctx["hil_review_rows"] == []


# -- SP1 additions: hil_slate source + logging_event_id stamping ---------------

class _CapturingProvider:
    def __init__(self):
        self.upsert_calls: list[dict] = []

    def upsert_rows(self, *, schema: str, table: str, rows: list[dict], conflict_columns, resolution: str = "merge-duplicates"):
        self.upsert_calls.append({
            "schema": schema,
            "table": table,
            "rows": rows,
            "conflict_columns": conflict_columns,
            "resolution": resolution,
        })
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _hil_row(idx: int = 0, **overrides) -> dict:
    base = {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": f"EL:2026-05-10:run{idx}",
        "source_provider": "cj_dropshipping",
        "source_topic": f"Topic {idx}",
        "product_name": f"Product {idx}",
        "product_url": f"https://x/{idx}",
        "image_urls": json.dumps([]),
        "raw_payload": json.dumps({}),
        "approval_status": "pending",
    }
    base.update(overrides)
    return base


def test_insert_reads_from_hil_slate_when_present():
    ctx = {
        "hil_slate": [_hil_row(0), _hil_row(1)],
        "phase4_candidates": [_hil_row(99)],  # should be ignored
        "logging_event_id": "11111111-1111-1111-1111-111111111111",
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    assert len(upserted_rows) == 2
    skus = [r["product_url"] for r in upserted_rows]
    assert "https://x/0" in skus and "https://x/1" in skus
    assert "https://x/99" not in skus


def test_insert_stamps_logging_event_id_on_every_row():
    event_id = "22222222-2222-2222-2222-222222222222"
    ctx = {
        "hil_slate": [_hil_row(0), _hil_row(1)],
        "logging_event_id": event_id,
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    for row in upserted_rows:
        assert row["logging_event_id"] == event_id


def test_insert_omits_logging_event_id_when_empty():
    ctx = {
        "hil_slate": [_hil_row(0)],
        "logging_event_id": "",
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    row = provider.upsert_calls[0]["rows"][0]
    assert "logging_event_id" not in row or row["logging_event_id"] is None


def test_insert_falls_back_to_phase4_candidates_when_hil_slate_missing():
    ctx = {"phase4_candidates": [_hil_row(7)]}
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    assert len(upserted_rows) == 1
    assert upserted_rows[0]["product_url"] == "https://x/7"
