# SP3 — Vision + pgvector Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-21-sp3-vision-pgvector-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sp3-vision-pgvector.md`
**Started:** 2026-05-21
**Completed:** 2026-05-21

## Summary

SP3 adds Vertex multimodal embeddings (text + image) for candidate products
and a `private.product_embeddings` table indexed via pgvector HNSW for
fast cosine-similarity search. The daily pipeline now embeds each
`cj_top_products` candidate after `pick_top_3`; SP4 (chat-bot RAG) will
be the first consumer of the new `find_similar_products` helper.

The master spec's optional Bing Visual Search wrapper is deferred (low
value relative to setup cost; revisit if reverse-image search demand
materializes).

## What changed

| Area | Change |
|------|--------|
| Schema | New table `private.product_embeddings`; HNSW indexes on `text_embedding` (full) and `image_embedding` (partial). New SQL function `private.match_product_embeddings(query_text, query_image, top_n, text_weight, image_weight)`. Migration in `migrations/sp3/001_pgvector_and_embeddings.sql`. |
| Embedding client | New `el/embeddings.py` — Vertex `text-embedding-005` (768-dim) + `multimodalembedding@001` (1408-dim) via `:predict`. Reuses `VertexAuth` from `el/llm.py` for SA-OAuth (no new credentials). Exponential-backoff retry on 429/5xx. `FakeEmbeddingProvider` for tests. |
| Pipeline node | `el/nodes/embed_candidate_products.py` — runs after `pick_top_3`, per-candidate fail-soft, `raw_payload_hash` short-circuit skips Vertex re-spend on byte-identical re-embeds. |
| Helper | `el/nodes/find_similar_products.py` — query-text + optional-image → top-N similar products via the new SQL function. |
| Supabase client | `SupabaseRestProvider.call_rpc(schema, function, params)` for invoking Postgres functions via PostgREST `/rpc/`. |
| Pipeline | `el/pipeline.py` calls `embed_candidate_products.run(ctx)` between `pick_top_3` and `normalize_cj_review`, gated by `EL_EMBEDDINGS_ENABLED`. |
| Config | New env vars: `EL_EMBEDDINGS_ENABLED`, `EL_EMBEDDINGS_TEXT_MODEL`, `EL_EMBEDDINGS_IMAGE_MODEL`, `EL_EMBEDDINGS_MAX_RETRIES`. |
| Tests | 25 new tests across embeddings client, node, similarity helper, and pipeline integration. All Vertex IO mocked; no live calls in CI. |

## Commits (in order)

| Commit | Task | What |
|---|---|---|
| `808734f` | spec | Design spec |
| `31902c1` | plan | Implementation plan |
| `bcac6b2` | Task 0 | `.env.example` env vars |
| `ed1649f` | Task 1 | pgvector migration + `el/supabase.py` constants |
| `ebff08c` | Task 2 | `el/embeddings.py` Vertex provider + fake |
| `2a92db8` | Task 3 | `embed_candidate_products` node |
| `4198392` | Task 4 | `find_similar_products` helper + `call_rpc` on supabase client |
| `8c2960c` | Task 5 | Pipeline wire-in |

## Deploy runbook

1. **Apply the migration in Supabase:** SQL Editor or
   `psql $DATABASE_URL -f migrations/sp3/001_pgvector_and_embeddings.sql`.
   Confirm `private.product_embeddings` exists and `\df private.match_product_embeddings`
   shows the function signature.
2. **Vertex prerequisites:** the existing service account in
   `GOOGLE_SERVICE_ACCOUNT_JSON` must have `roles/aiplatform.user`
   (already true from prior SPs). The Vertex AI API must be enabled
   on the project. **No new credentials.**
3. Deploy the new code. Defaults (`EL_EMBEDDINGS_ENABLED=true`) activate
   embeddings on the next batch automatically.
4. **Cost monitor:** open the Vertex billing dashboard for the project.
   Run one batch (`python -m el run`). Per-batch worst case: 3 candidates
   × (1 text + 1 image) = 6 Vertex calls = ≤ $0.02. Confirm actual spend.
5. **Verify rows:** `select count(*) from private.product_embeddings;`
   should equal the number of unique candidates ever embedded.
6. **Re-run idempotency check:** running the same batch twice should
   produce one set of new rows on the first run and zero new rows on the
   second (hash short-circuit). Verify by re-running and confirming
   `embeddings_result.skipped_n` increases.

## Rollback

Set `EL_EMBEDDINGS_ENABLED=false` in `.env` and restart. The pipeline
skips the embed node entirely — zero Vertex spend, zero schema usage.
Table and function remain (idempotent migration); no schema rollback.

## Acceptance verification

- [x] Migration is idempotent (every DDL has `if not exists` or `create or replace`).
- [x] Embedding client retries on 429/5xx; raises `EmbeddingError` after retries.
- [x] `embed_candidate_products` fail-soft on every error mode (provider, DB,
   per-candidate); `ctx["embeddings_result"]` always set.
- [x] Hash short-circuit verified: identical re-embed of same candidate
   makes zero provider calls.
- [x] `find_similar_products` degrades to text-only on image-embed failure.
- [x] 488/488 suite green; no live Vertex calls in tests.
- [ ] One end-to-end production batch confirms `private.product_embeddings`
  is populated; Vertex daily spend ≤ $0.02. *(human verification post-merge.)*

## Surprises / decisions deferred

- **Dropped the "combined" 2176-dim embedding column** (master spec listed
  it). Concat-then-cosine ≠ averaging component cosines without shared
  normalization. Cleaner to query both columns server-side and let the
  SQL function weight them — `match_product_embeddings` does exactly this.
- **Image-embed failures are non-fatal** at both the node level (per
  candidate stores `image_embedding=NULL`) and the search-query level
  (`find_similar` falls back to text-only). The catalog is allowed to
  contain text-only rows.
- **`SupabaseRestProvider.call_rpc`** added as a thin general-purpose
  RPC method. Other nodes can now invoke Postgres functions without
  bespoke `requests.post` calls.
- **Bing Visual Search wrapper deferred** — flagged as optional in master
  spec; no immediate consumer in Phase 3.
