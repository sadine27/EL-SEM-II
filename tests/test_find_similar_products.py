"""Tests for el/nodes/find_similar_products.py."""
from __future__ import annotations

from el import embeddings
from el.nodes import find_similar_products


class _CapturingDB:
    def __init__(self, results: list[dict] | None = None, *, fail: bool = False):
        self.rpc_calls: list[dict] = []
        self._results = results or []
        self._fail = fail

    def call_rpc(self, *, schema, function, params):
        self.rpc_calls.append({"schema": schema, "function": function, "params": params})
        if self._fail:
            raise RuntimeError("rpc down")
        return self._results


def _result(key: str, *, text_sim: float, image_sim: float = 0.0) -> dict:
    return {
        "product_key": key,
        "product_url": f"https://x/{key}",
        "product_sku": key,
        "product_name": key,
        "image_url": None,
        "source_provider": "cj_dropshipping",
        "text_similarity": text_sim,
        "image_similarity": image_sim,
        "combined_score": 0.7 * text_sim + 0.3 * image_sim,
    }


def test_text_only_query_calls_rpc_with_null_image():
    db = _CapturingDB(results=[_result("a", text_sim=0.9)])
    provider = embeddings.FakeEmbeddingProvider()

    out = find_similar_products.find_similar(
        query_text="hello",
        query_image_url=None,
        top_n=5,
        provider=provider,
        db_provider=db,
    )

    assert len(out) == 1
    assert out[0]["product_key"] == "a"
    params = db.rpc_calls[0]["params"]
    assert "query_text_embedding" in params
    assert len(params["query_text_embedding"]) == 768
    assert params["query_image_embedding"] is None
    assert params["top_n"] == 5


def test_text_plus_image_query_passes_both_embeddings():
    db = _CapturingDB(results=[_result("a", text_sim=0.9, image_sim=0.5)])
    provider = embeddings.FakeEmbeddingProvider()

    out = find_similar_products.find_similar(
        query_text="hello",
        query_image_url="https://x/img.jpg",
        top_n=3,
        text_weight=0.6,
        image_weight=0.4,
        provider=provider,
        db_provider=db,
    )

    params = db.rpc_calls[0]["params"]
    assert len(params["query_image_embedding"]) == 1408
    assert params["text_weight"] == 0.6
    assert params["image_weight"] == 0.4


def test_empty_db_returns_empty_list():
    db = _CapturingDB(results=[])
    out = find_similar_products.find_similar(
        query_text="x",
        query_image_url=None,
        provider=embeddings.FakeEmbeddingProvider(),
        db_provider=db,
    )
    assert out == []


def test_provider_exception_returns_empty():
    class _BadProvider:
        def embed_text(self, text): raise embeddings.EmbeddingError("nope")
        def embed_image(self, image_url): return []
    out = find_similar_products.find_similar(
        query_text="x",
        query_image_url=None,
        provider=_BadProvider(),
        db_provider=_CapturingDB(),
    )
    assert out == []


def test_rpc_exception_returns_empty():
    db = _CapturingDB(fail=True)
    out = find_similar_products.find_similar(
        query_text="x",
        query_image_url=None,
        provider=embeddings.FakeEmbeddingProvider(),
        db_provider=db,
    )
    assert out == []


def test_image_url_embed_failure_falls_back_to_text_only():
    """If the query image fails to embed, query proceeds text-only."""
    class _MixedProvider:
        def embed_text(self, text): return [0.0] * 768
        def embed_image(self, image_url): raise embeddings.EmbeddingError("img fail")

    db = _CapturingDB(results=[_result("a", text_sim=0.5)])
    out = find_similar_products.find_similar(
        query_text="x",
        query_image_url="https://x/img.jpg",
        provider=_MixedProvider(),
        db_provider=db,
    )
    assert len(out) == 1
    params = db.rpc_calls[0]["params"]
    assert params["query_image_embedding"] is None
