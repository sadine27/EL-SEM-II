# SP3 — Vision + pgvector (Design Spec)

**Date:** 2026-05-21
**Author:** Divyesh Sharma (with Claude)
**Status:** Design.
**Parent:** master spec §SP3
**Roadmap entry:** `PHASE3_ROADMAP.md` §SP3

---

## 1. Scope

The master spec for SP3 lists six deliverables. This sub-project ships five and defers one:

**Shipped:**
1. Supabase migration — enable `pgvector` extension + create `private.product_embeddings`.
2. `el/embeddings.py` — Vertex multimodal-embedding client (`multimodalembedding@001`) with retry, rate-limit handling, and a fake-injectable provider for tests.
3. `el/nodes/embed_candidate_products.py` — runs after `pick_top_3`; embeds each candidate's `product_name` (text embedding) and `image_url` (image embedding) and upserts to `private.product_embeddings`.
4. `el/nodes/find_similar_products.py` — given a candidate (or any text+image input), returns top-N cosine-similarity matches from `private.product_embeddings`.
5. Pipeline wire-in (`embed_candidate_products` runs after `pick_top_3`).

**Deferred:**
- Optional `el/sources/reverse_image.py` Bing Visual Search wrapper. Marked optional in the master spec; not needed for the immediate pipeline value. Becomes a tiny follow-up sub-project if reverse-image-search demand materializes.

---

## 2. Schema changes

```sql
-- migrations/sp3/001_pgvector_and_embeddings.sql

create extension if not exists vector;

create table if not exists private.product_embeddings (
  product_key       text primary key,             -- canonical id: lower(product_url) or sha1(product_url)
  product_url       text not null,
  product_sku       text,
  product_name      text not null,
  image_url         text,
  text_embedding    vector(768)  not null,        -- Vertex text-embedding-005 dimension
  image_embedding   vector(1408),                 -- Vertex multimodalembedding@001 dimension
  source_provider   text,                         -- "cj_dropshipping" | "browserbase_marketplace" | "shopify_competitor:<store>"
  embedded_at       timestamptz not null default now(),
  raw_payload_hash  text                          -- to detect when re-embed is needed
);

create index if not exists product_embeddings_text_hnsw
  on private.product_embeddings using hnsw (text_embedding vector_cosine_ops);

create index if not exists product_embeddings_image_hnsw
  on private.product_embeddings using hnsw (image_embedding vector_cosine_ops)
  where image_embedding is not null;

create index if not exists product_embeddings_source_provider_idx
  on private.product_embeddings (source_provider);

comment on table private.product_embeddings is
  'SP3 — Vertex multimodal embeddings for candidate products. Enables in-catalog similarity search.';
```

**Why no "combined" embedding column:** the master spec proposed a 2176-dim concatenation. Concatenating text+image vectors then doing cosine similarity is mathematically equivalent to averaging the two component cosine similarities only when both vectors are unit-normalized to the same scale — which Vertex doesn't guarantee. Querying the two columns separately and combining scores at the application layer is more honest and equally fast on HNSW indexes. Drops one column, one index, and 17KB per row.

**Why `image_embedding` is nullable:** not every candidate has a usable image URL at embed time. Nullable + partial index avoids polluting the image-similarity space with synthetic zeros.

**`raw_payload_hash`:** lets `embed_candidate_products` short-circuit when the candidate is byte-identical to what we already embedded (re-runs on the same trend → no Vertex re-spend).

---

## 3. `el/embeddings.py`

```python
class EmbeddingProvider(Protocol):
    def embed_text(self, text: str) -> list[float]: ...
    def embed_image(self, image_url: str) -> list[float]: ...

class VertexEmbeddingProvider:
    """Vertex multimodalembedding@001 + text-embedding-005.

    Text: text-embedding-005 (768-dim).
    Image: multimodalembedding@001 (1408-dim). Accepts an image URL or
           gcs:// path; we use HTTP URLs.

    Endpoints (Vertex REST):
      POST /v1/.../publishers/google/models/text-embedding-005:predict
      POST /v1/.../publishers/google/models/multimodalembedding@001:predict
    """
    def __init__(self, auth: VertexAuth | None = None, ...): ...
    def embed_text(self, text: str) -> list[float]: ...
    def embed_image(self, image_url: str) -> list[float]: ...
```

- Reuses the existing `VertexAuth` from `el/llm.py` (SA-based OAuth).
- Bounded retry on 429/5xx: exponential backoff, max 3 attempts.
- Bounded request timeout (30s default, matching the rest of `el/`).
- Tests inject a `FakeEmbeddingProvider` returning deterministic vectors — no live Vertex calls in CI.

**Cost gating:** `EL_EMBEDDINGS_ENABLED` (default `"true"`). Setting to `"false"` makes `embed_candidate_products` a passthrough — zero Vertex spend.

---

## 4. `el/nodes/embed_candidate_products.py`

**Where:** runs after `pick_top_3.run(ctx)`, before `normalize_cj_review.run(ctx)`.

**Logic:**
1. Read `ctx["cj_top_3"]` (the picked candidates). Per master spec; verify exact key during implementation.
2. If `EL_EMBEDDINGS_ENABLED=false` → log and skip.
3. For each candidate:
   - Compute `product_key` (lowercased URL).
   - Compute `raw_payload_hash` (sha1 of product_name + url + image_url).
   - Query `private.product_embeddings` for that `product_key`. If `raw_payload_hash` matches → skip Vertex call entirely.
   - Otherwise: call `provider.embed_text(product_name)` and (if image available) `provider.embed_image(image_url)`.
   - Upsert into `private.product_embeddings` (conflict on `product_key`).
