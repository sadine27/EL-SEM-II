# Phase 3 SaaS — Execution Roadmap

**Created:** 2026-05-21
**Owner:** Divyesh Sharma
**Scope:** Sequence and gate the work required to finish the Phase 3 SaaS end-to-end build defined in `docs/superpowers/specs/2026-05-10-phase3-saas-master-design.md`.
**Cadence target:** 30–35 working days at 4–6 focused hours/day.

This is a **meta-document**. It does not design or specify any sub-project. Each sub-project (SP1–SP8) gets its own design spec + implementation plan via just-in-time brainstorming when its turn comes.

---

## Status snapshot

_Last updated: 2026-05-21 (SP1 implementation complete, pre-merge)._

| SP | Title | Status | Notes |
|---|---|---|---|
| SP1 | Telemetry Foundation | 🟢 code complete, pre-merge | All 10 plan tasks committed on `feat/sp1-telemetry-foundation`. 433/433 tests green, 92% overall coverage. Iteration log at `docs/SP1_LOG.md`. Awaiting merge to `main`. |
| SP2 | Source Expansion | ⬜ not started | Design pending. |
| SP3 | Vision + pgvector | ⬜ not started | Design pending. |
| SP4 | FastAPI + RAG chat bot | ⬜ not started | Design pending. Depends on SP3. |
| SP5 | Outbound (email, Shopify auto-store, notify) | ⬜ not started | Design pending. |
| SP6 | CRM minimal | ⬜ not started | Design pending. Depends on SP1+SP4+SP5. |
| SP8 | Docker + Hetzner deploy | ⬜ not started | Design pending. Depends on all user-facing SPs. |
| SP7 | Paper pipeline (IPS overrides) | ⬜ not started | Depends on SP1 + ≥100 accrued events. Sequenced last. |

**Next action:** Merge SP1 to `main` (squash-merge per the branch/PR strategy), then start SP2 brainstorming. Production smoke (run one batch against the live Supabase, verify `hil_logging_events` rows + `logging_event_id` stamping on `hil_reviews`) must be done by a human with credentials after merge.

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

### SP2 — Source Expansion ⬜

- **Branch:** `feat/sp2-source-expansion` (to create from fresh `main`)
- **Master-spec deliverables:** `el/sources/` protocol, Google Trends, Meta Ad Library, TikTok Creative Center, AliExpress trending, Shopify-link scraper, pipeline merge adapter.
- **Credentials to confirm at SP-start:** none new — uses existing Browserbase.
- **Estimated effort:** 5–7 days.

### SP3 — Vision + pgvector ⬜

- **Branch:** `feat/sp3-vision-pgvector`
- **Master-spec deliverables:** `pgvector` migration, `private.product_embeddings` table + HNSW indexes, `el/embeddings.py`, `el/nodes/embed_candidate_products.py`, `el/nodes/find_similar_products.py`, optional Bing Visual Search.
- **Credentials to confirm at SP-start:** Vertex SA already authenticated; Supabase service-role can run `create extension`. Optional: Bing Visual Search free key.
- **Estimated effort:** 5–7 days.

### SP4 — FastAPI + RAG chat bot ⬜

- **Branch:** `feat/sp4-web-and-chat`
- **Master-spec deliverables:** `el/web/` FastAPI app, HTMX/Tailwind templates, `el/nodes/telegram_chat_trigger.py`, Supabase Auth magic-link, rate limiting, chat-bot grounded by SP3 pgvector RAG.
- **Credentials to confirm at SP-start:** `WEB_BASE_URL`, `WEB_SECRET_KEY` (random), `SUPABASE_AUTH_JWT_SECRET`.
- **Estimated effort:** 5–7 days.

### SP5 — Outbound ⬜

- **Branch:** `feat/sp5-outbound`
- **Master-spec deliverables:** `el/email.py` Gmail SMTP, `el/nodes/email_digest.py`, `el/nodes/email_product_detail.py`, `el/shopify.py`, `el/nodes/generate_shopify_theme.py`, `el/nodes/upload_shopify_theme.py`, `el/nodes/upload_shopify_products.py`, `el/nodes/notify_business.py`.
- **Credentials to confirm at SP-start:** `GMAIL_SMTP_USER`, `GMAIL_SMTP_APP_PASSWORD`, `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_ADMIN_API_TOKEN`, `SHOPIFY_API_VERSION`, `BUSINESS_NOTIFY_TELEGRAM_CHAT_ID`.
- **Estimated effort:** 5–7 days.

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

_None yet._
