"""Tests for el/nodes/embed_candidate_products.py."""
from __future__ import annotations

import json

import pytest

from el import embeddings
from el.nodes import embed_candidate_products


class _CapturingDB:
    def __init__(self, existing: list[dict] | None = None):
        self.upsert_calls: list[dict] = []
        self.select_calls: list[dict] = []
        self._existing = existing or []

    def select_rows(self, *, schema, table, filters, select="*", limit=None):
        self.select_calls.append({
            "schema": schema, "table": table, "select": select, "filters": filters,
        })
        # filters: {"product_key": "in.(k1,k2)"} — parse the in.() value
        raw = filters.get("product_key", "")
        if raw.startswith("in.(") and raw.endswith(")"):
            keys = {k.strip().strip('"') for k in raw[4:-1].split(",") if k.strip()}
        else:
            keys = {raw} if raw else set()
        return [r for r in self._existing if r["product_key"] in keys]

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        self.upsert_calls.append({
            "schema": schema, "table": table, "rows": rows,
            "conflict_columns": conflict_columns,
        })
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _candidate(idx: int, with_image: bool = True) -> dict:
    images = [f"https://img.example/{idx}-a.jpg", f"https://img.example/{idx}-b.jpg"] if with_image else []
    return {
        "source_provider": "cj_dropshipping",
        "product_name": f"Wireless Earbuds {idx}",
        "product_url": f"https://app.cjdropshipping.com/product/PID{idx}.html",
        "product_sku": f"SKU{idx}",
        "image_urls": json.dumps(images),
    }


# -- master kill switch --------------------------------------------------------

def test_disabled_flag_passthrough(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "false")
    db = _CapturingDB()
    provider = embeddings.FakeEmbeddingProvider()
    ctx = {"cj_top_products": [_candidate(0), _candidate(1)]}

    embed_candidate_products.run(ctx, provider=provider, db_provider=db)

    assert ctx["embeddings_result"]["ok"] is True
    assert ctx["embeddings_result"]["embedded_n"] == 0
    assert ctx["embeddings_result"]["skipped_n"] == 2
    assert db.upsert_calls == []


# -- empty input ---------------------------------------------------------------

def test_empty_cj_top_products(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    db = _CapturingDB()
    ctx = {"cj_top_products": []}

    embed_candidate_products.run(ctx, provider=embeddings.FakeEmbeddingProvider(), db_provider=db)

    assert ctx["embeddings_result"]["ok"] is True
    assert ctx["embeddings_result"]["embedded_n"] == 0
    assert db.upsert_calls == []


# -- happy path ----------------------------------------------------------------

def test_embeds_each_candidate_with_text_and_image(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    db = _CapturingDB()
    provider = embeddings.FakeEmbeddingProvider()
    ctx = {"cj_top_products": [_candidate(0), _candidate(1)]}

    embed_candidate_products.run(ctx, provider=provider, db_provider=db)

    assert ctx["embeddings_result"]["embedded_n"] == 2
    upserted = db.upsert_calls[0]["rows"]
    assert len(upserted) == 2
    for row in upserted:
        assert "text_embedding" in row and len(row["text_embedding"]) == 768
        assert "image_embedding" in row and len(row["image_embedding"]) == 1408
        assert row["raw_payload_hash"]
        assert row["source_provider"] == "cj_dropshipping"


# -- missing image -------------------------------------------------------------

def test_candidate_without_image_skips_image_embedding(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    db = _CapturingDB()
    ctx = {"cj_top_products": [_candidate(0, with_image=False)]}

    embed_candidate_products.run(ctx, provider=embeddings.FakeEmbeddingProvider(), db_provider=db)

    upserted = db.upsert_calls[0]["rows"]
    assert upserted[0]["text_embedding"] is not None
    assert upserted[0]["image_embedding"] is None


# -- hash short-circuit --------------------------------------------------------

def test_hash_match_skips_vertex_call(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    cand = _candidate(0)
    # Pre-compute the expected hash via the module's helper
    product_key = embed_candidate_products._product_key(cand["product_url"])
    h = embed_candidate_products._raw_payload_hash(cand)
    db = _CapturingDB(existing=[{"product_key": product_key, "raw_payload_hash": h}])

    call_count = {"text": 0, "image": 0}

    class _SpyProvider:
        def embed_text(self, text):
            call_count["text"] += 1
            return [0.0] * 768
        def embed_image(self, image_url):
            call_count["image"] += 1
            return [0.0] * 1408

    ctx = {"cj_top_products": [cand]}
    embed_candidate_products.run(ctx, provider=_SpyProvider(), db_provider=db)

    assert call_count == {"text": 0, "image": 0}
    assert ctx["embeddings_result"]["skipped_n"] == 1
    assert ctx["embeddings_result"]["embedded_n"] == 0
    assert db.upsert_calls == []


# -- per-candidate exception isolation ----------------------------------------

def test_provider_exception_on_one_candidate_does_not_kill_others(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    db = _CapturingDB()

    class _PickyProvider:
        def embed_text(self, text):
            if "broken" in text:
                raise embeddings.EmbeddingError("vertex tantrum")
            return [0.0] * 768
        def embed_image(self, image_url):
            return [0.0] * 1408

    bad = _candidate(0); bad["product_name"] = "broken thing"
    good = _candidate(1)
    ctx = {"cj_top_products": [bad, good]}

    embed_candidate_products.run(ctx, provider=_PickyProvider(), db_provider=db)

    assert ctx["embeddings_result"]["embedded_n"] == 1
    assert ctx["embeddings_result"]["failed_n"] == 1
    assert len(db.upsert_calls[0]["rows"]) == 1
    assert db.upsert_calls[0]["rows"][0]["product_url"] == good["product_url"]


# -- db failure is fail-soft ---------------------------------------------------

def test_db_upsert_failure_is_fail_soft(monkeypatch):
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")

    class _BadDB:
        def select_rows(self, **kw): return []
        def upsert_rows(self, **kw): raise RuntimeError("db down")

    ctx = {"cj_top_products": [_candidate(0)]}
    embed_candidate_products.run(ctx, provider=embeddings.FakeEmbeddingProvider(), db_provider=_BadDB())

    assert ctx["embeddings_result"]["ok"] is False
    assert "db down" in ctx["embeddings_result"]["error"]