4. Always set `ctx["embeddings_result"] = {"ok": True/False, "embedded_n": N, "skipped_n": M}`. Fail-soft — pipeline never crashes on embedding failure.

---

## 5. `el/nodes/find_similar_products.py`

**Standalone helper node**, not yet wired into the daily pipeline (master spec sites it as available for the chat bot / RAG path that SP4 will use). Tested in isolation.

**Function:**
```python
def find_similar(
    *,
    query_text: str | None,
    query_image_url: str | None,
    top_n: int = 10,
    text_weight: float = 0.7,
    image_weight: float = 0.3,
    provider: EmbeddingProvider | None = None,
    db_provider: SupabaseRestProvider | None = None,
) -> list[dict]:
    """Returns top_n products ordered by combined cosine similarity.

    Combined score = text_weight * text_sim + image_weight * image_sim.
    Sources may have no image_embedding — those rows contribute only text_sim.
    """
```

Implementation: two RPCs (one per embedding column), merge in Python. Avoids application-side vector math — pgvector does it server-side.

A Postgres function `private.match_product_embeddings(query_text_vec, query_image_vec, top_n, ...)` is added in the migration to encapsulate the query — keeps Python clean and lets Supabase index hints work.

---

## 6. Pipeline wire-in

Two lines added in `el/pipeline.py` between `pick_top_3` and `normalize_cj_review`:

```python
if config.get("EL_EMBEDDINGS_ENABLED", "true").lower() == "true":
    embed_candidate_products.run(ctx)
```

Wrapped in env-check so a config flip disables it cleanly. No effect on existing pipeline tests when embeddings provider is mocked.

---

## 7. Env vars

| Var | Purpose | Default |
|---|---|---|
| `EL_EMBEDDINGS_ENABLED` | Master flag for the embedding node | `"true"` |
| `EL_EMBEDDINGS_TEXT_MODEL` | Override the text-embedding model | `"text-embedding-005"` |
| `EL_EMBEDDINGS_IMAGE_MODEL` | Override the image-embedding model | `"multimodalembedding@001"` |
| `EL_EMBEDDINGS_MAX_RETRIES` | Retry cap for 429/5xx | `"3"` |

All documented in `.env.example`.

---

## 8. Tests

| File | Covers |
|---|---|
| `tests/test_embeddings.py` | `VertexEmbeddingProvider` request body, response parsing, retry on 429/5xx, timeout boundary, fake provider behavior. All Vertex IO mocked via `monkeypatch` on `requests.post`. |
| `tests/test_embed_candidate_products.py` | Reads `cj_top_3`, computes `product_key` + hash, calls provider, upserts via fake supabase. Short-circuits on hash match. Master flag off → passthrough. Fail-soft on provider exception. |
| `tests/test_find_similar_products.py` | Combined score weighting; image_weight=0 → text-only path; missing image_embedding rows handled. RPC mocked. |
| `tests/test_pipeline_with_embeddings.py` | Integration test exercising the full path with both fakes wired in. |

No live Vertex calls anywhere in the test suite.

---

## 9. Error handling

Inherits the project-wide fail-soft contract:
- Vertex unavailable / 429 exhausted → log, set `ctx["embeddings_result"]["ok"] = False`, continue.
- Supabase unavailable → log, count as skipped, continue. Re-embed at next run.
- Image URL 404 / unsupported MIME → log per-candidate, store `image_embedding = NULL`, continue.

No new error code categories. Existing `error_handler.py` flow unchanged.

---

## 10. Cost guardrails

- **Off-by-flag for first production run** — but defaulted on (with master flag) so it activates after deploy without manual toggle. Spec calls out that the first batch should be observed for cost.
- Short-circuit via `raw_payload_hash` means re-running on the same trend doesn't re-spend.
- Each daily batch embeds up to ~3 candidates (the `cj_top_3` size). At Vertex's text + image embedding rates, that's ≤ $0.01/day worst case.
- A hard daily cap (`EL_EMBEDDINGS_DAILY_CAP`) is **deferred** unless cost observation shows it's needed.

---

## 11. Definition of done

Per `PHASE3_ROADMAP.md` §Definition of Done. Specific to SP3:

1. Spec committed (this file).
2. Plan committed at `docs/superpowers/plans/2026-05-21-sp3-vision-pgvector.md`.
3. Migration committed and idempotent.
4. All plan tasks executed; full pytest suite green; project coverage ≥ 90%.
5. New env vars in `.env.example`.
6. `docs/SP3_LOG.md` iteration log.
7. PR squash-merged to `main`.
8. Roadmap status → ✅; "Next action" → SP4.

Post-merge production smoke (human, with creds + Vertex billing visible):
- Apply the migration in Supabase.
- Run one batch with `EL_EMBEDDINGS_ENABLED=true`. Verify `private.product_embeddings` has new rows after the run.
- Observe Vertex billing dashboard for the day; confirm spend is ≤ $0.02.

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Vertex multimodal endpoint shape drift breaks our request body | Pin model version in env var; integration test asserts response parsing on stable shape; warning logged on shape mismatch. |
| Cost overrun if `cj_top_3` accidentally returns 100 candidates | `raw_payload_hash` short-circuit caps re-spend; daily-cap env var is a future deferral if real exposure observed. |
| pgvector not actually enabled on the Supabase project | Migration is idempotent (`create extension if not exists`). First production run logs an error if the table doesn't accept inserts; manual SQL run resolves. |
| HNSW index build time on first prod insert blocks query latency | Initial table is empty; index builds instantly. After thousands of rows, HNSW build is incremental per insert — fine. |
| `find_similar` returns junk if embeddings have not yet been populated for the catalog | Function returns `[]` on empty table; downstream callers (SP4 chat bot) check non-empty. |
