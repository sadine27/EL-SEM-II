# AI_CONTEXT — Project status for AI agents

> **Read this first.** This file is the single entry point for any AI agent
> (or human) onboarding to the repo. It is the source of truth for *what this
> project is, what is done, and what is left*. Keep it current — see the
> "Maintenance contract" section at the bottom.

**Last updated:** 2026-05-26 (credentials runbook added)
**Current branch context:** Phase 3 SaaS build, mid-SP8.

---

## 1. What this project is

Faithful Python port of an n8n dropshipping pipeline (`legacy/EL.json` +
`legacy/el_error_handler.json`), now being extended into a multi-tenant
SaaS with a FastAPI web layer, a RAG chat bot, vision/pgvector enrichment,
auto-Shopify-store creation, and a Phase 3 research paper on off-policy
evaluation of human overrides.

Two goals share one infrastructure:

1. **SaaS product** — end-to-end automated dropshipping pipeline. User
   submits niche/dislikes/budget → system discovers trends, generates
   candidates, enriches with vision + embeddings, surfaces curated picks
   for human-in-loop (HIL) review on Telegram, and on approval builds a
   Shopify store + emails + notifies.
2. **Phase 3 paper** — *"Off-Policy Evaluation of Human Overrides in
   HIL Product Curation"*. Uses an ε-greedy stochastic logging policy on
   top of BCC-ranked candidates so propensities are known and IPS /
   doubly-robust estimation is unbiased.

---

## 2. Architecture (one-screen view)

```
USER (web form / Telegram)           ── SP4 ──┐
                                              ▼
TRENDING DISCOVERY  (sources/)       ── SP2 ──┤  YouTube ✓, Shopify-competitor ✓
                                              │  G-Trends/Meta/TikTok/AliExpress ⬜ deferred
CANDIDATE GENERATION  (nodes/)       ── port ─┤  score_rank → filter_top_30 → curate_picks → CJ
                                              │
ENRICHMENT  (nodes/, embeddings.py)  ── SP3 ──┤  Browserbase ✓, Tavily ✓, Vertex multimodal ✓, pgvector ✓
                                              │
RANKING + STOCHASTIC POLICY          ── SP1 ──┤  BCC posteriors ✓, ε-greedy logger ✓, hil_logging_events ✓
                                              │
HIL DECISION (Telegram)              ── port ─┤
                                              ▼
OUTBOUND (email + Shopify + notify)  ── SP5 ── Gmail SMTP ✓, Shopify Admin ✓, theme gen ✓, notify ✓

SIDECARS:
  • AI Research Chat (FastAPI + HTMX + SSE)     ── SP4 ✓
  • CRM dashboard                                ── SP6 ⬜
  • IPS / DR / paper figures                     ── SP7 ⬜
HOSTING:
  • Docker + Hetzner + Caddy + GH Actions        ── SP8 🟡 ~40%
```

---

## 3. Status snapshot

**Overall completion: ~65%.** Phase 3 SaaS critical path is 5 of 8 sub-projects merged + 1 mid-flight.

| SP  | Title                                  | Status        | Pending                                                                                                  |
|-----|----------------------------------------|---------------|----------------------------------------------------------------------------------------------------------|
| —   | Python port of n8n workflow            | ✅ done       | 63/63 functional nodes, baseline of the whole project                                                    |
| SP1 | Telemetry foundation (ε-greedy logger) | ✅ merged     | Production smoke (apply migration `migrations/sp1/001_*.sql`, run pipeline, confirm event rows)          |
| SP2 | Source expansion                       | ✅ merged     | Only 2 of 6 source types shipped (YouTube, Shopify competitor). G-Trends/Meta/TikTok/AliExpress deferred |
| SP3 | Vision + pgvector                      | ✅ merged     | Apply `migrations/sp3/001_pgvector_and_embeddings.sql`; verify Vertex spend ≤ $0.02/run. Bing deferred  |
| SP4 | FastAPI + RAG chat                     | ✅ merged     | Apply `migrations/sp4/001_run_requests.sql`; browser smoke. Supabase Auth + Telegram WebApp deferred    |
| SP5 | Outbound (email + Shopify + notify)    | ✅ merged     | Gmail app password + Shopify dev store creds; live send + theme + product upload                         |
| SP6 | CRM minimal                            | ⬜ not started | No design spec yet. First task = author the spec.                                                       |
| SP7 | Paper pipeline (IPS overrides)         | ⬜ not started | Blocked: needs ≥100 logged HIL events in `private.hil_logging_events`                                   |
| SP8 | Docker + Hetzner deploy                | 🟡 ~40%       | Tasks 1–7 of 17 done. Remaining: `el/worker.py`, Dockerfile, Caddyfile, compose, deploy workflow, runbook |

Test baseline: **625 passing**, run with `python -m pytest tests/ -q`.

---

## 4. Where things live

