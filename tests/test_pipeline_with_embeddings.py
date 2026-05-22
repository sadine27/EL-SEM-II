"""SP3 pipeline integration: embed_candidate_products runs after pick_top_3."""
from __future__ import annotations

import json

from el import embeddings
from el.nodes import embed_candidate_products


class _CapturingDB:
    def __init__(self):
        self.upsert_calls: list[dict] = []
        self.select_calls: list[dict] = []

    def select_rows(self, **kw):
        self.select_calls.append(kw)
        return []

    def upsert_rows(self, **kw):
        self.upsert_calls.append(kw)
        return [{"id": i + 1, **r} for i, r in enumerate(kw["rows"])]


def _candidate(idx: int) -> dict:
    return {
        "source_provider": "cj_dropshipping",
        "product_name": f"P{idx}",
        "product_url": f"https://x/{idx}",
        "product_sku": f"SKU{idx}",
        "image_urls": json.dumps([f"https://img.example/{idx}.jpg"]),
    }


def test_node_run_directly_with_fakes(monkeypatch):
    """The node must work with fake provider + db; integration of all wiring."""
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "true")
    db = _CapturingDB()
    ctx = {"cj_top_products": [_candidate(0), _candidate(1), _candidate(2)]}

    embed_candidate_products.run(
        ctx, provider=embeddings.FakeEmbeddingProvider(), db_provider=db,
    )

    assert ctx["embeddings_result"]["embedded_n"] == 3
    assert len(db.upsert_calls[0]["rows"]) == 3
    assert db.upsert_calls[0]["table"] == "product_embeddings"
    assert db.upsert_calls[0]["schema"] == "private"
    assert db.upsert_calls[0]["conflict_columns"] == ("product_key",)


def test_pipeline_disabled_flag_makes_node_passthrough(monkeypatch):
    """Pipeline-level: EL_EMBEDDINGS_ENABLED=false skips the embed node call."""
    monkeypatch.setenv("EL_EMBEDDINGS_ENABLED", "false")
    db = _CapturingDB()
    ctx = {"cj_top_products": [_candidate(0)]}

    embed_candidate_products.run(
        ctx, provider=embeddings.FakeEmbeddingProvider(), db_provider=db,
    )

    assert ctx["embeddings_result"]["skipped_n"] == 1
    assert db.upsert_calls == []
