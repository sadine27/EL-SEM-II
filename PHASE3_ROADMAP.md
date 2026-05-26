# Phase 3 SaaS — Execution Roadmap

**Created:** 2026-05-21
**Owner:** Divyesh Sharma
**Scope:** Sequence and gate the work required to finish the Phase 3 SaaS end-to-end build defined in `docs/superpowers/specs/2026-05-10-phase3-saas-master-design.md`.
**Cadence target:** 30–35 working days at 4–6 focused hours/day.

This is a **meta-document**. It does not design or specify any sub-project. Each sub-project (SP1–SP8) gets its own design spec + implementation plan via just-in-time brainstorming when its turn comes.

---

## Status snapshot

_Last updated: 2026-05-26 (SP6 squash-merged to main)._

| SP | Title | Status | Notes |
|---|---|---|---|
| SP1 | Telemetry Foundation | ✅ merged to main | All 10 plan tasks merged via fast-forward (see Roadmap revisions §1). 433/433 tests green, 92% overall coverage. Iteration log at `docs/SP1_LOG.md`. **Pending:** human-driven production smoke run (see SP1_LOG runbook §4). |
| SP2 | Source Expansion | ✅ merged to main | Squash-merged at `cbb6b9a`. Scoped to 2 sources (YouTube refactor + Shopify competitor); 4 sources deferred per SP2 design spec §1. 463/463 tests green. Iteration log at `docs/SP2_LOG.md`. **Pending:** optional production smoke if Shopify-competitor is enabled. |
| SP3 | Vision + pgvector | ✅ merged to main | Squash-merged at `dc2d400`. Vertex multimodal embeddings + pgvector HNSW + find_similar helper. Bing Visual Search deferred. 488/488 tests green. **Pending:** apply migration + production smoke (verify Vertex spend ≤ $0.02). |
| SP4 | FastAPI + RAG chat bot | ✅ merged to main | Squash-merged at `8c1b3da`. FastAPI app at `el/web/`, bearer auth, in-memory rate limit, RAG chat over SSE, HTMX shell pages. Supabase Auth magic-link + Telegram WebApp + Redis deferred to SP6/SP8. 555/555 tests green. Iteration log at `docs/SP4_LOG.md`. **Pending:** apply migration + browser smoke per SP4_LOG runbook. |
| SP5 | Outbound (email, Shopify auto-store, notify) | ✅ merged to main | Squash-merged at `6eac26c`. Bundles SP5a (Gmail SMTP digest + per-product) and SP5b (Shopify Admin API theme + product upload); `notify_business` delivers live store URL. 602/602 tests green. Design specs at `docs/superpowers/specs/2026-05-22-sp5a-outbound-email-design.md` and `2026-05-22-sp5b-shopify-auto-store-design.md`. **Pending:** configure Gmail app password + Shopify dev-store creds in prod `.env`; live smoke of email + theme + product upload. |
| SP6 | CRM minimal | ✅ merged to main | Squash-merged at `e3019ad`. Supabase tables `private.suppliers` + `private.disputes` + `private.niche_performance`; `el/crm.py` data layer; `record_niche_performance` pipeline node; `/crm` HTMX dashboard + `/api/crm/*` routes extending SP4. 661/661 tests green. Design spec at `docs/superpowers/specs/2026-05-26-sp6-crm-design.md`. **Pending:** apply migration `migrations/sp6/001_crm_tables.sql` in production Supabase; browser smoke of `/crm` dashboard. |
| SP8 | Docker + Hetzner deploy | ⬜ not started | Design pending. Depends on all user-facing SPs. |
| SP7 | Paper pipeline (IPS overrides) | ⬜ not started | Depends on SP1 + ≥100 accrued events. Sequenced last. |

**Next action:** Start SP8 (Docker + Hetzner deploy). Pending human-side: SP1–SP5 production smokes (unchanged); SP6 production smoke = apply `migrations/sp6/001_crm_tables.sql` in production Supabase + verify `/crm` dashboard loads.

**Step 0 status:** ✅ complete (2026-05-21). Paper work parked on `paper/phase2-revision` at commit `de79243`. `EL report content.docx` deleted (was an old Word version of the paper).

---

## Step 0 — Branch hygiene (one-time, before any new code)

1. Create branch `paper/phase2-revision` from current `feat/sp1-telemetry-foundation` working tree.
2. Triage `paper_review.md` against the uncommitted paper changes: confirm each file (`paper/main.tex`, `paper/references.bib`, `paper/main.pdf`, new scripts in `scripts/`, new figures, new JSON in `data/`, `EL report content.docx`) is intentional. Drop anything that isn't.
3. Commit the survivors as a single snapshot: `wip(paper): phase 2 revision snapshot (in-flight reviewer fixes)`.
4. Return to `feat/sp1-telemetry-foundation` with a clean working tree.
5. Park `paper/phase2-revision` indefinitely. Do not touch until Phase 3 SaaS is shipped.

