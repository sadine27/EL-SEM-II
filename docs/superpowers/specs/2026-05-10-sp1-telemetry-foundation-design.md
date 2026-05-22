# SP1 — Telemetry Foundation: ε-greedy + Propensity Logging

**Date:** 2026-05-10
**Sub-project of:** Phase 3 SaaS end-to-end build (master spec `2026-05-10-phase3-saas-master-design.md`, commit `4de56c4`)
**Estimated effort:** 3–5 days
**Hard blocker for:** SP7 (Research Paper pipeline). Without SP1 the Phase 3 paper has no identifiable causal estimand.

---

## 1. What this spec is — and is not

**Is:**
- A self-contained design for adding an ε-greedy stochastic logging policy on top of the existing deterministic `phase4_candidate_selection` node, plus a Supabase table that captures the propensity of every candidate that *could have been shown* on each daily run.
- The smallest unit of work that makes Phase 3's "human pick vs statistical-best divergence" paper claim formally identifiable.

**Is not:**
- A wiring of BCC posterior into the live pipeline. SP1 leaves the existing `selection_score` heuristic as the "model" the paper compares against. (Decision recorded in master spec; user picked SP1-min on 2026-05-10.)
- A change to phase4's existing decision logic. SP1 is purely additive at the data flow level.
- A position/order randomization scheme. Order within the final slate is left as score-rank; positional IPS is out of scope.
- An online learner or contextual bandit deployment. The logging policy is fixed (constant ε, no updating).

---

## 2. Problem statement

### 2.1 Why we need this

The Phase 3 paper claims the system can quantify *how often, and by how much, the human curator's pick diverges from the statistically-best pick under a fixed scoring model.* For this claim to be identifiable from observational data, the candidate that a human reviewed must have been chosen by a **stochastic logging policy with known propensities** — otherwise off-policy estimators (IPS, DR, SNIPS) reduce to biased descriptive statistics with no counterfactual interpretation.

The current pipeline's `phase4_candidate_selection` is deterministic: given a fixed input it always shows the same top-10. This means every HIL event collected so far has propensity = 1 for the chosen action and 0 for every alternative — IPS weights are undefined.

### 2.2 Goal

Replace the deterministic top-K selection — at the boundary between phase4 and HIL — with a **slate-level ε-greedy mixture** policy whose marginal per-candidate propensities are closed-form, and persist those propensities so SP7 can compute clipped-IPS and DR estimates with bootstrap CIs.

### 2.3 Non-goals

- Maximizing daily HIL-card quality. ε exploration *will* lower quality marginally; this is the cost of identifiability and is acceptable for a 30-day data-collection window.
- Comparing multiple logging policies. ε-greedy is the only logging policy SP1 deploys; alternative policies (Boltzmann, Thompson) can be evaluated *off-policy* in SP7 from the same data.

---

## 3. Architecture & data flow

### 3.1 Pipeline diagram (changed segment)

```
[merge_review_sources]
        │
        ▼
[phase4_candidate_selection]   ← MODIFIED (additive ctx output only)
        │
        │ ctx["phase4_candidates"]   (existing — top-K survivors, capped)
        │ ctx["eligible_pool"]       (NEW — full post-mismatch/dedupe pool, pre-cap)
        ▼
[stochastic_logger]             ← NEW NODE
        │
        │ Reads:  ctx["eligible_pool"], ctx["phase4_candidates"]
        │ Writes: ctx["hil_slate"]            (final list to send)
        │ Writes: ctx["logging_event_id"]     (uuid v4 grouping this batch)
        │ Writes: private.hil_logging_events  (one row per eligible candidate)
        ▼
[supabase_insert_hil_reviews]   ← MODIFIED (reads hil_slate; sets logging_event_id FK)
        │
        ▼
[prepare_telegram_card] → [send_hil_telegram_photo] → ...
```

### 3.2 What changes, by file

