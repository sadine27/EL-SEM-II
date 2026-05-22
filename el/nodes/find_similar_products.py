"""SP3 helper: find similar products via pgvector cosine similarity.

Standalone helper, not yet wired into the daily pipeline. SP4's chat-bot RAG
path will be its first caller.

Delegates the similarity math to the Postgres function
private.match_product_embeddings (created by the SP3 migration).
"""
from __future__ import annotations

from typing import Any

from el import embeddings, supabase
from el.logger import get_logger

log = get_logger(__name__)


def find_similar(
    *,
    query_text: str,
    query_image_url: str | None = None,
    top_n: int = 10,
    text_weight: float = 0.7,
    image_weight: float = 0.3,
    provider: embeddings.EmbeddingProvider | None = None,
    db_provider: Any | None = None,
) -> list[dict]:
    """Return the top_n products most similar to (query_text, query_image_url).

    Each returned dict has the columns produced by match_product_embeddings:
    product_key, product_url, product_sku, product_name, image_url,
    source_provider, text_similarity, image_similarity, combined_score.

    Fail-soft: any exception (text embed fail, RPC fail) → []. Image-embed
    failure degrades to text-only (RPC called with NULL image embedding).
    """
    active_provider = provider or embeddings.VertexEmbeddingProvider()
    active_db = db_provider or supabase.SupabaseRestProvider()

    try:
        text_vec = active_provider.embed_text(query_text)
    except Exception:
        log.exception("find_similar: text embedding failed for query")
        return []

    image_vec: list[float] | None = None
    if query_image_url:
        try:
            image_vec = active_provider.embed_image(query_image_url)
        except Exception:
            log.warning("find_similar: image embedding failed; falling back to text-only")
            image_vec = None

    params = {
        "query_text_embedding": text_vec,
        "query_image_embedding": image_vec,
        "top_n": int(top_n),
        "text_weight": float(text_weight),
        "image_weight": float(image_weight),
    }
    try:
        rows = active_db.call_rpc(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            function=supabase.MATCH_PRODUCT_EMBEDDINGS_FN,
            params=params,
        )
    except Exception:
        log.exception("find_similar: RPC failed")
        return []
    return rows
