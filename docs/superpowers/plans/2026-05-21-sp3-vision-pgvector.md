# SP3 — Vision + pgvector Implementation Plan

**Spec:** `docs/superpowers/specs/2026-05-21-sp3-vision-pgvector-design.md`
**Branch:** `feat/sp3-vision-pgvector`
**Estimated effort:** ~3 sessions (migration + embeddings client + 2 nodes + pipeline wire + log).

Tasks executed in order. Every task ends with green tests and a commit.

---

## Task 0: `.env.example` documentation

- [ ] Append SP3 env-var block (`EL_EMBEDDINGS_ENABLED`, `EL_EMBEDDINGS_TEXT_MODEL`, `EL_EMBEDDINGS_IMAGE_MODEL`, `EL_EMBEDDINGS_MAX_RETRIES`).
- [ ] Commit: `docs(sp3): document EL_EMBEDDINGS_* env vars`

---

## Task 1: Supabase migration

**Files:**
- Create: `migrations/sp3/001_pgvector_and_embeddings.sql`

- [ ] **Step 1:** Write the migration SQL per design spec §2:
  - `create extension if not exists vector;`
  - `create table if not exists private.product_embeddings (...);`
  - HNSW indexes on `text_embedding` (full) and `image_embedding` (partial, `where image_embedding is not null`).
  - `private.match_product_embeddings(...)` function (returns top-N by combined cosine).
- [ ] **Step 2:** Verify SQL is idempotent (re-runnable safely): every DDL has `if not exists`.
- [ ] **Step 3:** Add `HIL_PRODUCT_EMBEDDINGS_TABLE = "product_embeddings"` constant to `el/supabase.py`.
- [ ] **Step 4:** Tests: one assertion in `tests/test_supabase.py` for the new constant.
- [ ] **Step 5:** Commit: `feat(sp3): pgvector + product_embeddings migration`

---

## Task 2: `el/embeddings.py` — Vertex provider (TDD)

**Files:**
- Create: `el/embeddings.py`
- Create: `tests/test_embeddings.py`

### TDD

- [ ] **Step 1:** Write `tests/test_embeddings.py`. Cover:
  - `EmbeddingProvider` Protocol runtime check on `VertexEmbeddingProvider`.
  - `embed_text("hello")` POSTs to the correct Vertex URL with the SA OAuth header; parses `predictions[0].embeddings.values` into a 768-float list.
  - `embed_image("https://x/img.jpg")` POSTs to the multimodal endpoint with `{instances: [{image: {gcsUri or bytesBase64Encoded or...}}]}` — exact body shape per Vertex docs.
  - Retry on 429 / 503 with exponential backoff (mock `time.sleep`); fail after `EL_EMBEDDINGS_MAX_RETRIES`.
  - Timeout boundary (assert `requests.post` called with `timeout=30`).
  - `FakeEmbeddingProvider` deterministically returns vectors keyed by input — used by downstream tests.

- [ ] **Step 2:** Failing tests (`ModuleNotFoundError`).

### Implementation

- [ ] **Step 3:** Create `el/embeddings.py`:
  - Reuse `el.llm.VertexAuth` for OAuth tokens.
  - `class VertexEmbeddingProvider` with `embed_text` + `embed_image` methods.
  - `class FakeEmbeddingProvider` for tests — module-level so plain `import` from tests works.
  - All Vertex calls have try/except + retry; never raise non-IO exceptions.

- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit: `feat(sp3): add Vertex multimodal embedding provider`

---

## Task 3: `el/nodes/embed_candidate_products.py` (TDD)

**Files:**
- Create: `el/nodes/embed_candidate_products.py`
- Create: `tests/test_embed_candidate_products.py`

### TDD

- [ ] **Step 1:** Write tests. Cover:
  - `EL_EMBEDDINGS_ENABLED=false` → passthrough; provider never called; `ctx["embeddings_result"]["ok"] is True`.
  - Empty `cj_top_3` (or `pick_top_3_result` whichever the real ctx key is — verify against existing `pick_top_3.py`) → no calls; ok=True.
  - Per-candidate: text embedding always called, image embedding called only when `image_url` present.
  - Provider exception on one candidate doesn't crash the loop; that candidate is skipped, others still embedded.
  - Hash short-circuit: if a row with matching `product_key` AND `raw_payload_hash` exists, Vertex is NOT called.
  - Supabase upsert called with the right schema/table/conflict columns.

- [ ] **Step 2:** Failing tests.

### Implementation

- [ ] **Step 3:** Create the node. Use FakeEmbeddingProvider injected via `run(ctx, provider=None, db_provider=None)`.
- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit: `feat(sp3): add embed_candidate_products node`

---

## Task 4: `el/nodes/find_similar_products.py` (TDD)

**Files:**
- Create: `el/nodes/find_similar_products.py`
- Create: `tests/test_find_similar_products.py`

### TDD

- [ ] **Step 1:** Write tests. Cover:
  - `find_similar(query_text="x")` calls only text-embedding + only the text-similarity RPC; `image_weight=0` path.
  - `find_similar(query_text=..., query_image_url=...)` calls both, merges weighted.
  - Missing-image rows: contribute text similarity only with `image_sim = 0`.
  - `top_n` cap honored on the merged result.
  - Empty DB → returns `[]`.
  - Provider raise → returns `[]`, logs warning.

- [ ] **Step 2:** Failing tests.

### Implementation

- [ ] **Step 3:** Create the node. Stand-alone helper (not yet wired into the daily pipeline — SP4 will call it).
- [ ] **Step 4:** Tests pass. Full suite green.
- [ ] **Step 5:** Commit: `feat(sp3): add find_similar_products helper`

---

## Task 5: Pipeline wire-in (TDD)

**Files:**
- Modify: `el/pipeline.py`
- Modify: `tests/test_pipeline_*` or create `tests/test_pipeline_with_embeddings.py`

- [ ] **Step 1:** Add `embed_candidate_products` import (alphabetical block).
- [ ] **Step 2:** Insert call after `pick_top_3.run(ctx)`, guarded by `EL_EMBEDDINGS_ENABLED` flag check.
- [ ] **Step 3:** Integration test: full path with both fakes, asserts the embedding upsert was called once per candidate; asserts pipeline still works with embeddings disabled.
- [ ] **Step 4:** Full suite green.
- [ ] **Step 5:** Commit: `feat(sp3): wire embed_candidate_products into pipeline`

---

## Task 6: Iteration log + roadmap + merge

**Files:**
- Create: `docs/SP3_LOG.md`
- Modify: `PHASE3_ROADMAP.md`

- [ ] Write `docs/SP3_LOG.md` mirroring `docs/SP2_LOG.md` structure.
- [ ] Update `PHASE3_ROADMAP.md` SP3 row + Next action.
- [ ] Squash-merge to `main`.
- [ ] Final roadmap update flipping SP3 to ✅.

Post-merge production smoke (human): apply migration in Supabase; run a batch with `EL_EMBEDDINGS_ENABLED=true`; observe Vertex billing for the day stays ≤ $0.02; verify `product_embeddings` rows appear.