| File | Type of change | LOC delta (est.) |
|------|----------------|------------------|
| `el/nodes/phase4_candidate_selection.py` | Additive: emit `ctx["eligible_pool"]` alongside existing output. No behavioral change to `select_candidates()`. | +25 |
| `el/nodes/stochastic_logger.py` | **NEW.** ε-greedy mixture sampler + propensity arithmetic + Supabase insert. | +180 |
| `el/nodes/supabase_insert_hil_reviews.py` | Read source: `ctx["hil_slate"]` instead of `ctx["phase4_candidates"]`. Add `logging_event_id` to insert payload. | +10 |
| `el/nodes/__init__.py` | Export `stochastic_logger`. | +1 |
| `el/pipeline.py` | Insert `stochastic_logger.run(ctx)` between phase4 and supabase_insert_hil_reviews; gate on `EL_HIL_LOGGING_ENABLED`. | +5 |
| `el/supabase.py` | Add `HIL_LOGGING_EVENTS_TABLE = "hil_logging_events"` constant; add `insert_logging_events()` helper. | +20 |
| `el/config.py` | (No code change — `config.get()` is generic; new env vars documented in `.env.example`.) | 0 |
| `.env.example` | Document `EL_HIL_LOGGING_ENABLED`, `EL_HIL_EPSILON`, `EL_HIL_LOGGING_RNG_SEED`. | +20 |
| `migrations/sp1/001_hil_logging_events.sql` | **NEW.** Supabase migration: create table + indexes + alter `hil_reviews` to add `logging_event_id`. | +40 |
| `tests/test_stochastic_logger.py` | **NEW.** Unit + property tests for the sampler and propensity formulas. | +250 |
| `tests/test_phase4_candidate_selection.py` | Add 2 tests covering the new `eligible_pool` ctx field. | +40 |
| `tests/test_pipeline_with_logging.py` | **NEW.** Integration test: full pipeline run with mocked Supabase, assert one logging row per eligible candidate. | +120 |

Total: ~700 LOC added; ~10 LOC modified in existing files. **Zero deletions, zero behavioral changes** to existing tested logic.

### 3.3 ctx contract additions

```python
# Set by phase4_candidate_selection (NEW):
ctx["eligible_pool"] = [
    {
        "candidate_payload": dict,   # the full row that would have entered selection
        "candidate_score": float,    # selection_score
        "candidate_rank": int,       # 1-based rank within eligible pool by score (desc)
        "in_greedy_slate": bool,     # True iff present in ctx["phase4_candidates"]
    },
    ...
]

# Set by stochastic_logger (NEW):
ctx["hil_slate"]          = list[dict]   # the final list; same shape as old phase4_candidates
ctx["logging_event_id"]   = str          # uuid4 hex; "" iff logging disabled or empty pool
ctx["hil_slate_branch"]   = "greedy" | "explore" | "degenerate" | "passthrough"
```

`hil_slate_branch` is a per-batch debug aid in `ctx` only. The DB `branch` column (§5.1) takes the same labels except `'passthrough'` (passthrough writes no rows). Within one `event_id`, all DB rows share the same `branch` value — it describes which arm of the mixture was sampled for that batch, not a per-row state.

---

## 4. Stochastic logging policy

### 4.1 Definitions

- **Eligible pool** *E*: candidates surviving reviewability + mismatch + dedupe in `phase4_candidate_selection`, **before** topic / provider / total caps. `N := |E|`.
- **Greedy slate** *G*: `phase4_candidate_selection`'s existing deterministic output (`ctx["phase4_candidates"]`), respecting caps. `K := |G| = min(TOTAL_CAP, N_after_caps)`. By construction `G ⊆ E`.
- **Slate** *S*: the random variable representing the K candidates actually shown to the human. `|S| = K` (constant within a batch).
- **Logging policy** π_log: the distribution of *S* given *E* and *G*.

### 4.2 Policy definition (slate-level ε-greedy mixture)

```
With probability  (1 − ε):  S = G                                  (greedy branch)
With probability   ε     :  S = uniform random K-subset of E       (explore branch)
```

**Why this specific form:**
- Closed-form marginal propensities (§4.3) — required for tractable IPS.
- Constant slate size — daily HIL-card volume stays predictable.
- Standard in the contextual-bandit-with-slates literature (Strehl et al. 2010; Swaminathan & Joachims 2015) — defensible in paper.
- A single tunable parameter — easy to explain, easy to ablate.

**Rejected alternatives (recorded for paper "Methods" section):**
- *Per-item Bernoulli inclusion:* variable slate size — bad operational UX, no clean way to enforce TOTAL_CAP without breaking propensity arithmetic.
- *Plackett-Luce / softmax temperature sampling:* requires a temperature τ; harder to justify; one extra hyperparameter to defend.
- *ε-greedy per-slot without replacement:* path-dependent propensities; closed form exists but is not human-readable in a paper.

### 4.3 Marginal propensity (the value we log per candidate)

For each item *i* ∈ *E*:

```
P(i ∈ S)  =  (1 − ε) · 1[i ∈ G]  +  ε · K / N
```