**Definition of done for Step 0:** `git status` on `feat/sp1-telemetry-foundation` shows only SP1-related changes (or nothing).

---

## Sub-project queue

Sequencing follows the master spec's dependencies, with two intentional deviations from the master-spec critical path:

- **SP7 moved to last**, not parallel with SP8. Reason: maximize event-accrual window; avoid paper-writing context-switch during deploy.
- **SP2 not parallel with SP1.** That parallelism window closed when SP1 reached ~40% before SP2 design started. Functionally equivalent to do SP2 immediately after SP1.

```
SP1 ─► SP2 ─► SP3 ─► SP4 ─► SP5 ─► SP6 ─► SP8 ─► SP7
```

### SP1 — Telemetry Foundation 🟢

- **Branch:** `feat/sp1-telemetry-foundation` (ready to merge)
- **Design:** `docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md` ✅
- **Plan:** `docs/superpowers/plans/2026-05-10-sp1-telemetry-foundation.md` ✅
- **Iteration log:** `docs/SP1_LOG.md` ✅
- **All 10 tasks committed.** 433/433 tests green, 92% overall coverage.
- **Pending:** squash-merge to `main`; post-merge production smoke run.

### SP2 — Source Expansion ✅

- **Merged:** `cbb6b9a` (squash) on 2026-05-21.
- **Design:** `docs/superpowers/specs/2026-05-21-sp2-source-expansion-design.md` ✅
- **Plan:** `docs/superpowers/plans/2026-05-21-sp2-source-expansion.md` ✅
- **Iteration log:** `docs/SP2_LOG.md` ✅
- **Shipped:** `Source` protocol, YouTube source, Shopify-competitor source, pipeline source-loop.
- **Deferred** to future sub-projects: Google Trends via pytrends, Meta Ad Library, TikTok Creative Center, AliExpress trending (see SP2 design spec §1).

### SP3 — Vision + pgvector ✅

- **Merged:** `dc2d400` (squash) on 2026-05-21.
- **Design:** `docs/superpowers/specs/2026-05-21-sp3-vision-pgvector-design.md` ✅
- **Plan:** `docs/superpowers/plans/2026-05-21-sp3-vision-pgvector.md` ✅
- **Iteration log:** `docs/SP3_LOG.md` ✅
- **Shipped:** pgvector migration, `private.product_embeddings` + HNSW indexes, `match_product_embeddings` SQL function, `el/embeddings.py` (Vertex multimodal client + fake), `embed_candidate_products` node wired into pipeline, `find_similar_products` helper, `call_rpc` on supabase client.
- **Deferred:** Bing Visual Search wrapper (optional per master spec).

### SP4 — FastAPI + RAG chat bot ✅

- **Merged:** `8c1b3da` (squash) on 2026-05-22.
- **Design:** `docs/superpowers/specs/2026-05-21-sp4-web-and-chat-design.md` ✅
- **Plan:** `docs/superpowers/plans/2026-05-21-sp4-web-and-chat.md` ✅
- **Iteration log:** `docs/SP4_LOG.md` ✅
- **Shipped:** FastAPI app factory at `el/web/`, bearer-token auth (`hmac.compare_digest`), in-memory token-bucket rate limiter, `chat_rag.stream_answer` RAG generator over SP3 embeddings, SSE `/api/chat`, BackgroundTasks-driven `POST /api/runs`, three HTMX shell pages, `private.run_requests` table.
- **Deferred to SP6/SP8:** Supabase Auth magic-link, Telegram WebApp trigger, Redis/Celery, APScheduler, marketing landing page (per SP4 spec §1).

### SP5 — Outbound ✅

- **Merged:** `6eac26c` (squash) on 2026-05-25.
- **Design:** `docs/superpowers/specs/2026-05-22-sp5a-outbound-email-design.md` + `docs/superpowers/specs/2026-05-22-sp5b-shopify-auto-store-design.md` ✅
- **Shipped:** `el/email.py` (Gmail SMTP w/ retry + STARTTLS), `el/nodes/email_digest.py`, `el/nodes/email_product_detail.py`, `el/shopify.py` (Admin API client w/ idempotency keys + retry), `el/nodes/generate_shopify_theme.py` (Vertex Gemini structured-output), `el/nodes/upload_shopify_theme.py`, `el/nodes/upload_shopify_products.py`, `el/nodes/notify_business.py` (Telegram operator ping w/ live store URL). 47 new tests; 602/602 total green.
- **Deferred:** none (full SP5 scope delivered).

### SP6 — CRM minimal ⬜

- **Branch:** `feat/sp6-crm`
- **Master-spec deliverables:** decision spec for storage choice (Supabase + dashboard vs external), `private.suppliers`, `private.disputes`, `private.niche_performance`, pipeline hook, `/crm` route extension of SP4.
- **Credentials to confirm at SP-start:** TBD (depends on chosen storage).
- **Estimated effort:** 1–2 days spec + 3–5 days build.

### SP8 — Docker + Hetzner deploy ⬜

