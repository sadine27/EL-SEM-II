"""Tests for el/nodes/supabase_insert_scraped.py."""
from __future__ import annotations

import json

from el.nodes import supabase_insert_scraped as sis


class FakeSupabaseProvider:
    def __init__(self, should_error: bool = False):
        self.should_error = should_error
        self.upsert_calls = []

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        self.upsert_calls.append({
            "schema": schema,
            "table": table,
            "rows": rows,
            "conflict_columns": conflict_columns,
        })
        if self.should_error:
            raise Exception("Supabase API error")
        return rows


def test_upserts_to_public_scraped_products():
    provider = FakeSupabaseProvider()
    ctx = {"cj_top_products": [{"product_url": "u1", "source_topic": "t1", "image_urls": json.dumps(["a"])}]}
    sis.run(ctx, provider=provider)
    call = provider.upsert_calls[0]
    assert call["schema"] == "public"
    assert call["table"] == "scraped_products"
    assert call["conflict_columns"] == ("product_url", "source_topic")
    assert call["rows"][0]["image_urls"] == ["a"]


def test_no_rows_short_circuits():
    provider = FakeSupabaseProvider()
    ctx = {"cj_top_products": []}
    sis.run(ctx, provider=provider)
    assert ctx["scraped_upsert_result"]["rows"] == 0
    assert provider.upsert_calls == []


def test_provider_error_soft_fail():
    provider = FakeSupabaseProvider(should_error=True)
    ctx = {"cj_top_products": [{"product_url": "u", "source_topic": "t"}]}
    sis.run(ctx, provider=provider)
    assert ctx["scraped_upsert_result"]["ok"] is False
    assert "error" in ctx["scraped_upsert_result"]


def test_skips_non_dict_rows():
    provider = FakeSupabaseProvider()
    ctx = {"cj_top_products": [None, "x", {"product_url": "u", "source_topic": "t"}]}
    sis.run(ctx, provider=provider)
    assert len(provider.upsert_calls[0]["rows"]) == 1


def test_parses_json_string_fields():
    provider = FakeSupabaseProvider()
    ctx = {"cj_top_products": [{
        "product_url": "u", "source_topic": "t",
        "image_urls": '["a","b"]', "offers": '[{"k":1}]', "raw_payload": '{"x":1}',
    }]}
    sis.run(ctx, provider=provider)
    row = provider.upsert_calls[0]["rows"][0]
    assert row["image_urls"] == ["a", "b"]
    assert row["offers"] == [{"k": 1}]
    assert row["raw_payload"] == {"x": 1}


def test_handles_malformed_json_field():
    """Regression: malformed JSON falls back to default, doesn't crash."""
    provider = FakeSupabaseProvider()
    ctx = {"cj_top_products": [{"product_url": "u", "source_topic": "t", "image_urls": "not-json"}]}
    sis.run(ctx, provider=provider)
    row = provider.upsert_calls[0]["rows"][0]
    assert row["image_urls"] == []