| Case | Formula | Numeric example (ε=0.1, K=10, N=30) |
|------|---------|--------------------------------------|
| *i* ∈ *G* (in greedy slate) | (1 − ε) + ε · K / N | 0.9 + 0.1 · 10/30 = **0.933** |
| *i* ∉ *G* (only in explore arm) | ε · K / N | 0.1 · 10/30 = **0.033** |
| *i* not in *E* | 0 | not logged at all |

Bounds: ε · K / N ≤ P ≤ 1 − ε · (1 − K/N). With ε > 0 every logged item has P > 0; IPS weights 1/P are bounded above by N / (ε · K) ≈ 30 in the example.

### 4.4 Edge cases

| Condition | Branch label | Behavior | Propensity logged |
|-----------|--------------|----------|--------------------|
| N = 0 (empty pool) | n/a | No logging row written; `hil_slate := []`; pipeline continues | n/a |
| N ≤ K (pool ≤ slate cap) | `degenerate` | All items shown; `hil_slate := E` (no sampling); explore branch is identity | P = 1 for all logged items |
| Phase4 fallback path triggered (`fallback_selected` reasons present) | `degenerate` | Fallback already produces ≤ FALLBACK_MAX_ITEMS=2 candidates from a small fallback pool; treat E := G := fallback output (N ≤ K). No ε-greedy mixing — fallback is too rare and too small for exploration to add anything but noise. | P = 1 for all logged items |
| `EL_HIL_LOGGING_ENABLED=false` | `passthrough` | `hil_slate := phase4_candidates`; no DB write; no `logging_event_id` | No row written (NULL on `hil_reviews.logging_event_id`) |
| Supabase insert fails | `passthrough` (logged warning) | `hil_slate := phase4_candidates`; pipeline continues; this batch is unloggable | No row written; HIL events for this batch will have `logging_event_id IS NULL` and be excluded from SP7 IPS analysis |

### 4.5 Reward / outcome (for SP7 reference; not implemented here)

SP1 captures everything needed for SP7 to compute reward Y per (logging_event_id, candidate_idx):
- `was_shown` (in `hil_logging_events`) — whether this candidate entered HIL at all.
- `review_id` (FK to `hil_reviews`) — joins to the human's `approval_status` ∈ {pending, approved, rejected, skipped}.
- Default reward in SP7: `Y := 1 if approval_status == 'approved' else 0`. SP7 may extend with downstream sales signals — out of scope here.

---

## 5. Database schema

### 5.1 New table

```sql
-- migrations/sp1/001_hil_logging_events.sql

create extension if not exists "uuid-ossp";

create table if not exists private.hil_logging_events (
  id                bigserial primary key,
  event_id          uuid        not null,           -- groups one batch
  candidate_idx     int         not null,           -- 0-indexed within event_id
  candidate_score   numeric     not null,           -- phase4 selection_score
  candidate_rank    int         not null,           -- 1-based, desc by score, within E
  candidate_payload jsonb       not null,           -- snapshot of the row
  in_greedy_slate   boolean     not null,
  was_shown         boolean     not null,
  branch            text        not null
                    check (branch in ('greedy','explore','degenerate')),
                    -- per-batch invariant: all rows sharing event_id share branch.
                    -- 'passthrough' is NOT a valid value here because passthrough writes no rows.
  propensity        numeric     not null
                    check (propensity > 0 and propensity <= 1),
  epsilon           numeric     not null
                    check (epsilon >= 0 and epsilon <= 1),
  pool_size         int         not null check (pool_size >= 0),
  slate_size        int         not null check (slate_size >= 0),
  review_id         bigint      references private.hil_reviews(id) on delete set null,
  batch_run_at      timestamptz not null default now(),
  created_at        timestamptz not null default now(),
  unique (event_id, candidate_idx)
);

create index hil_logging_events_event_id_idx
  on private.hil_logging_events(event_id);
create index hil_logging_events_review_id_idx
  on private.hil_logging_events(review_id) where review_id is not null;
create index hil_logging_events_batch_run_at_idx
  on private.hil_logging_events(batch_run_at desc);
```

### 5.2 Alter existing table

```sql
alter table private.hil_reviews
  add column if not exists logging_event_id uuid;

create index if not exists hil_reviews_logging_event_id_idx
  on private.hil_reviews(logging_event_id);
```

`logging_event_id` is nullable so pre-SP1 rows remain valid. Post-SP1, every new `hil_reviews` row written by `supabase_insert_hil_reviews` has it populated.

### 5.3 Why a separate table (vs extending `hil_reviews`)