- **Branch:** `feat/sp8-deploy`
- **Master-spec deliverables:** multi-stage `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `el/web/asgi.py`, `el/web/scheduler.py`, Hetzner bootstrap script, GitHub Actions deploy workflow, Sentry, Caddy, docs.
- **Credentials to confirm at SP-start:** Hetzner account + SSH keypair, `GHCR_TOKEN`, optional `SENTRY_DSN`.
- **Estimated effort:** 4–6 days.

### SP7 — Paper pipeline ⬜

- **Branch:** `feat/sp7-paper`
- **Master-spec deliverables:** `scripts/research/ips_overrides.py`, `scripts/research/override_descriptive.py`, `scripts/research/paper_figures.py`, `paper/phase3_overrides.tex`, unit tests for estimators.
- **Hard precondition:** ≥100 logged HIL events in `private.hil_logging_events`. Decide at SP4 merge whether to extend pipeline schedule to hit this in time.
- **Credentials to confirm at SP-start:** read access to Supabase from analysis machine.
- **Estimated effort:** 10–14 days.

---

## Definition of Done (applies to every SP)

A sub-project is "done" only when **all** of the following are true:

1. Design spec committed at `docs/superpowers/specs/YYYY-MM-DD-spN-<name>-design.md`.
2. Implementation plan committed at `docs/superpowers/plans/YYYY-MM-DD-spN-<name>.md`.
3. All plan tasks executed — each commit references the task it implements.
4. Full `pytest` suite green; line coverage ≥90%; new code has explicit fail-soft tests at every IO boundary.
5. Integration test at `tests/integration/test_spN_*.py` exercises the SP's pipeline subset against fakes.
6. Iteration log section appended to `docs/SP_LOG.md` (created in SP1's Task 9): what shipped, surprises, decisions deferred, credentials added.
7. New env vars documented in `.env.example` with one-line explanation each.
8. PR merged to `main` with a passing CI smoke (`python -m el run --dry-run` against fakes).
9. This roadmap doc updated — SP status flipped to ✅, "Next action" pointer advanced.

**Recommended:** add a default-OFF skip-flag for the SP's new behavior to `.env.example` for the first 24 hours after merge, providing a one-line rollback if the SP misbehaves.

---

## Branch & PR strategy

- One branch per SP: `feat/spN-<short-name>`.
- Merge to `main` between SPs. Never accumulate two unfinished SPs on parallel branches.
- PRs squash-merged so `main` keeps one commit per SP.
- Inside an SP branch, commits stay granular (one per plan task); squash happens at merge.
- Every SP starts from a freshly-pulled `main`.
- No force-pushing to `main`. Force-push on an SP branch only while solo-iterating.
- Uncommitted paper work lives permanently on `paper/phase2-revision` (see Step 0).

---

## Risk register

| Risk | Mitigation |
|---|---|
| Paper work loss | Step 0 stash to `paper/phase2-revision` before any SP1 commit. |
| Event accrual <100 by SP7 start | At SP4 merge, decide: extend pipeline schedule (APScheduler hourly), or downgrade SP7 to "preliminary study" framing. Re-check at SP5 merge. |
| Credential surprise mid-SP (Shopify dev store, Hetzner) | Per-SP gate: confirm creds at SP start, not SP middle. Each SP's design spec lists creds-required up front. |
| Vertex / Browserbase cost overrun | Monthly check after SP3 (embeddings) and SP4 (chat bot). Hard cap configurable via `EL_DAILY_COST_USD_CAP`. |
| Solo brain-fatigue on long SPs (SP4, SP7) | Each plan task ≤2 hours. Sessions end at task boundaries, never mid-task. |
| Session ends mid-SP, context lost | Iteration log entries written at each task boundary, not at SP boundary, so a stale branch can be resumed cold. |
| Master-spec timeline already slipped | Today is 2026-05-21; spec assumed start 2026-05-16. ~5 days of slack already consumed. Re-evaluate timeline at SP1 merge. |

---

## How this roadmap stays current

- The **Status snapshot** block at the top is updated after every merge to `main`.
- The **Next action** line states the single next concrete step.
- Structure is immutable; only status/dates change.
- Re-ordering or re-scoping is recorded as a new **Roadmap revisions** entry below, with date + reason. No silent edits to the queue.

---

## Roadmap revisions

### §1 — 2026-05-21 — SP1 merged as fast-forward, not squash

**Deviation:** Roadmap §Branch & PR strategy specifies squash-merge for SP PRs. SP1 was merged with `git merge --ff-only` instead, preserving 13 granular commits on `main`.

**Reason:** The `feat/sp1-telemetry-foundation` branch contained three distinct units of work — the SP1 implementation, the Phase 3 roadmap meta-document, and Step 0 branch hygiene. Squashing would have produced a single commit message conflating all three. Fast-forward preserves per-task TDD commit history with no information loss and is reversible via `git reset` if needed.

**Future SPs:** Will follow the squash-merge default. SP1's mixed-purpose branch was a one-off artifact of Phase 3 kickoff.
