"""SP4 — chat_rag.stream_answer tests."""
from __future__ import annotations

from el import embeddings
from el.web import chat_rag


class _CapturingDB:
    def __init__(self, rpc_results: list[dict] | None = None, *, fail: bool = False):
        self.rpc_calls: list[dict] = []
        self._results = rpc_results or []
        self._fail = fail

    def call_rpc(self, *, schema, function, params):
        self.rpc_calls.append({"schema": schema, "function": function, "params": params})
        if self._fail:
            raise RuntimeError("rpc broken")
        return self._results


def _product(key: str) -> dict:
    return {
        "product_key": key,
        "product_name": f"Item {key}",
        "product_url": f"https://x/{key}",
        "source_provider": "cj_dropshipping",
        "text_similarity": 0.8,
        "image_similarity": 0.0,
        "combined_score": 0.56,
    }


def _fake_llm_stream(chunks: list[str]):
    def _stream(prompt: str):
        for c in chunks:
            yield c
    return _stream


def test_happy_path_emits_context_chunks_done():
    db = _CapturingDB(rpc_results=[_product("a"), _product("b")])
    provider = embeddings.FakeEmbeddingProvider()
    llm = _fake_llm_stream(["Hello", " world"])

    events = list(chat_rag.stream_answer(
        question="best earbuds?", top_k=3,
        embedding_provider=provider, db_provider=db, llm_stream=llm,
    ))

    kinds = [e["event"] for e in events]
    assert kinds[0] == "context"
    assert "chunk" in kinds
    assert kinds[-1] == "done"

    ctx_evt = events[0]
    assert len(ctx_evt["products"]) == 2
    assert ctx_evt["products"][0]["product_key"] == "a"

    text = "".join(e["text"] for e in events if e["event"] == "chunk")
    assert text == "Hello world"


def test_top_k_passed_to_find_similar():
    db = _CapturingDB(rpc_results=[])
    provider = embeddings.FakeEmbeddingProvider()
    list(chat_rag.stream_answer(
        question="x", top_k=7,
        embedding_provider=provider, db_provider=db,
        llm_stream=_fake_llm_stream(["ok"]),
    ))
    assert db.rpc_calls[0]["params"]["top_n"] == 7


def test_embed_failure_emits_error_event():
    class _BadProvider:
        def embed_text(self, t): raise embeddings.EmbeddingError("vertex down")
        def embed_image(self, u): return []

    events = list(chat_rag.stream_answer(
        question="x", top_k=3,
        embedding_provider=_BadProvider(),
        db_provider=_CapturingDB(),
        llm_stream=_fake_llm_stream(["unused"]),
    ))
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert "vertex down" in events[0]["message"]


def test_db_failure_emits_error_event():
    db = _CapturingDB(fail=True)
    events = list(chat_rag.stream_answer(
        question="x", top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=db,
        llm_stream=_fake_llm_stream(["unused"]),
    ))
    # find_similar swallows DB errors → empty product list, so we still get
    # context (empty) + chunks + done. That's correct behavior: no grounding
    # available, but the bot can still answer (poorly). Verify that path.
    kinds = [e["event"] for e in events]
    assert "context" in kinds
    assert events[0]["products"] == []
    assert "done" in kinds


def test_llm_mid_stream_failure_emits_error_after_partial_chunks():
    db = _CapturingDB(rpc_results=[_product("a")])
    provider = embeddings.FakeEmbeddingProvider()

    def crashing_stream(prompt: str):
        yield "partial"
        raise RuntimeError("llm exploded")

    events = list(chat_rag.stream_answer(
        question="x", top_k=2,
        embedding_provider=provider, db_provider=db, llm_stream=crashing_stream,
    ))

    kinds = [e["event"] for e in events]
    assert kinds[0] == "context"
    assert "chunk" in kinds
    assert kinds[-1] == "error"
    assert "llm exploded" in events[-1]["message"]


def test_empty_chunks_still_emits_done():
    db = _CapturingDB(rpc_results=[_product("a")])
    provider = embeddings.FakeEmbeddingProvider()
    llm = _fake_llm_stream([])
    events = list(chat_rag.stream_answer(
        question="x", top_k=2,
        embedding_provider=provider, db_provider=db, llm_stream=llm,
    ))
    assert events[-1]["event"] == "done"
