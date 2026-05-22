# SP1 — Telemetry Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a slate-level ε-greedy stochastic logging policy on top of the existing deterministic `phase4_candidate_selection`, persist closed-form marginal propensities to a new `private.hil_logging_events` table, and expose a `logging_event_id` FK on `private.hil_reviews` — without changing the behavior or test surface of any existing node.

**Architecture:** A new node `el/nodes/stochastic_logger.py` runs between `phase4_candidate_selection` and `supabase_insert_hil_reviews`. Phase4 is modified additively to expose an `eligible_pool` ctx field. The new node samples a slate (with prob `1−ε` use phase4's deterministic output; with prob `ε` use a uniform random K-subset of the eligible pool), computes per-item marginal propensities `(1−ε)·𝟙[i∈G] + ε·K/N`, and writes one row per logged candidate to Supabase. All failures degrade to passthrough — pipeline never crashes. ε=0 is the regression-safety mode and produces byte-identical `hil_reviews` to the pre-SP1 pipeline.

**Tech Stack:** Python 3.12, pytest, requests (existing Supabase REST client), uuid (stdlib), random (stdlib, seedable). No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md` (commit `35d5d2a`).

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `migrations/sp1/001_hil_logging_events.sql` | Create | Supabase DDL: new table, FK column on `hil_reviews`, indexes |
| `el/supabase.py` | Modify | Add `HIL_LOGGING_EVENTS_TABLE` constant |
| `.env.example` | Modify | Document `EL_HIL_LOGGING_ENABLED`, `EL_HIL_EPSILON`, `EL_HIL_LOGGING_RNG_SEED` |
| `el/nodes/phase4_candidate_selection.py` | Modify | Refactor internals into `_select_with_pool`; emit `ctx["eligible_pool"]` |
| `el/nodes/stochastic_logger.py` | Create | Pure helpers (`compute_marginal_propensity`, `sample_slate`) + `run(ctx)` Supabase integration |
| `el/nodes/supabase_insert_hil_reviews.py` | Modify | Read from `ctx["hil_slate"]`; populate `logging_event_id` |
| `el/pipeline.py` | Modify | Insert `stochastic_logger.run(ctx)` between phase4 and supabase_insert_hil_reviews |
| `tests/test_phase4_candidate_selection.py` | Modify | Add 2 tests for `eligible_pool` ctx field |
| `tests/test_stochastic_logger.py` | Create | Unit + property tests for sampler and propensity formulas |
| `tests/test_supabase_insert_hil_reviews.py` | Modify | Add tests for `logging_event_id` propagation and `hil_slate` source |
| `tests/test_pipeline_with_logging.py` | Create | End-to-end integration test with mocked external IO |
| `tests/test_sp1_regression_safety.py` | Create | ε=0 produces byte-identical `hil_reviews` to pre-SP1 baseline |
| `docs/SP1_LOG.md` | Create | Iteration journal (mirrors `docs/PORT_LOG.md` pattern) |

**Boundaries:**
- `el/nodes/stochastic_logger.py` is the ONLY file with new behavioral logic. Pure helpers (`compute_marginal_propensity`, `sample_slate`) are stateless and seedable for testing. `run(ctx)` is the only function that touches Supabase.
- Phase4 changes are pure refactoring + an additive ctx output. The public function `select_candidates(rows, *, selected_at=None) -> list[dict]` keeps its exact signature and behavior.
- `supabase_insert_hil_reviews.py` only changes its **input source** (`hil_slate` ← was `phase4_candidates`) and adds one field to the upsert payload. Output ctx keys unchanged.

---

## Conventions used in this plan

- **Working directory:** repo root (the directory containing `el/`, `tests/`, `docs/`).
- **Python invocation:** `.venv\Scripts\python.exe` on Windows. The existing `README.md` specifies `py -3.12 -m venv .venv` for setup. All `pytest` commands assume the venv is active or invoked via the full path.
- **Pytest selector syntax:** `pytest tests/test_foo.py::test_name -v` runs a single test.
- **Commit style:** mirror existing repo log — `feat(sp1): ...`, `test(sp1): ...`, `refactor(sp1): ...`, `docs(sp1): ...`. End each commit body with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` only if the user explicitly requests; otherwise omit.
- **Tests imports:** mirror `from el.nodes import <module_name>` (the package's `__init__.py` is empty; submodules are imported by name).
- **Encoding:** all new Python and SQL files written with UTF-8 (no BOM). Per repo memory, on Windows always use `encoding="utf-8"` and `ensure_ascii=False` when writing JSON to disk.

---

## Task 0: Create Supabase migration SQL

**Files:**
- Create: `migrations/sp1/001_hil_logging_events.sql`

This migration is **not auto-applied** by code. The deploy runbook is: apply this SQL via Supabase Dashboard → SQL Editor (or `psql $DATABASE_URL -f migrations/sp1/001_hil_logging_events.sql`) before deploying SP1 code.

- [ ] **Step 1: Create the migration directory**

```bash
mkdir -p migrations/sp1
```

- [ ] **Step 2: Write the migration file**

Create `migrations/sp1/001_hil_logging_events.sql` with this exact content:

```sql
-- SP1 Telemetry Foundation — 2026-05-10
-- Adds private.hil_logging_events for ε-greedy propensity logging,
-- and adds private.hil_reviews.logging_event_id FK column.
-- Idempotent: safe to re-run.

create extension if not exists "uuid-ossp";
create schema if not exists private;

create table if not exists private.hil_logging_events (
  id                bigserial primary key,
  event_id          uuid        not null,
  candidate_idx     int         not null,
  candidate_score   numeric     not null,
  candidate_rank    int         not null,
  candidate_payload jsonb       not null,
  in_greedy_slate   boolean     not null,
  was_shown         boolean     not null,
  branch            text        not null
                    check (branch in ('greedy','explore','degenerate')),
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

create index if not exists hil_logging_events_event_id_idx
  on private.hil_logging_events(event_id);
create index if not exists hil_logging_events_review_id_idx
  on private.hil_logging_events(review_id) where review_id is not null;
create index if not exists hil_logging_events_batch_run_at_idx
  on private.hil_logging_events(batch_run_at desc);

alter table private.hil_reviews
  add column if not exists logging_event_id uuid;

create index if not exists hil_reviews_logging_event_id_idx
  on private.hil_reviews(logging_event_id);
```

- [ ] **Step 3: Lint-check the SQL**

Manually verify: every `create` is `if not exists`; the unique constraint is `(event_id, candidate_idx)`; the propensity check matches the spec (`> 0 and <= 1`).

- [ ] **Step 4: Commit**

```bash
git add migrations/sp1/001_hil_logging_events.sql
git commit -m "feat(sp1): add hil_logging_events migration"
```

---

## Task 1: Add Supabase table constant + .env.example documentation

**Files:**
- Modify: `el/supabase.py:10-12`
- Modify: `.env.example` (append at end)

- [ ] **Step 1: Add the table constant to `el/supabase.py`**

Find these lines (currently lines 10–12):

```python
HIL_REVIEWS_TABLE = "hil_reviews"
HIL_REVIEW_EVENTS_TABLE = "hil_review_events"
HIL_REVIEWS_SCHEMA = "private"
```

Add immediately after them:

```python
HIL_LOGGING_EVENTS_TABLE = "hil_logging_events"
```

- [ ] **Step 2: Document the new env vars in `.env.example`**

Append this block at the end of `.env.example` (after the existing `TELEGRAM_ALERT_CHAT_ID=""` line):

```bash


# ------------------------------------------------------------------------------
# 10. SP1 Telemetry / ε-greedy logging policy                         [OPTIONAL]
# ------------------------------------------------------------------------------
# Used by:  el/nodes/stochastic_logger.py
# These control the stochastic HIL slate sampler that produces propensities
# for the Phase 3 paper's IPS analysis. Defaults are production-safe.

# Master kill switch. Set to "false" to revert to pre-SP1 deterministic phase4
# behavior with one config change. Default: "true".
EL_HIL_LOGGING_ENABLED="true"

# Exploration rate ε ∈ [0, 1]. ε=0 ⇒ deterministic phase4 (regression-equivalent).
# ε=1 ⇒ uniform random K-subset every batch. Default: 0.1.
EL_HIL_EPSILON="0.1"

# Optional integer seed for the slate sampler RNG. Leave unset in production
# (true random). Tests pass an explicit seed for reproducibility.
EL_HIL_LOGGING_RNG_SEED=""
```

- [ ] **Step 3: Verify nothing else broke**

```bash
.venv\Scripts\python.exe -c "from el import supabase; print(supabase.HIL_LOGGING_EVENTS_TABLE)"
```

Expected output: `hil_logging_events`

- [ ] **Step 4: Commit**

```bash
git add el/supabase.py .env.example
git commit -m "feat(sp1): add hil_logging_events table constant + env docs"
```

---

## Task 2: Modify phase4_candidate_selection to emit eligible_pool

**Goal:** Refactor `select_candidates` internals so its `run(ctx)` can also expose the deduped pre-cap pool as `ctx["eligible_pool"]`. Public function signatures stay identical; existing tests stay green.

**Files:**
- Modify: `el/nodes/phase4_candidate_selection.py:688-815` (`select_candidates` and `run`)
- Modify: `tests/test_phase4_candidate_selection.py` (add 2 tests at end of file)

### TDD: write failing tests first

- [ ] **Step 1: Add the eligible_pool tests to `tests/test_phase4_candidate_selection.py`**

Append at end of file:

```python
def test_run_emits_eligible_pool_alongside_phase4_candidates():
    """Phase4 run() must populate ctx["eligible_pool"] with the deduped, pre-cap pool.

    Each entry has the shape required by stochastic_logger:
    candidate_payload, candidate_score, candidate_rank, in_greedy_slate.
    """
    ctx = {"review_candidates": [_candidate(), _candidate(product_url="https://app.cjdropshipping.com/product/PID2.html", product_sku="SKU2")]}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-07T12:00:00Z")

    assert "eligible_pool" in ctx
    pool = ctx["eligible_pool"]
    assert isinstance(pool, list)
    assert len(pool) >= 1
    for idx, entry in enumerate(pool):
        assert set(entry.keys()) == {
            "candidate_payload",
            "candidate_score",
            "candidate_rank",
            "in_greedy_slate",
        }
        assert isinstance(entry["candidate_payload"], dict)
        assert isinstance(entry["candidate_score"], float)
        assert entry["candidate_rank"] == idx + 1
        assert isinstance(entry["in_greedy_slate"], bool)


def test_eligible_pool_marks_selected_candidates_as_in_greedy_slate():
    """Items that ended up in phase4_candidates must have in_greedy_slate=True;
    items that were deduped-in but cap-rejected must have in_greedy_slate=False."""
    rows = [_candidate() for _ in range(15)]
    for i, row in enumerate(rows):
        row["product_url"] = f"https://app.cjdropshipping.com/product/PID{i}.html"
        row["product_sku"] = f"SKU{i}"
        row["product_name"] = f"Wireless Earbuds Pro {i}"
    ctx = {"review_candidates": rows}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-07T12:00:00Z")

    selected = ctx["phase4_candidates"]
    pool = ctx["eligible_pool"]

    selected_count = sum(1 for e in pool if e["in_greedy_slate"])
    assert selected_count == len(selected)
    assert len(pool) >= len(selected)
```

- [ ] **Step 2: Run the failing tests**

```bash
.venv\Scripts\python.exe -m pytest tests/test_phase4_candidate_selection.py::test_run_emits_eligible_pool_alongside_phase4_candidates tests/test_phase4_candidate_selection.py::test_eligible_pool_marks_selected_candidates_as_in_greedy_slate -v
```

Expected: both tests FAIL with `KeyError: 'eligible_pool'` or `AssertionError: 'eligible_pool' not in {...}`.

### Implementation

- [ ] **Step 3: Refactor `select_candidates` to expose the pool**

In `el/nodes/phase4_candidate_selection.py`, replace the entire `select_candidates` function (currently starting at line 688) with this version:

```python
def _select_internal(
    rows: list[dict], *, selected_at: str | None = None
) -> tuple[list[dict], list[PreparedCandidate]]:
    """Internal: return (selected_rows, deduped_candidates).

    deduped_candidates is the post-mismatch/dedupe pool BEFORE caps.
    selected_rows is the same list select_candidates returned historically.
    """
    now_value = selected_at or _now_iso()
    prepared = [prepare_candidate(row) for row in rows]
    eligible = sorted(
        [entry for entry in prepared if not entry.rejection_reasons],
        key=_sort_key,
    )

    deduped: list[PreparedCandidate] = []
    for candidate in eligible:
        duplicate_of = None
        for kept in deduped:
            same_url = bool(candidate.url and kept.url and candidate.url == kept.url)
            same_image = bool(candidate.img and kept.img and candidate.img == kept.img)
            same_topic = normalize_text(candidate.row.get("source_topic")) == normalize_text(kept.row.get("source_topic"))
            same_host = bool(candidate.host and kept.host and candidate.host == kept.host)
            similar_name = overlap_ratio(candidate.name_tokens, kept.name_tokens) >= 0.8
            if same_url or same_image or (same_topic and same_host and similar_name):
                duplicate_of = kept
                break
        if duplicate_of:
            candidate.rejection_reasons.append(build_reason(
                "dedupe",
                "duplicate_candidate",
                "Blocked because a higher-ranked near-duplicate was already kept.",
                {
                    "duplicate_of_product": duplicate_of.row.get("product_name") or None,
                    "duplicate_of_url": duplicate_of.row.get("product_url") or None,
                    "duplicate_of_score": duplicate_of.score,
                },
            ))
            continue
        deduped.append(candidate)

    per_topic_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    selected: list[PreparedCandidate] = []
    for candidate in deduped:
        topic_key = normalize_text(candidate.row.get("source_topic"))
        provider_key = compact(candidate.row.get("source_provider")).lower()
        topic_count = per_topic_counts.get(topic_key, 0)
        provider_count = provider_counts.get(provider_key, 0)

        if topic_count >= TOPIC_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "topic_cap_reached",
                "Blocked because this topic already reached the phase 4 queue cap.",
                {"topic_cap": TOPIC_CAP, "topic": candidate.row.get("source_topic")},
            ))
            continue
        if provider_key == "cj_dropshipping" and provider_count >= CJ_PROVIDER_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "provider_cap_reached",
                "Blocked because the CJ provider cap was reached.",
                {"provider_cap": CJ_PROVIDER_CAP, "source_provider": provider_key},
            ))
            continue
        if provider_key == "browserbase_marketplace" and provider_count >= BROWSERBASE_PROVIDER_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "provider_cap_reached",
                "Blocked because the browserbase provider cap was reached.",
                {"provider_cap": BROWSERBASE_PROVIDER_CAP, "source_provider": provider_key},
            ))
            continue
        if len(selected) >= TOTAL_CAP:
            candidate.rejection_reasons.append(build_reason(
                "cap",
                "total_cap_reached",
                "Blocked because the overall phase 4 queue cap was reached.",
                {"total_cap": TOTAL_CAP},
            ))
            continue

        per_topic_counts[topic_key] = topic_count + 1
        provider_counts[provider_key] = provider_count + 1
        candidate.selected = True
        selected.append(candidate)

    if not selected:
        fallback_pool = sorted(
            [
                candidate for candidate in prepared
                if not has_terminal_rejection(candidate)
                and has_only_score_rejections(candidate)
                and has_fallback_evidence(candidate)
                and candidate.score >= FALLBACK_MIN_SCORE
            ],
            key=lambda candidate: -candidate.score,
        )
        for candidate in fallback_pool[:FALLBACK_MAX_ITEMS]:
            candidate.selected = True
            candidate.rejection_reasons = [
                reason for reason in candidate.rejection_reasons
                if reason.get("stage") != "score"
            ]
            candidate.rejection_reasons.append(build_reason(
                "fallback",
                "fallback_selected",
                "Selected by fallback because strict phase 4 produced an empty queue.",
                {"score": candidate.score, "fallback_min_score": FALLBACK_MIN_SCORE},
            ))
            selected.append(candidate)

    output = []
    for index, candidate in enumerate(selected, start=1):
        selection = {
            "phase": "phase4_candidate_selection",
            "topic_intent_type": candidate.context["topic_intent_type"],
            "confidence_score": candidate.score,
            "queue_rank": index,
            "selected_at": now_value,
            "source_host": candidate.host or None,
            "dedupe_name_key": candidate.normalized_name or None,
        }
        output.append(attach_payload(candidate, selection))
    return output, deduped


def select_candidates(rows: list[dict], *, selected_at: str | None = None) -> list[dict]:
    """Public: return the selected candidates list, exactly as before."""
    selected, _pool = _select_internal(rows, selected_at=selected_at)
    return selected


def build_eligible_pool(
    deduped: list[PreparedCandidate], selected_rows: list[dict]
) -> list[dict]:
    """Serialize the pre-cap deduped pool for ctx["eligible_pool"].

    Each entry: {candidate_payload, candidate_score, candidate_rank, in_greedy_slate}.
    candidate_rank is 1-based, in deduped order (sorted desc by selection_score).
    in_greedy_slate is True iff the candidate's row appears in selected_rows.
    """
    selected_keys = {
        (compact(r.get("product_url")).lower(), compact(r.get("product_sku")).lower())
        for r in selected_rows
    }
    pool: list[dict] = []
    for idx, candidate in enumerate(deduped, start=1):
        key = (
            compact(candidate.row.get("product_url")).lower(),
            compact(candidate.row.get("product_sku")).lower(),
        )
        pool.append({
            "candidate_payload": dict(candidate.row),
            "candidate_score": float(candidate.score),
            "candidate_rank": idx,
            "in_greedy_slate": key in selected_keys,
        })
    return pool
```

- [ ] **Step 4: Update `run` to populate `ctx["eligible_pool"]`**

In the same file, replace the `run` function (currently lines 809-815) with:

```python
def run(ctx: dict, *, selected_at: str | None = None) -> dict:
    rows = [item for item in (ctx.get("review_candidates") or []) if isinstance(item, dict)]
    selected, deduped = _select_internal(rows, selected_at=selected_at)
    ctx["phase4_candidates"] = selected
    ctx["eligible_pool"] = build_eligible_pool(deduped, selected)
    log.info(
        "Phase 4 Candidate Selection: selected %d of %d candidates (eligible pool %d)",
        len(selected), len(rows), len(ctx["eligible_pool"]),
    )
    return ctx
```

- [ ] **Step 5: Run the new tests + the existing phase4 test suite**

```bash
.venv\Scripts\python.exe -m pytest tests/test_phase4_candidate_selection.py -v
```

Expected: all tests pass, including the 2 new ones AND every pre-existing test in that file.

- [ ] **Step 6: Run the full test suite to confirm zero regression elsewhere**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all tests green (the existing 400 + the 2 new = 402+).

- [ ] **Step 7: Commit**

```bash
git add el/nodes/phase4_candidate_selection.py tests/test_phase4_candidate_selection.py
git commit -m "feat(sp1): emit eligible_pool ctx field from phase4_candidate_selection"
```

---

## Task 3: stochastic_logger pure helpers (TDD)

**Goal:** Stateless, seedable functions for propensity arithmetic and slate sampling. No Supabase, no ctx, no IO.

**Files:**
- Create: `tests/test_stochastic_logger.py`
- Create: `el/nodes/stochastic_logger.py` (helpers section only — `run()` comes in Task 4)

### TDD: write the failing tests first

- [ ] **Step 1: Create `tests/test_stochastic_logger.py` with the helper tests**

```python
"""Tests for el/nodes/stochastic_logger.py."""
from __future__ import annotations

import math
import random
from collections import Counter

import pytest

from el.nodes import stochastic_logger


# -- compute_marginal_propensity ------------------------------------------------

def test_marginal_propensity_in_greedy_slate():
    # P(i shown | i in G) = (1 - eps) + eps * K / N
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=0.1
    )
    assert p == pytest.approx(0.9 + 0.1 * 10 / 30, rel=1e-9)


def test_marginal_propensity_not_in_greedy_slate():
    # P(i shown | i not in G) = eps * K / N
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=0.1
    )
    assert p == pytest.approx(0.1 * 10 / 30, rel=1e-9)


def test_marginal_propensity_epsilon_zero_in_greedy():
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=0.0
    )
    assert p == pytest.approx(1.0)


def test_marginal_propensity_epsilon_zero_not_in_greedy_is_zero():
    """At ε=0 a non-greedy item has 0 probability — outside policy support."""
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=0.0
    )
    assert p == pytest.approx(0.0)


def test_marginal_propensity_epsilon_one_uniform():
    p_in = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=1.0
    )
    p_out = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=1.0
    )
    assert p_in == pytest.approx(10 / 30)
    assert p_out == pytest.approx(10 / 30)


def test_marginal_propensity_degenerate_n_le_k():
    # When N <= K, every eligible item is shown; propensity = 1.
    p_in = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=5, epsilon=0.1
    )
    p_out = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=5, epsilon=0.1
    )
    assert p_in == pytest.approx(1.0)
    assert p_out == pytest.approx(1.0)


def test_marginal_propensity_pool_size_zero_returns_zero():
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=0, epsilon=0.1
    )
    assert p == pytest.approx(0.0)


# -- sample_slate ---------------------------------------------------------------

def test_sample_slate_epsilon_zero_returns_greedy_exactly():
    """ε=0 must return the greedy slate byte-for-byte (regression-safety mode)."""
    eligible = [{"id": i} for i in range(20)]
    greedy = eligible[:10]
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=0.0, rng=rng)
    assert slate == greedy
    assert branch == "greedy"


def test_sample_slate_epsilon_one_returns_uniform_subset():
    eligible = [{"id": i} for i in range(20)]
    greedy = eligible[:10]
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=1.0, rng=rng)
    assert branch == "explore"
    assert len(slate) == 10
    # All items in slate are from the eligible pool
    eligible_ids = {e["id"] for e in eligible}
    slate_ids = {s["id"] for s in slate}
    assert slate_ids.issubset(eligible_ids)
    # No duplicates
    assert len(slate_ids) == len(slate)


def test_sample_slate_degenerate_pool_le_slate_returns_all():
    eligible = [{"id": i} for i in range(5)]
    greedy = list(eligible)
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=0.1, rng=rng)
    assert branch == "degenerate"
    assert slate == eligible


def test_sample_slate_empty_pool_returns_empty():
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate([], [], epsilon=0.1, rng=rng)
    assert slate == []
    assert branch == "degenerate"


def test_sample_slate_empirical_propensity_matches_analytical():
    """Property test: across many trials, empirical P(item shown) ≈ analytical."""
    eligible = [{"id": i} for i in range(30)]
    greedy = eligible[:10]
    epsilon = 0.1
    n_trials = 5000
    rng = random.Random(0xC0FFEE)
    counts: Counter[int] = Counter()
    for _ in range(n_trials):
        slate, _ = stochastic_logger.sample_slate(eligible, greedy, epsilon=epsilon, rng=rng)
        for item in slate:
            counts[item["id"]] += 1

    # Analytical: in-greedy ≈ 0.9333; out-greedy ≈ 0.0333.
    in_greedy_analytical = 0.9 + 0.1 * 10 / 30
    out_greedy_analytical = 0.1 * 10 / 30

    for item_id in range(10):  # in-greedy
        empirical = counts[item_id] / n_trials
        assert math.isclose(empirical, in_greedy_analytical, abs_tol=0.03), (
            f"item {item_id} (in-greedy): empirical {empirical}, analytical {in_greedy_analytical}"
        )
    for item_id in range(10, 30):  # out-greedy
        empirical = counts[item_id] / n_trials
        assert math.isclose(empirical, out_greedy_analytical, abs_tol=0.02), (
            f"item {item_id} (out-greedy): empirical {empirical}, analytical {out_greedy_analytical}"
        )


def test_sample_slate_branch_distribution_matches_epsilon():
    """Across many trials, branch=='explore' fraction ≈ ε."""
    eligible = [{"id": i} for i in range(30)]
    greedy = eligible[:10]
    epsilon = 0.3
    n_trials = 2000
    rng = random.Random(123)
    explore_count = 0
    for _ in range(n_trials):
        _, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=epsilon, rng=rng)
        if branch == "explore":
            explore_count += 1
    empirical_eps = explore_count / n_trials
    assert math.isclose(empirical_eps, epsilon, abs_tol=0.03)
```

- [ ] **Step 2: Run tests — they should fail with import error**

```bash
.venv\Scripts\python.exe -m pytest tests/test_stochastic_logger.py -v
```

Expected: collection error / `ImportError: cannot import name 'stochastic_logger' from 'el.nodes'`.

### Implementation

- [ ] **Step 3: Create `el/nodes/stochastic_logger.py` with the helpers**

Create the file with this exact content (the `run()` function will be added in Task 4 — for now we leave a `NotImplementedError` placeholder):

```python
"""SP1 telemetry node — slate-level ε-greedy sampler + propensity logging.

Pure helpers (compute_marginal_propensity, sample_slate) are stateless and
seedable for testing. The run(ctx) entry point is added in Task 4.

Spec: docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md
"""
from __future__ import annotations

import random
from typing import Literal

Branch = Literal["greedy", "explore", "degenerate"]


def compute_marginal_propensity(
    *, in_greedy: bool, slate_size: int, pool_size: int, epsilon: float
) -> float:
    """Marginal P(item shown) under slate-level ε-greedy mixture.

    Mixture: with prob (1-ε) S = G; with prob ε S = uniform K-subset of E.
    For item i:
        P(i in S) = (1 - ε) · 𝟙[i ∈ G] + ε · K / N

    Edge cases:
      pool_size == 0  → 0.0  (item is not in any pool, so not loggable)
      pool_size <= slate_size  → 1.0  (degenerate: everyone shown)
    """
    if pool_size <= 0:
        return 0.0
    if pool_size <= slate_size:
        return 1.0
    explore_term = epsilon * slate_size / pool_size
    if in_greedy:
        return (1.0 - epsilon) + explore_term
    return explore_term


def sample_slate(
    eligible: list[dict],
    greedy: list[dict],
    *,
    epsilon: float,
    rng: random.Random,
) -> tuple[list[dict], Branch]:
    """Sample a slate via the ε-greedy mixture.

    Returns (slate, branch). slate is a list of items drawn from `eligible`;
    branch ∈ {'greedy', 'explore', 'degenerate'}.

    - Empty pool → ([], 'degenerate').
    - pool_size <= slate_size (== len(greedy) by phase4 contract) → return all
      eligible items, branch='degenerate'. ε is ignored in this case.
    - Otherwise: with prob 1-ε return greedy unchanged ('greedy');
      with prob ε return a uniform random K-subset of eligible ('explore').
    """
    pool_size = len(eligible)
    if pool_size == 0:
        return [], "degenerate"
    slate_size = len(greedy)
    if pool_size <= slate_size:
        return list(eligible), "degenerate"
    if rng.random() < epsilon:
        slate = rng.sample(eligible, slate_size)
        return slate, "explore"
    return list(greedy), "greedy"
```

- [ ] **Step 4: Run the helper tests**

```bash
.venv\Scripts\python.exe -m pytest tests/test_stochastic_logger.py -v
```

Expected: all 13 tests in this file pass.

- [ ] **Step 5: Run the full test suite to confirm no regression**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all tests green (402 + 13 = 415+).

- [ ] **Step 6: Commit**

```bash
git add el/nodes/stochastic_logger.py tests/test_stochastic_logger.py
git commit -m "feat(sp1): add stochastic_logger pure helpers (propensity + sampler)"
```

---

## Task 4: stochastic_logger.run() — ctx wiring + Supabase integration

**Goal:** Add the `run(ctx)` entry point. It reads `ctx["eligible_pool"]` and `ctx["phase4_candidates"]`, samples a slate, computes propensities for every item with propensity > 0, inserts those rows to `private.hil_logging_events`, and sets `ctx["hil_slate"]` + `ctx["logging_event_id"]`. All failures degrade to passthrough.

**Files:**
- Modify: `el/nodes/stochastic_logger.py` (append run + helpers)
- Modify: `tests/test_stochastic_logger.py` (append run() tests)

### TDD: write failing tests first

- [ ] **Step 1: Append run() tests to `tests/test_stochastic_logger.py`**

Add at the end of the file:

```python
# -- run(ctx) integration -------------------------------------------------------

class FakeProvider:
    """Mimics SupabaseRestProvider for the subset of methods stochastic_logger uses."""

    def __init__(self, *, fail_on: str | None = None):
        self.inserts: list[dict] = []
        self.fail_on = fail_on

    def insert_rows(self, *, schema: str, table: str, rows: list[dict]):
        if self.fail_on == "insert":
            raise RuntimeError("supabase down")
        self.inserts.append({"schema": schema, "table": table, "rows": rows})
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _eligible_entry(idx: int, score: float, in_greedy: bool) -> dict:
    return {
        "candidate_payload": {"product_sku": f"SKU{idx}", "product_url": f"https://x/{idx}"},
        "candidate_score": score,
        "candidate_rank": idx + 1,
        "in_greedy_slate": in_greedy,
    }


def _phase4_row(idx: int) -> dict:
    return {"product_sku": f"SKU{idx}", "product_url": f"https://x/{idx}", "extra": "phase4_attached"}


def test_run_passthrough_when_logging_disabled(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "false")
    provider = FakeProvider()
    ctx = {
        "eligible_pool": [_eligible_entry(i, 50.0 - i, i < 2) for i in range(5)],
        "phase4_candidates": [_phase4_row(0), _phase4_row(1)],
    }
    stochastic_logger.run(ctx, provider=provider)
    assert ctx["hil_slate"] == ctx["phase4_candidates"]
    assert ctx["logging_event_id"] == ""
    assert ctx["hil_slate_branch"] == "passthrough"
    assert provider.inserts == []


def test_run_passthrough_when_eligible_pool_empty(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    provider = FakeProvider()
    ctx = {"eligible_pool": [], "phase4_candidates": []}
    stochastic_logger.run(ctx, provider=provider)
    assert ctx["hil_slate"] == []
    assert ctx["logging_event_id"] == ""
    assert ctx["hil_slate_branch"] == "passthrough"
    assert provider.inserts == []


def test_run_writes_one_row_per_pool_item_when_epsilon_positive(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.1")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "42")
    provider = FakeProvider()
    pool = [_eligible_entry(i, 50.0 - i, i < 3) for i in range(10)]
    ctx = {
        "eligible_pool": pool,
        "phase4_candidates": [_phase4_row(0), _phase4_row(1), _phase4_row(2)],
    }
    stochastic_logger.run(ctx, provider=provider)

    assert len(provider.inserts) == 1
    inserted = provider.inserts[0]["rows"]
    assert len(inserted) == 10
    # Every row shares the same event_id
    event_ids = {r["event_id"] for r in inserted}
    assert len(event_ids) == 1
    # Every row has all required schema fields with valid values
    for row in inserted:
        assert 0 < row["propensity"] <= 1
        assert row["branch"] in {"greedy", "explore", "degenerate"}
        assert row["epsilon"] == 0.1
        assert row["pool_size"] == 10
        assert row["slate_size"] == 3
        assert isinstance(row["candidate_idx"], int)
        assert isinstance(row["was_shown"], bool)
        assert isinstance(row["in_greedy_slate"], bool)


def test_run_epsilon_zero_only_logs_greedy_items(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "1")
    provider = FakeProvider()
    pool = [_eligible_entry(i, 50.0 - i, i < 3) for i in range(10)]
    ctx = {
        "eligible_pool": pool,
        "phase4_candidates": [_phase4_row(0), _phase4_row(1), _phase4_row(2)],
    }
    stochastic_logger.run(ctx, provider=provider)

    inserted = provider.inserts[0]["rows"]
    # Only 3 rows — the greedy items, all with propensity=1 and was_shown=True
    assert len(inserted) == 3
    for row in inserted:
        assert row["propensity"] == 1.0
        assert row["in_greedy_slate"] is True
        assert row["was_shown"] is True
        assert row["branch"] == "greedy"
    assert ctx["hil_slate"] == ctx["phase4_candidates"]


def test_run_supabase_failure_falls_through_to_passthrough(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.2")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "7")
    provider = FakeProvider(fail_on="insert")
    pool = [_eligible_entry(i, 50.0 - i, i < 2) for i in range(5)]
    ctx = {
        "eligible_pool": pool,
        "phase4_candidates": [_phase4_row(0), _phase4_row(1)],
    }
    stochastic_logger.run(ctx, provider=provider)
    # Pipeline must not crash; hil_slate falls back to phase4_candidates
    assert ctx["hil_slate"] == ctx["phase4_candidates"]
    assert ctx["logging_event_id"] == ""
    assert ctx["hil_slate_branch"] == "passthrough"


def test_run_degenerate_mode_when_pool_le_slate(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.1")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "5")
    provider = FakeProvider()
    pool = [_eligible_entry(i, 50.0 - i, True) for i in range(2)]
    phase4 = [_phase4_row(0), _phase4_row(1)]
    ctx = {"eligible_pool": pool, "phase4_candidates": phase4}
    stochastic_logger.run(ctx, provider=provider)

    inserted = provider.inserts[0]["rows"]
    assert len(inserted) == 2
    for row in inserted:
        assert row["propensity"] == 1.0
        assert row["was_shown"] is True
        assert row["branch"] == "degenerate"
    assert ctx["hil_slate_branch"] == "degenerate"


def test_run_logging_event_id_is_uuid_hex(monkeypatch):
    import re

    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.1")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "11")
    provider = FakeProvider()
    pool = [_eligible_entry(i, 50.0 - i, i < 2) for i in range(5)]
    ctx = {"eligible_pool": pool, "phase4_candidates": [_phase4_row(0), _phase4_row(1)]}
    stochastic_logger.run(ctx, provider=provider)
    # Standard uuid hyphenated form, 36 chars
    assert re.fullmatch(r"[0-9a-f-]{36}", ctx["logging_event_id"]), ctx["logging_event_id"]
```

- [ ] **Step 2: Run tests — they should fail (run() not yet implemented)**

```bash
.venv\Scripts\python.exe -m pytest tests/test_stochastic_logger.py -v -k "test_run_"
```

Expected: 7 tests fail with `AttributeError: module 'el.nodes.stochastic_logger' has no attribute 'run'`.

### Implementation

- [ ] **Step 3a: Add new imports at the TOP of `el/nodes/stochastic_logger.py`**

Find the existing import block at the top of the file:

```python
from __future__ import annotations

import random
from typing import Literal
```

Replace it with:

```python
from __future__ import annotations

import random
import uuid
from typing import Literal

from el import config, supabase
from el.logger import get_logger

log = get_logger(__name__)
```

- [ ] **Step 3b: Append helpers and `run()` at the END of `el/nodes/stochastic_logger.py`**

Add at the END of the file (after the `sample_slate` function):

```python
def _env_bool(name: str, default: bool) -> bool:
    raw = config.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = config.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("Invalid float for %s: %r — falling back to %s", name, raw, default)
        return default


def _env_int_or_none(name: str) -> int | None:
    raw = config.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid int for %s: %r — using non-deterministic RNG", name, raw)
        return None


def _build_rng() -> random.Random:
    seed = _env_int_or_none("EL_HIL_LOGGING_RNG_SEED")
    return random.Random(seed) if seed is not None else random.Random()


def _passthrough(ctx: dict) -> dict:
    ctx["hil_slate"] = list(ctx.get("phase4_candidates") or [])
    ctx["logging_event_id"] = ""
    ctx["hil_slate_branch"] = "passthrough"
    return ctx


def _candidate_key(payload: dict) -> tuple[str, str]:
    return (
        str(payload.get("product_url") or "").strip().lower(),
        str(payload.get("product_sku") or "").strip().lower(),
    )


def _build_logging_rows(
    *,
    event_id: str,
    eligible_pool: list[dict],
    slate_keys: set[tuple[str, str]],
    branch: Branch,
    epsilon: float,
    pool_size: int,
    slate_size: int,
) -> list[dict]:
    rows: list[dict] = []
    for entry in eligible_pool:
        payload = entry["candidate_payload"]
        in_greedy = bool(entry["in_greedy_slate"])
        propensity = compute_marginal_propensity(
            in_greedy=in_greedy,
            slate_size=slate_size,
            pool_size=pool_size,
            epsilon=epsilon,
        )
        if propensity <= 0:
            # Outside the policy's support — IPS weight undefined; do not log.
            continue
        was_shown = _candidate_key(payload) in slate_keys
        rows.append({
            "event_id": event_id,
            "candidate_idx": int(entry["candidate_rank"]) - 1,
            "candidate_score": float(entry["candidate_score"]),
            "candidate_rank": int(entry["candidate_rank"]),
            "candidate_payload": payload,
            "in_greedy_slate": in_greedy,
            "was_shown": was_shown,
            "branch": branch,
            "propensity": propensity,
            "epsilon": epsilon,
            "pool_size": pool_size,
            "slate_size": slate_size,
        })
    return rows


def run(
    ctx: dict,
    *,
    provider: supabase.SupabaseRestProvider | None = None,
) -> dict:
    """Sample slate via ε-greedy mixture, log propensities, set hil_slate.

    On any failure: passthrough to phase4_candidates. Pipeline never crashes.
    """
    if not _env_bool("EL_HIL_LOGGING_ENABLED", default=True):
        log.info("stochastic_logger: EL_HIL_LOGGING_ENABLED=false → passthrough")
        return _passthrough(ctx)

    eligible_pool = ctx.get("eligible_pool") or []
    phase4_candidates = ctx.get("phase4_candidates") or []

    if not eligible_pool:
        log.info("stochastic_logger: empty eligible_pool → passthrough")
        return _passthrough(ctx)

    epsilon = _env_float("EL_HIL_EPSILON", default=0.1)
    epsilon = max(0.0, min(1.0, epsilon))

    rng = _build_rng()
    eligible_payloads = [e["candidate_payload"] for e in eligible_pool]
    greedy_payloads = [e["candidate_payload"] for e in eligible_pool if e["in_greedy_slate"]]

    try:
        slate, branch = sample_slate(
            eligible_payloads, greedy_payloads, epsilon=epsilon, rng=rng
        )
    except Exception:
        log.exception("stochastic_logger: sampler crashed → passthrough")
        return _passthrough(ctx)

    # Map sampled payloads back to phase4-attached rows when possible (greedy
    # branch only: the explore branch may surface payloads phase4 dropped).
    slate_keys = {_candidate_key(p) for p in slate}
    if branch == "greedy":
        hil_slate = list(phase4_candidates)
    else:
        # Explore / degenerate: build hil_slate from the raw eligible_pool
        # payloads. Downstream nodes (supabase_insert_hil_reviews, etc.) expect
        # the same shape phase4 emitted, which is the row dict the candidates
        # came in as. We surface eligible_pool payloads as-is.
        hil_slate = list(slate)

    event_id = uuid.uuid4().hex
    # Reformat to standard hyphenated UUID for the DB
    event_id_db = str(uuid.UUID(event_id))

    pool_size = len(eligible_pool)
    slate_size = len(greedy_payloads)

    rows = _build_logging_rows(
        event_id=event_id_db,
        eligible_pool=eligible_pool,
        slate_keys=slate_keys,
        branch=branch,
        epsilon=epsilon,
        pool_size=pool_size,
        slate_size=slate_size,
    )

    if not rows:
        log.info("stochastic_logger: no rows to log (all propensities zero) → passthrough")
        return _passthrough(ctx)

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        active_provider.insert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.HIL_LOGGING_EVENTS_TABLE,
            rows=rows,
        )
    except Exception:
        log.exception("stochastic_logger: Supabase insert failed → passthrough")
        return _passthrough(ctx)

    ctx["hil_slate"] = hil_slate
    ctx["logging_event_id"] = event_id_db
    ctx["hil_slate_branch"] = branch
    log.info(
        "stochastic_logger: branch=%s pool=%d slate=%d ε=%.3f rows_logged=%d event_id=%s",
        branch, pool_size, slate_size, epsilon, len(rows), event_id_db,
    )
    return ctx
```

- [ ] **Step 4: Run all stochastic_logger tests**

```bash
.venv\Scripts\python.exe -m pytest tests/test_stochastic_logger.py -v
```

Expected: all 20 tests pass (13 helper + 7 run-integration).

- [ ] **Step 5: Run the full test suite**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add el/nodes/stochastic_logger.py tests/test_stochastic_logger.py
git commit -m "feat(sp1): add stochastic_logger.run() with Supabase logging"
```

---

## Task 5: Modify supabase_insert_hil_reviews to read hil_slate + write logging_event_id

**Goal:** Switch the upsert source from `ctx["phase4_candidates"]` to `ctx["hil_slate"]`, and stamp every row with `ctx["logging_event_id"]` (when present).

**Files:**
- Modify: `el/nodes/supabase_insert_hil_reviews.py:29-30` (the `run` function — read source + payload extension)
- Modify: `tests/test_supabase_insert_hil_reviews.py` (add 2 tests)

### TDD: write the failing tests first

- [ ] **Step 1: Look at the existing test file to mirror the pattern**

```bash
.venv\Scripts\python.exe -c "import os; print(os.path.exists('tests/test_supabase_insert_hil_reviews.py'))"
```

If the file exists, append the new tests at the end. If not, create it.

- [ ] **Step 2: Add tests to `tests/test_supabase_insert_hil_reviews.py`**

If the file does not exist, create it with this content. If it does, **append** these test functions at the end (preserving any existing `_row()` helper; otherwise add the helper too):

```python
"""Tests for el/nodes/supabase_insert_hil_reviews.py — SP1 additions."""
from __future__ import annotations

import json

from el.nodes import supabase_insert_hil_reviews


class _CapturingProvider:
    def __init__(self):
        self.upsert_calls: list[dict] = []

    def upsert_rows(self, *, schema: str, table: str, rows: list[dict], conflict_columns):
        self.upsert_calls.append({
            "schema": schema,
            "table": table,
            "rows": rows,
            "conflict_columns": conflict_columns,
        })
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _hil_row(idx: int = 0, **overrides) -> dict:
    base = {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": f"EL:2026-05-10:run{idx}",
        "source_provider": "cj_dropshipping",
        "source_topic": f"Topic {idx}",
        "product_name": f"Product {idx}",
        "product_url": f"https://x/{idx}",
        "image_urls": json.dumps([]),
        "raw_payload": json.dumps({}),
        "approval_status": "pending",
    }
    base.update(overrides)
    return base


def test_insert_reads_from_hil_slate_when_present():
    ctx = {
        "hil_slate": [_hil_row(0), _hil_row(1)],
        "phase4_candidates": [_hil_row(99)],  # should be ignored
        "logging_event_id": "11111111-1111-1111-1111-111111111111",
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    assert len(upserted_rows) == 2
    skus = [r["product_url"] for r in upserted_rows]
    assert "https://x/0" in skus and "https://x/1" in skus
    assert "https://x/99" not in skus


def test_insert_stamps_logging_event_id_on_every_row():
    event_id = "22222222-2222-2222-2222-222222222222"
    ctx = {
        "hil_slate": [_hil_row(0), _hil_row(1)],
        "logging_event_id": event_id,
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    for row in upserted_rows:
        assert row["logging_event_id"] == event_id


def test_insert_omits_logging_event_id_when_empty():
    """Passthrough mode: logging_event_id is "" — column should not be set."""
    ctx = {
        "hil_slate": [_hil_row(0)],
        "logging_event_id": "",
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    row = provider.upsert_calls[0]["rows"][0]
    assert "logging_event_id" not in row or row["logging_event_id"] is None


def test_insert_falls_back_to_phase4_candidates_when_hil_slate_missing():
    """Backward-compat: if a caller forgets to wire stochastic_logger, the
    upstream phase4_candidates list still works. Required so partial deploys
    (code without the stochastic_logger wired into pipeline.py yet) don't
    silently no-op."""
    ctx = {
        "phase4_candidates": [_hil_row(7)],
    }
    provider = _CapturingProvider()
    supabase_insert_hil_reviews.run(ctx, provider=provider)
    upserted_rows = provider.upsert_calls[0]["rows"]
    assert len(upserted_rows) == 1
    assert upserted_rows[0]["product_url"] == "https://x/7"
```

- [ ] **Step 3: Run the tests — they should fail**

```bash
.venv\Scripts\python.exe -m pytest tests/test_supabase_insert_hil_reviews.py -v
```

Expected: the 4 new tests fail (current code reads `phase4_candidates`, not `hil_slate`).

### Implementation

- [ ] **Step 4: Modify `el/nodes/supabase_insert_hil_reviews.py`**

Replace the `run` function (currently lines 29–60) with:

```python
def run(ctx: dict, provider: supabase.SupabaseRestProvider | None = None) -> dict:
    # Prefer hil_slate (set by stochastic_logger). Fall back to phase4_candidates
    # so partial deploys keep working.
    source = ctx.get("hil_slate")
    if source is None:
        source = ctx.get("phase4_candidates") or []
    rows = [prepare_row(row) for row in source if isinstance(row, dict)]

    logging_event_id = ctx.get("logging_event_id") or ""
    if logging_event_id:
        for row in rows:
            row["logging_event_id"] = logging_event_id

    if not rows:
        ctx["hil_reviews_upsert_result"] = {"ok": True, "rows": 0, "data": []}
        log.info("Supabase Insert (HIL Reviews): no rows to upsert")
        return ctx

    active_provider = provider or supabase.SupabaseRestProvider()
    try:
        data = active_provider.upsert_rows(
            schema=supabase.HIL_REVIEWS_SCHEMA,
            table=supabase.HIL_REVIEWS_TABLE,
            rows=rows,
            conflict_columns=supabase.HIL_REVIEWS_CONFLICT_COLUMNS,
        )
    except Exception as exc:
        ctx["hil_reviews_upsert_result"] = {
            "ok": False,
            "rows": len(rows),
            "error": str(exc),
        }
        log.exception("Supabase Insert (HIL Reviews) failed")
        return ctx

    ctx["hil_reviews_upsert_result"] = {
        "ok": True,
        "rows": len(rows),
        "data": data,
    }
    ctx["hil_review_rows"] = data
    log.info("Supabase Insert (HIL Reviews): upserted %d rows", len(rows))
    return ctx
```

- [ ] **Step 5: Run the tests for this file**

```bash
.venv\Scripts\python.exe -m pytest tests/test_supabase_insert_hil_reviews.py -v
```

Expected: all tests pass (4 new + any pre-existing).

- [ ] **Step 6: Run the full test suite**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add el/nodes/supabase_insert_hil_reviews.py tests/test_supabase_insert_hil_reviews.py
git commit -m "feat(sp1): supabase_insert_hil_reviews reads hil_slate + stamps logging_event_id"
```

---

## Task 6: Wire stochastic_logger into pipeline.py

**Files:**
- Modify: `el/pipeline.py:6-36` (imports) and `el/pipeline.py:88-93` (insertion point)

- [ ] **Step 1: Add the import**

In `el/pipeline.py`, find the import block at the top (lines 6–36) and insert `stochastic_logger` alphabetically — between `score_rank` and `supabase_insert_hil_reviews`:

```python
from el.nodes import (
    answer_hil_callback,
    apply_hil_callback,
    build_search_query,
    cj_get_token,
    cj_product_list,
    create_curated_picks_tab,
    create_day_tab,
    curate_picks,
    download_product_image,
    drive_upload,
    filter_top_30,
    if_callback_finalized_review,
    mark_telegram_photo_sent,
    mark_telegram_text_fallback,
    merge_review_sources,
    normalize_cj_review,
    parse_hil_callback,
    phase4_candidate_selection,
    pick_top_3,
    prepare_json_file,
    prepare_sheet_rows,
    prepare_telegram_card,
    score_rank,
    send_hil_telegram_photo,
    send_hil_telegram_text_fallback,
    stochastic_logger,
    supabase_insert_hil_reviews,
    write_curated_picks,
    write_rows_to_sheet,
    youtube_trending,
)
```

- [ ] **Step 2: Insert the call between phase4 and supabase_insert**

In `el/pipeline.py`, find this block (currently at lines ~86–93):

```python
                cj_get_token.run(ctx)
                cj_product_list.run(ctx)
                pick_top_3.run(ctx)
                normalize_cj_review.run(ctx)
                merge_review_sources.run(ctx)
                phase4_candidate_selection.run(ctx)
                if config.get("SUPABASE_URL") and (
                    config.get("SUPABASE_SERVICE_ROLE_KEY")
                    or config.get("SUPABASE_SECRET_KEY")
                    or config.get("SUPABASE_KEY")
                ):
                    supabase_insert_hil_reviews.run(ctx)
```

Insert `stochastic_logger.run(ctx)` immediately after `phase4_candidate_selection.run(ctx)` (and BEFORE the Supabase config check — the logger handles its own Supabase availability and degrades to passthrough internally):

```python
                cj_get_token.run(ctx)
                cj_product_list.run(ctx)
                pick_top_3.run(ctx)
                normalize_cj_review.run(ctx)
                merge_review_sources.run(ctx)
                phase4_candidate_selection.run(ctx)
                stochastic_logger.run(ctx)
                if config.get("SUPABASE_URL") and (
                    config.get("SUPABASE_SERVICE_ROLE_KEY")
                    or config.get("SUPABASE_SECRET_KEY")
                    or config.get("SUPABASE_KEY")
                ):
                    supabase_insert_hil_reviews.run(ctx)
```

- [ ] **Step 3: Run the full test suite to confirm zero regression in any pipeline test**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all green. The pipeline-level tests (if any) keep working because: (a) `stochastic_logger` falls through to passthrough when no Supabase env is set, (b) `supabase_insert_hil_reviews` falls back to `phase4_candidates` when `hil_slate` is absent.

- [ ] **Step 4: Commit**

```bash
git add el/pipeline.py
git commit -m "feat(sp1): wire stochastic_logger into pipeline between phase4 and HIL"
```

---

## Task 7: End-to-end integration test

**Goal:** A single test exercising the new contract: phase4 → stochastic_logger → supabase_insert_hil_reviews, with all external IO mocked. Verifies (a) one row per eligible item is inserted into `hil_logging_events`, (b) the matching `hil_reviews` rows carry the correct `logging_event_id`.

**Files:**
- Create: `tests/test_pipeline_with_logging.py`

- [ ] **Step 1: Create the integration test file**

Create `tests/test_pipeline_with_logging.py`:

```python
"""End-to-end SP1 integration: phase4 → stochastic_logger → hil_reviews insert.

External IO mocked. Verifies the full ctx contract between the three nodes
that SP1 touches.
"""
from __future__ import annotations

import json

from el.nodes import (
    phase4_candidate_selection,
    stochastic_logger,
    supabase_insert_hil_reviews,
)


class _UnifiedFakeProvider:
    """Single fake implementing both insert_rows (logging events)
    and upsert_rows (hil_reviews)."""

    def __init__(self):
        self.inserts: list[dict] = []
        self.upserts: list[dict] = []

    def insert_rows(self, *, schema, table, rows):
        self.inserts.append({"schema": schema, "table": table, "rows": rows})
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]

    def upsert_rows(self, *, schema, table, rows, conflict_columns):
        self.upserts.append({
            "schema": schema, "table": table, "rows": rows,
            "conflict_columns": conflict_columns,
        })
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]


def _candidate(idx: int) -> dict:
    raw_payload = {
        "source": "cj_dropshipping",
        "offer": {"listedNum": 20, "categoryName": "Collectibles"},
        "raw_payload": {"pid": f"PID{idx}", "productNameEn": f"Wireless Earbuds {idx}"},
    }
    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": "EL:2026-05-10:test",
        "run_date": "2026-05-10",
        "source_provider": "cj_dropshipping",
        "source_topic": f"Wireless Earbuds {idx}",
        "source_pick_rank": 1,
        "opportunity_score": 8.5,
        "product_name": f"Wireless Earbuds Pro {idx}",
        "product_url": f"https://app.cjdropshipping.com/product/PID{idx}.html",
        "product_sku": f"SKU{idx}",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": f"https://img.example/{idx}.jpg",
        "image_urls": json.dumps([f"https://img.example/{idx}.jpg"]),
        "description": "Bluetooth earbuds with compact charging case",
        "supplier_name": "Supplier",
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": json.dumps(raw_payload),
        "scraped_at": "2026-05-10T10:00:00Z",
    }


def test_end_to_end_pipeline_writes_logging_rows_and_stamps_reviews(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0.0")  # deterministic — greedy slate only
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "1")

    rows = [_candidate(i) for i in range(5)]
    ctx = {"review_candidates": rows}

    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    assert "phase4_candidates" in ctx and "eligible_pool" in ctx
    assert len(ctx["phase4_candidates"]) >= 1

    provider = _UnifiedFakeProvider()
    stochastic_logger.run(ctx, provider=provider)
    assert ctx["logging_event_id"] != ""
    assert ctx["hil_slate_branch"] == "greedy"

    # Logging table got 1 row per greedy item (ε=0 → only greedy logged)
    inserted = provider.inserts[0]["rows"]
    assert len(inserted) == len(ctx["phase4_candidates"])
    for row in inserted:
        assert row["propensity"] == 1.0
        assert row["was_shown"] is True
        assert row["branch"] == "greedy"
        assert row["event_id"] == ctx["logging_event_id"]

    supabase_insert_hil_reviews.run(ctx, provider=provider)

    # hil_reviews rows all carry the same logging_event_id
    upserted = provider.upserts[0]["rows"]
    assert len(upserted) == len(ctx["phase4_candidates"])
    for row in upserted:
        assert row["logging_event_id"] == ctx["logging_event_id"]


def test_end_to_end_explore_branch_logs_full_pool(monkeypatch):
    """ε=1 forces explore branch; every eligible_pool item must be logged."""
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "1.0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "13")

    rows = [_candidate(i) for i in range(15)]
    ctx = {"review_candidates": rows}

    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    pool_size = len(ctx["eligible_pool"])

    provider = _UnifiedFakeProvider()
    stochastic_logger.run(ctx, provider=provider)

    if ctx["hil_slate_branch"] == "degenerate":
        # Pool was <= K — degenerate; every item logged with propensity=1.
        inserted = provider.inserts[0]["rows"]
        assert len(inserted) == pool_size
    else:
        assert ctx["hil_slate_branch"] == "explore"
        inserted = provider.inserts[0]["rows"]
        assert len(inserted) == pool_size  # every eligible item logged
        # Some out-of-greedy items should have was_shown == True
        out_greedy_shown = [r for r in inserted if not r["in_greedy_slate"] and r["was_shown"]]
        assert len(out_greedy_shown) > 0
```

- [ ] **Step 2: Run the integration tests**

```bash
.venv\Scripts\python.exe -m pytest tests/test_pipeline_with_logging.py -v
```

Expected: both tests pass.

- [ ] **Step 3: Run the full suite**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_with_logging.py
git commit -m "test(sp1): add end-to-end pipeline integration test"
```

---

## Task 8: Regression-safety acceptance test (ε=0 byte-identical)

**Goal:** Lock in the spec's success criterion #3 — with `EL_HIL_EPSILON=0`, the rows reaching `hil_reviews` are byte-identical to a pre-SP1 baseline (modulo the new `logging_event_id` column).

**Files:**
- Create: `tests/test_sp1_regression_safety.py`

- [ ] **Step 1: Create the regression-safety test**

Create `tests/test_sp1_regression_safety.py`:

```python
"""SP1 regression-safety acceptance test.

Asserts: with EL_HIL_EPSILON=0, the hil_slate that would be inserted into
hil_reviews is byte-identical to the phase4_candidates list — i.e. SP1 makes
zero behavioral change to the HIL queue under the regression-safety mode.
"""
from __future__ import annotations

import copy
import json

from el.nodes import phase4_candidate_selection, stochastic_logger


class _NoOpProvider:
    def insert_rows(self, **_kwargs):
        return []

    def upsert_rows(self, **_kwargs):
        return []


def _candidate(idx: int) -> dict:
    raw_payload = {
        "source": "cj_dropshipping",
        "offer": {"listedNum": 20, "categoryName": "Collectibles"},
        "raw_payload": {"pid": f"PID{idx}", "productNameEn": f"Earbuds {idx}"},
    }
    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": "EL:2026-05-10:reg",
        "run_date": "2026-05-10",
        "source_provider": "cj_dropshipping",
        "source_topic": f"Earbuds {idx}",
        "source_pick_rank": 1,
        "opportunity_score": 8.5,
        "product_name": f"Earbuds Pro {idx}",
        "product_url": f"https://app.cjdropshipping.com/product/PID{idx}.html",
        "product_sku": f"SKU{idx}",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": f"https://img.example/{idx}.jpg",
        "image_urls": json.dumps([f"https://img.example/{idx}.jpg"]),
        "description": "Bluetooth earbuds",
        "supplier_name": "Supplier",
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": json.dumps(raw_payload),
        "scraped_at": "2026-05-10T10:00:00Z",
    }


def test_epsilon_zero_hil_slate_byte_identical_to_phase4_candidates(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "999")

    rows = [_candidate(i) for i in range(20)]
    ctx = {"review_candidates": copy.deepcopy(rows)}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    phase4_baseline = copy.deepcopy(ctx["phase4_candidates"])

    stochastic_logger.run(ctx, provider=_NoOpProvider())

    assert ctx["hil_slate_branch"] == "greedy"
    assert ctx["hil_slate"] == phase4_baseline


def test_logging_disabled_hil_slate_byte_identical_to_phase4_candidates(monkeypatch):
    """Master kill switch must produce the same byte-identical guarantee."""
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "false")

    rows = [_candidate(i) for i in range(20)]
    ctx = {"review_candidates": copy.deepcopy(rows)}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    phase4_baseline = copy.deepcopy(ctx["phase4_candidates"])

    stochastic_logger.run(ctx, provider=_NoOpProvider())

    assert ctx["hil_slate_branch"] == "passthrough"
    assert ctx["hil_slate"] == phase4_baseline
    assert ctx["logging_event_id"] == ""
```

- [ ] **Step 2: Run the regression-safety tests**

```bash
.venv\Scripts\python.exe -m pytest tests/test_sp1_regression_safety.py -v
```

Expected: both tests pass.

- [ ] **Step 3: Run the full test suite — final green check**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe -m pytest tests/ --cov=el --cov-report=term-missing
```

Expected: 
- All tests green.
- Coverage report shows `el/nodes/stochastic_logger.py` ≥ 95%.

- [ ] **Step 4: Commit**

```bash
git add tests/test_sp1_regression_safety.py
git commit -m "test(sp1): add ε=0 regression-safety acceptance test"
```

---

## Task 9: Documentation — SP1 iteration log

**Files:**
- Create: `docs/SP1_LOG.md`

- [ ] **Step 1: Create the SP1 iteration log**

Create `docs/SP1_LOG.md`:

```markdown
# SP1 — Telemetry Foundation Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md`
**Plan:** `docs/superpowers/plans/2026-05-10-sp1-telemetry-foundation.md`
**Started:** 2026-05-10
**Completed:** <fill in on completion>

## Summary

SP1 is the first sub-project of the Phase 3 SaaS end-to-end build. It adds a
slate-level ε-greedy stochastic logging policy on top of the existing
deterministic `phase4_candidate_selection`, and persists closed-form marginal
propensities to a new `private.hil_logging_events` Supabase table. Every HIL
event collected after SP1 deploys carries the propensity-of-being-shown that
SP7's IPS / DR analysis depends on.

## What changed

| Area | Change |
|------|--------|
| Schema | New table `private.hil_logging_events`; new `logging_event_id` column on `private.hil_reviews`. Migration in `migrations/sp1/001_hil_logging_events.sql` (manually applied). |
| Pipeline | Added `el/nodes/stochastic_logger.py` between `phase4_candidate_selection` and `supabase_insert_hil_reviews`. |
| Phase4 | Refactored internals into `_select_internal` returning `(selected_rows, deduped_pool)`. Added `build_eligible_pool` helper. Public `select_candidates(...)` signature unchanged. |
| HIL insert | `supabase_insert_hil_reviews` now reads from `ctx["hil_slate"]` (with fallback to `ctx["phase4_candidates"]`) and stamps `logging_event_id` when present. |
| Config | New env vars: `EL_HIL_LOGGING_ENABLED`, `EL_HIL_EPSILON`, `EL_HIL_LOGGING_RNG_SEED`. |

## Deploy runbook

1. Apply the migration via Supabase SQL Editor or `psql $DATABASE_URL -f migrations/sp1/001_hil_logging_events.sql`. Confirm `private.hil_logging_events` exists and `private.hil_reviews.logging_event_id` is added.
2. Set the new env vars in production `.env` (defaults are fine; no action required if you accept ε=0.1).
3. Deploy the new code. Run `pytest tests/ -q` against the deployed venv as a smoke check.
4. Run one production batch (`python -m el run`). Verify a row per eligible candidate appears in `hil_logging_events` and that every newly-inserted `hil_reviews` row has `logging_event_id` populated.
5. After 30 days of data collection, hand off to SP7 (paper).

## Rollback

Set `EL_HIL_LOGGING_ENABLED=false` in `.env` and redeploy (or restart the worker). Pipeline reverts to pre-SP1 deterministic behavior with one config change. The table and column remain (idempotent migration); no schema rollback needed.

## Acceptance verification

- [ ] All 400 pre-SP1 tests pass.
- [ ] New tests pass at coverage ≥ 95% for `el/nodes/stochastic_logger.py`.
- [ ] `tests/test_sp1_regression_safety.py` passes — confirming ε=0 produces byte-identical `hil_slate`.
- [ ] One end-to-end production run writes ≥ 1 row to `hil_logging_events` and FK-matches `hil_reviews`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/SP1_LOG.md
git commit -m "docs(sp1): add SP1 iteration log + deploy runbook"
```

---

## Final verification

- [ ] **Run the full suite one more time and confirm coverage**

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe -m pytest tests/ --cov=el --cov-report=term-missing
```

Expected:
- All tests green.
- `el/nodes/stochastic_logger.py` coverage ≥ 95%.
- `el/nodes/phase4_candidate_selection.py` coverage same or higher than pre-SP1 (refactor is internal-only).

- [ ] **Verify migration is committed but not auto-applied**

```bash
git log --oneline -- migrations/sp1
```

Expected: one commit `feat(sp1): add hil_logging_events migration`. No auto-apply hook in code.

- [ ] **Sanity-check the new env vars are documented**

```bash
grep -A1 "EL_HIL_" .env.example
```

Expected: 3 new env vars documented with comments.

---

## Spec coverage map

| Spec section | Implementing task(s) |
|--------------|----------------------|
| §3.1 pipeline diagram | Tasks 2, 4, 5, 6 |
| §3.2 file changes table | Tasks 0–9 (one row per task) |
| §3.3 ctx contract additions | Tasks 2 (`eligible_pool`), 4 (`hil_slate`, `logging_event_id`, `hil_slate_branch`) |
| §4 stochastic logging policy | Task 3 (helpers), Task 4 (run integration) |
| §4.4 edge cases | Task 3 (degenerate, empty), Task 4 (passthrough variants) |
| §5.1 new table DDL | Task 0 |
| §5.2 alter hil_reviews | Task 0 |
| §6 configuration | Tasks 1 (.env.example), 4 (env-reading helpers in `run`) |
| §7 error handling | Task 4 (every failure path tested) |
| §8 testing strategy | Tasks 3, 4, 5, 7, 8 |
| §9 backfill / data hygiene | Task 9 (documented in SP1_LOG); no code change |
| §11 out of scope | Enforced by absence of any matching task |
| §12 success criteria | Task 8 (#3 byte-identical) + Task 9 (#5 docs) + Final verification |

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-10-sp1-telemetry-foundation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
