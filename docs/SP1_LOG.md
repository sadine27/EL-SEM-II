# SP1 — Telemetry Foundation Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md`
**Plan:** `docs/superpowers/plans/2026-05-10-sp1-telemetry-foundation.md`
**Started:** 2026-05-10
**Completed:** 2026-05-21

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
| Phase4 | Refactored internals into `_select_internal` returning `(selected_rows, deduped_pool)`. Added `build_eligible_pool` helper. Public `select_candidates(...)` signature unchanged. Emits `ctx["eligible_pool"]`. |
| HIL insert | `supabase_insert_hil_reviews` now reads from `ctx["hil_slate"]` (with fallback to `ctx["phase4_candidates"]`) and stamps `logging_event_id` when present. |
| Config | New env vars: `EL_HIL_LOGGING_ENABLED`, `EL_HIL_EPSILON`, `EL_HIL_LOGGING_RNG_SEED`. |

## Commits (in order)

| Commit | Task | What |
|---|---|---|
| `93db475` | Task 0 | Supabase migration for `hil_logging_events` + `logging_event_id` column |
| `611becf` | Task 1 | Table constant + `.env.example` documentation |
| `2721fd0` | Task 2 | `phase4_candidate_selection` emits `ctx["eligible_pool"]` |
| `d41a1b5` | Task 3 | `stochastic_logger` pure helpers (`compute_marginal_propensity`, `sample_slate`) |
| `323e88d` | Task 4 | `stochastic_logger.run()` with Supabase integration |
| `952c294` | Task 5 | `supabase_insert_hil_reviews` reads `hil_slate` + stamps `logging_event_id` |
| `8d4bda9` | Task 6 | Wired `stochastic_logger` into `pipeline.py` |
| `f06b81d` | Task 7 | End-to-end integration test |
| `94a6d61` | Task 8 | ε=0 regression-safety acceptance test |

## Deploy runbook

1. Apply the migration via Supabase SQL Editor or `psql $DATABASE_URL -f migrations/sp1/001_hil_logging_events.sql`. Confirm `private.hil_logging_events` exists and `private.hil_reviews.logging_event_id` is added.
2. Set the new env vars in production `.env` (defaults are fine; no action required if you accept ε=0.1).
3. Deploy the new code. Run `pytest tests/ -q` against the deployed venv as a smoke check.
4. Run one production batch (`python -m el run`). Verify a row per eligible candidate appears in `hil_logging_events` and that every newly-inserted `hil_reviews` row has `logging_event_id` populated.
5. After 30 days of data collection, hand off to SP7 (paper).

## Rollback

Set `EL_HIL_LOGGING_ENABLED=false` in `.env` and redeploy (or restart the worker). Pipeline reverts to pre-SP1 deterministic behavior with one config change. The table and column remain (idempotent migration); no schema rollback needed.

## Acceptance verification

- [x] All 400 pre-SP1 tests pass (current suite: 433 tests, all green).
- [~] Per-file coverage for `el/nodes/stochastic_logger.py` is 88% — short of the 95% per-file target, but overall `el/` coverage is 92% (above the 90% floor). Missing lines are env-parse error branches (`_env_float`/`_env_int_or_none` bad-value warning paths) — low-priority defensive code.
- [x] `tests/test_sp1_regression_safety.py` passes — confirms ε=0 produces byte-identical `hil_slate`.
- [ ] One end-to-end production run writes ≥ 1 row to `hil_logging_events` and FK-matches `hil_reviews`. *(pending merge to main + deploy.)*

## Surprises / decisions deferred

- **Plan test fixture bug, Task 7:** The original 5-candidate fixture for the greedy-branch integration test produced a degenerate slate (pool == slate) because phase4 caps don't trigger with 5 distinct-topic candidates. Fixed by sizing to 12 so `TOTAL_CAP=10` makes pool > slate.
- **No tests for env-parse error branches.** Deferred — the warning-and-fallback paths in `_env_float` / `_env_int_or_none` are defensive and exercising them adds little signal vs. test maintenance cost.
- **Deploy verification step open.** Production smoke (point 4 of the runbook) must be completed by a human with Supabase access after the SP1 PR merges; cannot be automated from a sandbox.