- `hil_reviews` rows exist *only for shown items*. We need rows for *every* eligible candidate including those not shown — the explore-arm counterfactual data — so a 1:N relationship is required.
- Separation also means the existing HIL flow (Telegram callback handler, etc.) stays untouched.

### 5.4 Migration application

The migration is committed under `migrations/sp1/001_hil_logging_events.sql` but **not auto-applied**. Run manually via Supabase SQL editor or `psql` against `DATABASE_URL` before deploying SP1 code. Add an idempotent check in `stochastic_logger`: on first call, attempt a `select 1 from private.hil_logging_events limit 0` — on relation-not-found, log a clear error and fall through to passthrough.

---

## 6. Configuration

Three new env vars, all optional, all documented in `.env.example`:

| Var | Type | Default | Purpose |
|-----|------|---------|---------|
| `EL_HIL_LOGGING_ENABLED` | bool (`true`/`false`) | `true` | Master kill switch. Set `false` to revert to pre-SP1 behavior with one config change. |
| `EL_HIL_EPSILON` | float in [0, 1] | `0.1` | Exploration rate. ε=0 ⇒ deterministic phase4 (regression-equivalent). ε=1 ⇒ uniform K-subset every run. |
| `EL_HIL_LOGGING_RNG_SEED` | int | unset | If set, seeds the slate sampler. Production = unset (true random). Tests pass an explicit seed. |

`EL_HIL_LOGGING_ENABLED=true` is the *default* once SP1 ships, but the config existing means an emergency revert needs zero code changes.

---

## 7. Error handling & boundaries

The single non-negotiable invariant: **`stochastic_logger` must never crash the pipeline.** Failures degrade to passthrough.

| Failure mode | Detection | Response |
|--------------|-----------|----------|
| `EL_HIL_LOGGING_ENABLED=false` | env read | `hil_slate := phase4_candidates`; log INFO; return |
| `eligible_pool` missing or empty | ctx check | `hil_slate := []`; no DB write; log INFO; return |
| Migration not applied (table missing) | first DB call | log ERROR with migration path; passthrough; return |
| Supabase auth / network failure | exception from `insert_logging_events` | log ERROR (sanitized; no payloads); passthrough; return |
| RNG produces invalid slate (defensive — should be impossible) | post-sample assertion | log CRITICAL with sampler state; passthrough; return |
| Eligible pool serialization fails (e.g. non-JSON payload) | exception in `phase4_candidate_selection` `eligible_pool` builder | log WARNING; emit empty `eligible_pool`; downstream behaves as passthrough |

All failure paths set `ctx["hil_slate_branch"] = "passthrough"` so downstream observability tools (and `supabase_insert_hil_reviews`) know not to write `logging_event_id`.

No retry logic. SP1 batches are daily — a one-day gap in IPS data is acceptable; the cost of an over-eager retry that double-writes propensities is not.

---

## 8. Testing strategy

### 8.1 Coverage targets

- `el/nodes/stochastic_logger.py`: ≥ 95%
- Propensity / sampler helpers: 100%
- Existing 400 tests in the port: must remain green at `pytest tests/ -q`. SP1 is purely additive; any failure indicates a wiring bug.

### 8.2 Test files

**`tests/test_stochastic_logger.py` (NEW):**

Unit tests for pure functions:
- `compute_marginal_propensity(in_greedy, K, N, epsilon)` — correctness across (in/out × K=N × N=0 × ε=0 × ε=1) cells.
- `sample_slate(eligible, greedy, epsilon, rng)` with fixed seed: ε=0 returns `greedy` byte-for-byte; ε=1 returns a uniform K-subset of `eligible`; intermediate ε returns one or the other deterministically per seed.
- Degenerate case N ≤ K: returns all of `eligible`, every propensity = 1, branch = `"degenerate"`.
- Empty case N=0: returns `[]`, branch = `"degenerate"`, no DB write attempted (mock asserts `insert_logging_events` not called).

Property test (1000 iterations, fixed eligible pool of 30):
- Empirical P(item *i* shown) over 1000 sampled slates is within 5% of analytical propensity for ε=0.1, K=10, N=30.
- Slate size is exactly K on every iteration (or N if N < K).

Integration with mocked Supabase:
- One logging row per item in `eligible_pool` (not just shown items).
- `was_shown` matches actual slate membership.
- `propensity` matches `compute_marginal_propensity` for each row.
- All rows in a single call share the same `event_id`.

Failure-mode tests:
- `EL_HIL_LOGGING_ENABLED=false` ⇒ passthrough, no Supabase call.
- `eligible_pool=[]` ⇒ passthrough, no Supabase call.
- Supabase raises on insert ⇒ passthrough, `hil_slate == phase4_candidates`, ERROR logged.

