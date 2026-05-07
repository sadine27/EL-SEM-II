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
    assert "hil_review_rows" not in ctx
