"""SP4 — RAG chat helper.

Pure generator. Yields event dicts that the FastAPI /api/chat route serializes
to SSE ``data:`` lines. No FastAPI imports here so this is independently
unit-testable.

Event shape:
  {"event": "context", "products": [...]}    — first event, citation rows
  {"event": "chunk",   "text": "..."}        — repeating, LLM tokens
  {"event": "done"}                          — terminal on success
  {"event": "error",   "message": "..."}     — terminal on failure
"""
from __future__ import annotations

from typing import Callable, Iterator

from el.logger import get_logger
from el.nodes import find_similar_products

log = get_logger(__name__)


def _build_prompt(question: str, products: list[dict]) -> str:
    """System prompt + grounded context + user question.

    Kept deliberately small — the LLM's job is "answer the question using the
    listed products as evidence; cite product names when relevant."
    """
    if products:
        context_lines = "\n".join(
            f"- {p.get('product_name', '?')} ({p.get('product_url', '')})"
            for p in products
        )
        context_block = f"Relevant catalog products:\n{context_lines}\n\n"
    else:
        context_block = "No catalog products matched this query.\n\n"

    return (
        "You are an assistant for a dropshipping research catalog. "
        "Answer the user's question using the listed products as evidence "
        "when relevant. Cite product names directly.\n\n"
        f"{context_block}"
        f"User question: {question}"
    )


def stream_answer(
    *,
    question: str,
    top_k: int,
    embedding_provider,
    db_provider,
    llm_stream: Callable[[str], Iterator[str]],
) -> Iterator[dict]:
    """Yield SSE event dicts for the chat endpoint.

    Algorithm (spec §4.9):
      1. find_similar_products(query_text=question, ...) — handles its own
         fail-soft, so we always get a list (possibly empty).
      2. Emit one 'context' event with the products as citations.
      3. Stream LLM tokens as 'chunk' events.
      4. Terminate with 'done' on success, 'error' on any LLM exception.

    Embedding provider failure during the find_similar step short-circuits
    with a single 'error' event (no context, no chunks).
    """
    # Quick sanity check on the embedding provider before delegating — gives a
    # cleaner error event when Vertex auth is broken.
    try:
        embedding_provider.embed_text(question)
    except Exception as exc:
        log.exception("chat_rag: embed_text failed")
        yield {"event": "error", "message": str(exc)}
        return

    try:
        products = find_similar_products.find_similar(
            query_text=question,
            query_image_url=None,
            top_n=top_k,
            provider=embedding_provider,
            db_provider=db_provider,
        )
    except Exception as exc:
        # find_similar itself fail-softs to [], so this should be rare —
        # but guard anyway.
        log.exception("chat_rag: find_similar raised unexpectedly")
        yield {"event": "error", "message": str(exc)}
        return

    yield {"event": "context", "products": products}

    prompt = _build_prompt(question, products)
    try:
        for chunk in llm_stream(prompt):
            yield {"event": "chunk", "text": chunk}
    except Exception as exc:
        log.exception("chat_rag: llm stream failed mid-response")
        yield {"event": "error", "message": str(exc)}
        return

    yield {"event": "done"}