**`tests/test_phase4_candidate_selection.py` (additions):**

- `eligible_pool` is populated and equals the post-mismatch/dedupe pool size.
- `eligible_pool` items each have `candidate_score`, `candidate_rank`, `in_greedy_slate` set.
- Existing test cases all continue to pass (regression).

**`tests/test_pipeline_with_logging.py` (NEW):**

End-to-end pipeline run with all external IO mocked:
- ε=0 ⇒ items written to `hil_reviews` are byte-identical to a baseline run with SP1 code disabled. **This is the regression-safety acceptance test.**
- ε=0.5 ⇒ logging rows count = eligible-pool size; `hil_reviews.logging_event_id` set on every shown item; FK matches.

### 8.3 Acceptance criteria (informal)

A reviewer can run `EL_HIL_EPSILON=0 pytest tests/ -q` and see **all 400 + new tests green**, then `EL_HIL_EPSILON=0.1 pytest tests/test_pipeline_with_logging.py -v` and see logging rows written with non-degenerate propensities.

---

## 9. Backfill & data hygiene

- Pre-SP1 HIL events keep `logging_event_id IS NULL`. They are **excluded** from SP7's IPS analysis. **Do not backfill synthetic propensities** — assigning uniform 1/K to historical events would be statistically incorrect and pollute the paper's identification claim.
- Pre-SP1 `hil_reviews` rows remain readable by all existing nodes. The new column is nullable.
- After SP1 deploy, the SP7 paper script's eligibility filter is `where logging_event_id is not null and propensity > 0`.
- Target collection window: 30 days from SP1 deploy. Master spec assumes 100+ HIL events — at ε=0.1, K=10, this yields ~30 explore-arm exposures per item across the 100 batches, sufficient for clipped-IPS with bootstrap CIs.

---

## 10. Open questions (deferred — none block SP1 implementation)

| ID | Question | Defer to |
|----|----------|----------|
| Q1 | IPS clipping threshold τ | SP7 (paper analysis) — default 20, tune empirically |
| Q2 | Estimator family (clipped IPS vs SNIPS vs DR) | SP7 — pick during paper writing |
| Q3 | Whether to randomize *order* within slate (positional bias) | SP1.5 if positional effects look material in SP7 EDA |
| Q4 | Reward Y definition: approval-only vs sales-weighted | SP7 — log everything in SP1, decide Y at analysis time |
| Q5 | Whether to expose `eligible_pool` to dashboards | SP4 (UI) |

---

## 11. Out of scope

Confirming what SP1 does **not** touch, to avoid scope creep during implementation:

- BCC posterior wiring (master spec SP1.5 / SP3)
- Vertex multimodal embeddings, pgvector (master spec SP3)
- New trend sources — Meta Ad Library, TikTok Creative Center, AliExpress (master spec SP2)
- Order/position randomization within the slate
- Online learner / Thompson sampling / contextual bandit deployment
- A dashboard for browsing logging events (master spec SP4)
- Export of `hil_logging_events` to Drive (the existing Drive export covers `hil_reviews` only; SP7 may add an export job)
- Changing the default ε in production over time (we set 0.1 and leave it for the 30-day collection window; tuning is post-paper)

---

## 12. Success criteria

SP1 is done when **all five** of the following hold:

1. All 400 existing tests pass at `pytest tests/ -q`.
2. New tests (≥ ~30 cases) pass; `el/nodes/stochastic_logger.py` ≥ 95% coverage.
3. With `EL_HIL_EPSILON=0`, an end-to-end pipeline run produces `hil_reviews` rows byte-identical to a pre-SP1 baseline (regression safety verified).
4. With `EL_HIL_EPSILON=0.1`, a pipeline run against a real Supabase project writes one row per eligible candidate to `private.hil_logging_events`, with valid `propensity` values, valid `event_id` UUIDs, and FK-matched `review_id` for every shown item.
5. Documentation: `.env.example` lists the three new vars; `docs/PORT_LOG.md` (or a new `docs/SP1_LOG.md`) records the iteration; this spec is committed to git on `main`.

---

## 13. Next step

Hand this spec to the **writing-plans** skill to produce the implementation plan. The implementation plan will sequence the work into commits (suggested order: migration SQL → phase4 `eligible_pool` emission → `stochastic_logger` pure helpers → `stochastic_logger` integration → `supabase_insert_hil_reviews` rewire → pipeline wiring → integration test → regression-safety acceptance run).

No further design decisions need user input before implementation begins.