| Path                               | What it is                                                                  |
|------------------------------------|-----------------------------------------------------------------------------|
| `el/pipeline.py`                   | Daily-batch orchestrator. Calls nodes in order, threads `ctx` dict.         |
| `el/nodes/*.py`                    | 63+ pipeline steps. Each exposes `run(ctx, *, provider=None) -> ctx`.       |
| `el/sources/*.py`                  | SP2 trend sources (YouTube, Shopify competitor) behind a `Source` protocol. |
| `el/web/`                          | SP4 FastAPI app (auth, rate limit, SSE chat, HTMX pages, run service).      |
| `el/{supabase,llm,embeddings,...}` | Provider clients. Tests pass `Fake*` instances.                             |
| `el/error_handler.py`              | Port of `legacy/el_error_handler.json` — Telegram dev-alert sink.           |
| `tests/`                           | 625 tests, `conftest.py` defines fakes for every provider.                  |
| `tests/web/`                       | SP4 web-layer tests (TestClient against the FastAPI factory).               |
| `migrations/sp{1,3,4}/`            | One Supabase migration file per SP that needed schema. Apply manually.      |
| `scripts/verify_env.py`            | Live integration check — reads `.env`, probes each provider.                |
| `scripts/verify_env_runtime.py`    | SP8 container entrypoint check — env-only, network-free.                    |
| `scripts/bayesian_calibration.py`  | Phase 2 BCC calibration utility.                                            |
| `scripts/build_phase3_hil.py`      | Standalone HIL Telegram WebApp builder (uses `GEMINI_API_KEY`).             |
| `legacy/EL.json`                   | **Source of truth** for every ported node. Do not drift from it.            |
| `legacy/el_error_handler.json`     | Source of truth for the error handler.                                      |
| `paper/`                           | Phase 2 paper (TeX + bib + PDF + figures). Phase 3 paper goes in SP7.       |
| `docs/PORT_LOG.md`                 | Iteration journal for the n8n→Python port.                                  |
| `docs/SP{1,2,3,4}_LOG.md`          | Iteration journal per merged sub-project.                                   |
| `docs/superpowers/specs/`          | One design spec per SP. Master spec is `2026-05-10-phase3-saas-master-*`.   |
| `docs/superpowers/plans/`          | One implementation plan per SP (task-by-task checklists).                   |
| `docs/runbooks/`                   | Operational runbooks: `credentials.md` (teammate-facing creds guide), `shopify.md`. |
| `docs/legacy/`                     | The original Saas reference: `Saas-PNG.png` + `Saas.pdf`.                   |
| `PHASE3_ROADMAP.md`                | Live roadmap with per-SP status and next-action pointer.                    |
| `.env.example`                     | All required + optional env vars, numbered, with sources.                   |

---

## 5. Conventions

- **Fail-soft at IO boundaries.** Every external call returns `ok=False`
  instead of raising. Downstream nodes guard against missing context keys.
  `tests/test_hardening_edges.py` enforces this.
- **`ctx` is the only inter-node channel.** Keys are namespaced by source:
  `ctx["youtube_trends"]`, `ctx["candidates"]`, `ctx["bcc_scores"]`,
  `ctx["topk_with_propensity"]`, `ctx["hil_decision"]`, etc.
- **Tests use Fakes, never live network.** `tests/conftest.py` and
  `tests/web/conftest.py` provide the fixtures.
- **Coverage floor:** 90%+ line coverage, enforced on Shopify modules in CI.
- **Commits:** Conventional Commits with SP prefix — `feat(sp8):`,
  `test(sp1):`, `docs(phase3):`, etc.
- **Branches:** one `feat/spN-<name>` branch per sub-project, squash-merged
  to `main`. Never two unfinished SPs in flight.
- **Source of truth for nodes:** when in doubt about node behavior, read
  the matching JS in `legacy/EL.json` and match it.

---

## 6. Outstanding work (in priority order)

1. **Finish SP8** (~3–4 days) — `el/worker.py`, Dockerfile, Caddyfile,
   `docker-compose.yml`, GH Actions deploy workflow, Hetzner bootstrap
   script, runbook, opt-in compose smoke test. Plan: `docs/superpowers/plans/2026-05-25-sp8-docker-deploy.md` (Tasks 8–17).
2. **SP6 CRM** (~5–7 days) — author the design spec first; pick storage
   (Supabase tables vs Notion/Airtable/HubSpot vs hybrid).
3. **SP7 paper pipeline** (~10–14 days) — blocked until ≥100 HIL events
   accrue. Build `scripts/research/ips_overrides.py`,
   `override_descriptive.py`, `paper_figures.py`,
   `paper/phase3_overrides.tex`.
4. **Pending production smokes** (human-driven):
   - SP1: Supabase access to confirm events flowing.
   - SP3: apply pgvector migration + run pipeline + check Vertex spend.
   - SP4: apply `run_requests` migration + browser smoke.
   - SP5: configure Gmail app password + Shopify dev store + live send/upload.

---

## 7. Maintenance contract (for future AI sessions)

This file goes stale fast if not maintained. The rule:

- **Before committing any change** that affects status (an SP merging,
  a task completing, a deferral, a new dependency, a new env var, a new
  top-level path), update this file in the same commit.
- Update the **`Last updated:`** line at the top.
- Update the **status table** in §3 and the **outstanding work** in §6.
- If you add a new top-level directory or a new SP, add a row in §4.
- Keep it terse. This is a map, not a journal — journals live in
  `docs/PORT_LOG.md` and `docs/SP*_LOG.md`.

`CLAUDE.md` in the repo root instructs Claude Code sessions to read
this file at session start and to keep it in sync; that is how
"auto-updated on every push" works in practice.
