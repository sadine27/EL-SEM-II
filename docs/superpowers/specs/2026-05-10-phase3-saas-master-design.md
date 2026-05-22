# Phase 3 SaaS End-to-End — Master Design Spec

**Date:** 2026-05-10
**Author:** Divyesh Sharma (with Claude)
**Status:** Master plan — sub-projects each get their own design docs.
**Predecessors:** Phase 2 paper (calibration / IPS / hierarchical pooling — in progress, due 2026-05-13/15). The Python port of `legacy/EL.json` finished at iter 13 (`f398da3`, 63 nodes, 400 tests, 93% coverage).
**Target SaaS reference:** `docs/legacy/Saas-PNG.png` and `docs/legacy/Saas.pdf`.
**Timeline:** ~30–35 calendar days from 2026-05-16 (post-paper). Phase 3 paper submission window: ≥30 days from start.

---

## 1. What this spec is and is not

**Is:** the architectural decomposition, sub-project list with order/effort/dependencies, tech-stack decisions, credential & cost plan, data-flow contract between sub-projects, and Docker/deploy plan. The spec that everything else references.

**Is not:** the implementation plan for any single sub-project. Each sub-project (SP1 … SP8) gets its own detailed design spec + implementation plan in subsequent sessions, drilled in via the same brainstorming → spec → writing-plans → executing-plans pipeline.

---

## 2. Problem statement

Two simultaneous goals:

1. **SaaS product:** complete the end-to-end automated dropshipping pipeline shown in `Saas-PNG.png`. User specifies a niche/genre/dislikes → system trends-discovers, scrapes ad-spy + competitor stores, generates candidates via CJ Dropshipping + BCC ranking, enriches with vision + embeddings, produces curated picks for HIL approval, and on approval auto-builds a Shopify store with theme + products + business notification + CRM update. Containerized, deployed to a server.

2. **Phase 3 paper:** *"Off-Policy Evaluation of Human Overrides in HIL Product Curation"*. Use the existing IPS calibration toolkit (`scripts/ips_calibration.py`) to estimate counterfactual reward — *would the model's BCC-ranked top pick have outperformed the human's HIL choice?* — using a stochastic logging policy (ε-greedy on BCC top-K) so propensities are known and unbiased IPS / doubly-robust estimation is possible.

The two goals share infrastructure: the SaaS pipeline generates the HIL events the paper analyzes, and the paper's stochastic-logging requirement constrains how the SaaS pipeline must rank.

---

## 3. Target architecture

```
                        ┌───────────────────────────────┐
                        │   USER INPUT LAYER  (SP4)     │
                        │  • Web form (FastAPI + HTMX)  │
                        │  • Telegram chat trigger      │
                        │  → niche, dislikes, budget    │
                        └───────────────┬───────────────┘
                                        │
                                        ▼
        ┌─────────── TRENDING DISCOVERY (SP2) ───────────┐
        │  YouTube ✓ │ Google Trends ✗ │ Ad-Spy ✗        │
        │  Shopify-store-link competitor scraper ✗       │
        │  Unified `el/sources/` interface ✗             │
        └───────────────────────┬────────────────────────┘
                                │
                                ▼
        ┌─── CANDIDATE GENERATION (existing) ───────────┐
        │  score_rank → filter_top_30                   │
        │  curate_picks (Vertex Gemini agent)           │
        │  CJ Dropshipping product list → top 3         │
        └───────────────────────┬────────────────────────┘
                                │
                                ▼
        ┌─── ENRICHMENT (SP3 + existing) ───────────────┐
        │  Browserbase reviews ✓  │ Tavily search ✓     │
        │  Vertex multimodal img embedding ✗            │
        │  pgvector similarity index ✗                  │
        │  "Find similar in catalog" service ✗          │
        └───────────────────────┬────────────────────────┘
                                │
                                ▼
        ┌─── RANKING + STOCHASTIC POLICY (SP1) ★ ───────┐
        │  BCC posteriors ✓  │ phase4 candidate sel. ✓  │
        │  ε-greedy sampler over top-K ✗                │
        │  Propensity recorder ✗                        │
        │  HIL event logger (Supabase `hil_events`) ✗   │
        └───────────────────────┬────────────────────────┘
                                │
                                ▼
        ┌─── HIL DECISION ───────────────────────────────┐
        │  Telegram bot ✓                                │
        │  Web HIL UI (SP4 nice-to-have)                 │
        │  Captures (action, propensity, position)       │
        └───────────────────────┬────────────────────────┘
                                │  (on approve)
                                ▼
        ┌─── OUTBOUND (SP5) ────────────────────────────┐
        │  Email-to-self ×2 ✗                            │
        │  Shopify Admin API: theme JSON + products ✗    │
        │  Business notify (Telegram) ✗                  │
        │  CRM update (SP6) ✗                            │
        └────────────────────────────────────────────────┘

  SIDECARS:
   ★ AI Research Chat Bot (SP4) — RAG over pgvector
   ★ IPS Research Pipeline (SP7) — clipped IPS + DR + paper figs

  HOSTING:
   ★ Docker (SP8) — multi-stage image, Hetzner CX22, GitHub Actions CI/CD
```

Legend: ✓ = already built (Python port), ✗ = to build, ★ = paper-critical.

---

## 4. Sub-projects

Each sub-project is a separately-spec'd, separately-planned, separately-implemented unit. All write to and read from a shared `ctx` dict passed through `el/pipeline.py`, plus a Supabase database that all components share. Boundaries below are firm — touching another sub-project's internals during implementation triggers re-spec.

### SP1 — Telemetry Foundation [paper-critical, hard blocker]

**Purpose:** make every HIL decision a labeled, propensity-tagged data point so the Phase 3 paper can run IPS without bias.

**Deliverables:**
- New module `el/policy.py` — wraps the BCC-ranked top-K with an ε-greedy sampler. ε is configurable (start 0.1). Records the chosen item, its rank, the BCC score, and the propensity p(chosen | ranking, ε).
- Supabase table `private.hil_events` — schema: `event_id`, `run_id`, `category`, `topk_payload (jsonb)`, `bcc_scores (jsonb)`, `chosen_index`, `chosen_propensity`, `human_action (approve/reject/null)`, `human_decided_at`, `created_at`. Migration file.
- Logging hooks in `phase4_candidate_selection.py`, `prepare_telegram_card.py`, `apply_hil_callback.py`. No business-logic changes.
- `scripts/backfill_hil_events.py` — one-shot tool to backfill existing approved/rejected reviews from `private.hil_reviews` into the new table where possible (best-effort, missing propensities flagged).
- Tests: ε-greedy distribution check, propensity arithmetic, schema migration round-trip, hook fail-soft.

**Effort:** 3–5 days.
**Blocks:** SP7 (paper). Without SP1, every HIL event collected during the build is unusable for IPS.
**Blocked by:** none.

### SP2 — Source Expansion

**Purpose:** broaden trending discovery beyond YouTube; honor `Saas-PNG.png`'s "Google Trends → INPUT DB", "Ghost Browsing → ad-spy sites", and "Shopify Store Link → JSON" arrows.

**Deliverables:**
- `el/sources/__init__.py` defining `Source` protocol with `fetch_trends() -> list[TrendCandidate]`.
- `el/sources/google_trends.py` — pytrends-modern wrapper, IN region, realtime + daily, related-queries expansion. Routes through Browserbase if rate-limited (no proxy provider needed).
- `el/sources/meta_ad_library.py` — scrape Meta Ad Library public web for ads tagged commerce/shopping; Browserbase-backed.
- `el/sources/tiktok_creative_center.py` — public TikTok Creative Center trends; Browserbase-backed.
- `el/sources/aliexpress_trending.py` — AliExpress hot-products list.
- `el/sources/shopify_competitor.py` — given a `*.myshopify.com` URL, scrape `/products.json` (Shopify exposes this publicly for any store) → product list as `TrendCandidate`s.
- Adapter in `el/pipeline.py` to merge all sources into the existing `score_rank` input shape. Existing YouTube remains as `el/sources/youtube.py`.
- Tests for each source with fixture HTML/JSON and one live-network smoke test (skipped without env).

**Effort:** 5–7 days.
**Blocks:** indirectly increases HIL volume → faster paper data accrual.
**Blocked by:** none.

### SP3 — Vision + Vector

**Purpose:** the `Saas-PNG.png` "Google Vision API + reverse image search + Vertex Embedding System + Google PostgreSQL pgvector" loop, simplified to in-corpus similarity (cheaper, more relevant).

**Deliverables:**
- Enable `pgvector` extension on Supabase (`create extension if not exists vector;`) — migration file.
- New table `private.product_embeddings` — `product_id`, `text_embedding vector(768)`, `image_embedding vector(1408)`, `combined_embedding vector(2176)`, `created_at`. HNSW index on each embedding column.
- `el/embeddings.py` — wraps Vertex multimodal embedding model (`multimodalembedding@001`) — produces text + image embeddings with retry / rate-limit handling.
- `el/nodes/embed_candidate_products.py` — runs after `pick_top_3.py`, embeds each candidate.
- `el/nodes/find_similar_products.py` — given a candidate, returns top-N from `private.product_embeddings` by cosine similarity.
- Optional: `el/sources/reverse_image.py` — Bing Visual Search free-tier wrapper, used only if explicitly enabled.
- Tests: embedding shape, HNSW index recall on synthetic data, similarity ordering.

**Effort:** 5–7 days.
**Blocks:** SP4 chat bot (RAG over embeddings).
**Blocked by:** none for the embedding work; SP1 is independent.

### SP4 — User Input + AI Research Chat Bot

**Purpose:** the `Saas-PNG.png` "INPUT chat trigger" + "AI CHAT BOT" loop. Lets non-Divyesh users specify a niche and converse with the catalog.

**Deliverables:**
- FastAPI app at `el/web/` — routes:
  - `POST /api/runs` — submit niche/dislikes/budget; enqueues a pipeline run.
  - `GET /api/runs/{id}` — run status.
  - `POST /api/chat` — chat-bot endpoint; SSE streaming response from Vertex Gemini grounded by pgvector RAG.
  - `GET /healthz` — for the load balancer.
- HTMX + Tailwind frontend (`el/web/templates/`). No build step. One page each: input form, run status, chat.
- Telegram chat trigger handler (`el/nodes/telegram_chat_trigger.py`) — listens for `/start_run` + structured form via Telegram WebApp.
- Auth: Telegram WebApp auth (signed init data); for the web side, simple email-magic-link via Supabase Auth.
- Rate limiting (per-user 10 runs/day initially).
- Tests: route handlers with TestClient, chat-bot grounding correctness (mocked LLM), Telegram auth signature verification.

**Effort:** 5–7 days.
**Blocks:** nothing in the paper path.
**Blocked by:** SP3 (chat bot needs pgvector).

### SP5 — Outbound Actions

**Purpose:** the `Saas-PNG.png` `E-MAIL TO SELF` ×2, `Shopify Dev API`, "feed JSON to store", "ADD ITEMS TO SHOPIFY", "NOTIFY THE BUSINESS" arrows.

**Deliverables:**
- `el/email.py` — Gmail SMTP client (app password). Two send modes: digest (Sheet attachment + Gemini-summarized body + N8N chat link) and per-product (full seller details + product page link).
- `el/nodes/email_digest.py` and `el/nodes/email_product_detail.py` — wired into pipeline post-HIL-approve.
- `el/shopify.py` — Shopify Admin API client (REST 2024-10) with retry + idempotency-key.
- `el/nodes/generate_shopify_theme.py` — Vertex Gemini structured-output: theme name, color palette, font stack, hero copy, CTA copy. Output: a `theme_template.json` checked into the run's Drive folder.
- `el/nodes/upload_shopify_theme.py` — applies the theme JSON to a target dev store via Admin API (uses `themes` REST resource + asset uploads for derived Liquid).
- `el/nodes/upload_shopify_products.py` — pushes each approved product (image + title + description + price + SKU + tags + inventory) via `products` REST resource.
- `el/nodes/notify_business.py` — Telegram message to business chat with run summary + Shopify store URL.
- Tests: SMTP fail-soft, Shopify Admin API mocking, theme JSON schema validation, idempotency on product re-push.

**Effort:** 5–7 days.
**Blocks:** SP6.
**Blocked by:** none structurally; needs an approved HIL event in the test fixtures, which SP1 produces.

### SP6 — CRM Module (minimal)

**Purpose:** the `LEFT TO MAP — CRM` sticky on `Saas-PNG.png`. Currently undefined. This sub-project's first task is to define it.

**Deliverables (tentative; refined in its own brainstorming session):**
- Decision spec: pick between (a) Supabase tables + Postgres views + a Grafana/Metabase dashboard; (b) external integration (Notion, Airtable, HubSpot free); (c) hybrid.
- Tables: `private.suppliers` (supplier_id, name, cj_ref, reliability_score, last_dispute_at), `private.disputes` (dispute_id, product_id, opened_at, status, resolution), `private.niche_performance` (niche, run_count, approval_rate, avg_bcc_score, avg_human_position).
- Pipeline hook to record per-run, per-niche metrics post-approval/rejection.
- Read-only dashboard at `/crm` (extend SP4's FastAPI).
- Tests: aggregate query correctness on synthetic event data.

**Effort:** 1–2 days for spec, 3–5 days for build.
**Blocks:** nothing in the paper.
**Blocked by:** SP1 (needs HIL events), SP5 (needs supplier interactions), SP4 (needs the FastAPI app).

### SP7 — Research Paper Pipeline [paper-critical]

**Purpose:** convert SP1's `hil_events` table into a publishable paper: "Off-Policy Evaluation of Human Overrides in HIL Product Curation".

**Deliverables:**
- `scripts/research/ips_overrides.py` — given the `hil_events` table dump, computes:
  - **Vanilla IPS** of human-policy reward and model-policy reward.
  - **Clipped IPS** with weight cap M (M ∈ {10, 50, 100} sweep).
  - **Doubly-robust** estimator using a fitted reward model (BCC posterior expected reward serves as the direct method baseline; we have this).
  - Bootstrap 95% CIs.
  - Per-category and per-niche breakdowns.
- `scripts/research/override_descriptive.py` — frequency of overrides, position distribution of human picks vs. model top-K, mutual information between product features and override decision, SHAP attribution of override drivers.
- `scripts/research/paper_figures.py` — generates the LaTeX-ready figures (PGF/TikZ where possible, matplotlib otherwise) and tables (`paper/figures/overrides_*.tex`).
- `paper/phase3_overrides.tex` — the Phase 3 paper draft, hard-capped at venue page limit, ≤15 references, separated from Phase 2 paper.
- `tests/research/` — unit tests for IPS estimators (analytic check on synthetic policies), DR estimator (variance reduction check), bootstrap reproducibility (seeded).

**Effort:** 10–14 days, parallel with data accrual. First analyses run at ~50 events; final paper requires ≥100 events (target 200 if pace allows).

**Blocks:** Phase 3 paper submission.
**Blocked by:** SP1, plus ≥100 logged HIL events.

### SP8 — Docker + Production Deploy

**Purpose:** package the pipeline + FastAPI + chat bot + research scripts into containers and run them on a server.

**Deliverables:**
- Repo-root `Dockerfile` (multi-stage):
  - Stage 1 (builder): python:3.12-slim, installs `requirements.txt` + `requirements-paper.txt` + `requirements-web.txt` (new) into a venv.
  - Stage 2 (runtime): `gcr.io/distroless/python3-debian12` or python:3.12-slim with non-root user. Copies the venv + `el/` + `scripts/` + `paper/` (excluded via .dockerignore for the runtime image actually — only `el/`, `scripts/`, and runtime assets).
- Repo-root `docker-compose.yml` — three services for local dev: `api` (FastAPI), `worker` (pipeline runs via APScheduler), `redis` (Celery broker, only if SP4 needs it).
- `.dockerignore` — excludes `.venv/`, `tests/`, `data/*.json`, `paper/`, `legacy/`, `*.aux`, `*.log`, `*.out`, `.env`, `node_modules/`.
- `el/web/asgi.py` — uvicorn entrypoint.
- `el/web/scheduler.py` — APScheduler config: daily pipeline run at 03:00 IST, hourly health-check, etc.
- Hetzner CX22 setup script (`scripts/deploy/hetzner_bootstrap.sh`) — apt installs Docker, adds non-root user, opens UFW for 22/443, installs Caddy as TLS terminator, pulls image from GHCR, runs compose.
- GitHub Actions workflow `.github/workflows/deploy.yml` — on push to `main`: build + push image to GHCR, SSH to Hetzner, `docker compose pull && up -d`, run smoke test.
- Secrets management: `.env` on the server, owned root, mode 600; never in image; loaded by Docker at runtime via `--env-file`.
- Observability: Sentry SDK with free-tier DSN; `/healthz` exposed; Caddy access logs.
- Documentation in `docs/DEPLOY.md`.

**What goes IN the runtime image:**
- `el/` (entire package, all 63 nodes + new SP modules)
- `scripts/` (only the runtime-needed scripts: `verify_env.py`, `backfill_hil_events.py`, `research/*` if we want them on-server; otherwise excluded)
- `requirements.txt`, `requirements-web.txt`
- entrypoint scripts

**What stays OUT of the runtime image:**
- `paper/`, `legacy/`, `tests/`, `docs/`
- `data/*.json` (mounted as volume from host if persistence needed)
- `.git/`, `.venv/`, `.pytest_cache/`, `.vscode/`
- `.env`, `.env.example`
- `requirements-paper.txt` (only for paper builds, separate dev image if needed)

**Effort:** 4–6 days.
**Blocks:** nothing — it's the final packaging step.
**Blocked by:** at least SP1 for a meaningful "first deploy"; ideally SP1 + SP2 + SP4 to have something user-facing to expose.

---

## 5. Critical path & timeline

```
 Day  1 ── 7  : SP1 (telemetry, BLOCKING)        ║ SP2a (G-Trends) parallel
 Day  8 ── 14 : SP2b (ad-spy + Shopify-link)     ║ SP3 (vision + pgvector)        ║ events accrue
 Day 15 ── 21 : SP4 (user input + chat bot)      ║ SP5a (email)                   ║ ~50 events
 Day 22 ── 28 : SP5b (Shopify auto-store)        ║ SP6 (CRM minimal)              ║ ~100 events
 Day 29 ── 35 : SP7 (paper write-up + analyses)  ║ SP8 (Docker + Hetzner deploy)
```

Solo-Divyesh assumption. With teammate parallelism (G-Trends + email + CRM are good handoffs), compresses by ~5 days.

Decision points:
- **Day 7:** SP1 must be merged and emitting events. If not, slip everything 1 week.
- **Day 21:** if event count <40 by Day 21, increase pipeline run frequency or seed via teammate-driven HIL volume.
- **Day 28:** if event count <100, decide whether to extend timeline or fall back to "preliminary study" framing for the paper.

---

## 6. Tech stack (locked)

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | existing port; one language reduces context-switching |
| Pipeline core | `el/` package, existing `pipeline.py` | already 63 nodes, 400 tests |
| Web framework | FastAPI | async, fits Python pipeline, OpenAPI for free |
| Frontend | HTMX + Tailwind, server-rendered Jinja | no build step; tiny image; zero JS-toolchain hell |
| Telegram WebApp | existing pattern | already wired |
| Vector DB | Supabase pgvector | one DB, free tier covers our scale |
| LLM | Vertex Gemini (existing SA) | already authenticated, no new key |
| Embeddings | Vertex `multimodalembedding@001` | text + image in one call |
| Headless browsing | Browserbase (existing) | one vendor for trends, ad-spy, Shopify scrape |
| Job scheduling | APScheduler in-process initially | upgrade to Celery + Redis only if scrape parallelism demands |
| Database | Supabase Postgres | already there |
| Container | Docker, multi-stage, distroless or slim | small + secure |
| Host | Hetzner CX22 (€3.79/mo) | full root, 4GB RAM enough for our load |
| TLS | Caddy automatic Let's Encrypt | zero-config |
| CI/CD | GitHub Actions → GHCR → SSH deploy | free tier |
| Secrets | `.env` on server, mode 600 | matches existing pattern |
| Observability | Sentry free + Caddy logs + `/healthz` | sufficient |
| Tests | pytest + pytest-cov (existing) | ≥90% target maintained |

**Explicitly NOT used:** Next.js, React build pipelines, Vercel/Netlify, Pinecone, Weaviate, paid SerpAPI/AdSpy/scrapfly, Kubernetes, Terraform.

---

## 7. Credentials & dependencies

### Already present (`.env` and `.env.example`)
- `YOUTUBE_API_KEY`, `TAVILY_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `VERTEX_LOCATION`
- `CJ_EMAIL`, `CJ_API_KEY`
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`
- `BROWSERBASE_API_KEY`
- `TELEGRAM_HIL_BOT_TOKEN`, `TELEGRAM_HIL_CHAT_ID`, `TELEGRAM_ALERT_CHAT_ID`
- `EL_DEVELOPER_ALERT_TOKEN_KEY`, `EL_DEVELOPER_ALERT_CHAT_ID`

### To add (per sub-project, requested at SP-start time)

| Var | Sub-project | Source | Cost |
|---|---|---|---|
| `PYTRENDS_PROXY_VIA_BROWSERBASE` (bool) | SP2 | flag, no creds | free |
| `META_AD_LIBRARY_BROWSERBASE_PROJECT` | SP2 | Browserbase (existing) | free |
| `SHOPIFY_COMPETITOR_USER_AGENT` | SP2 | string, no creds | free |
| (none — Vertex SA already authenticated) | SP3 | existing | Vertex pay-per-use |
| `SUPABASE_PGVECTOR_ENABLED=true` | SP3 | one SQL migration | free |
| `BING_VISUAL_SEARCH_KEY` (optional) | SP3 | Azure portal → Cognitive Services free tier | free 1k/mo |
| `WEB_BASE_URL` | SP4 | string | free |
| `WEB_SECRET_KEY` | SP4 | random 32 bytes | free |
| `SUPABASE_AUTH_JWT_SECRET` | SP4 | Supabase dashboard | free |
| `GMAIL_SMTP_USER` | SP5 | Gmail account | free |
| `GMAIL_SMTP_APP_PASSWORD` | SP5 | Google account → app passwords | free |
| `SHOPIFY_STORE_DOMAIN` | SP5 | Shopify Partners → dev store | free |
| `SHOPIFY_ADMIN_API_TOKEN` | SP5 | Shopify Partners → custom app → install | free |
| `SHOPIFY_API_VERSION=2024-10` | SP5 | string | free |
| `BUSINESS_NOTIFY_TELEGRAM_CHAT_ID` | SP5 | Telegram | free |
| (CRM choice TBD) | SP6 | TBD | TBD |
| `SENTRY_DSN` (optional) | SP8 | Sentry free-tier project | free |
| `HETZNER_SSH_HOST` `HETZNER_SSH_USER` (CI) | SP8 | Hetzner | $4.59/mo |
| `GHCR_TOKEN` | SP8 | GitHub PAT | free |

### Recurring monthly cost (worst case)

| Item | Cost |
|---|---|
| Hetzner CX22 | €3.79 ≈ $4.10 |
| Vertex AI (LLM + embeddings @ moderate use) | $5–15 |
| Browserbase (existing tier — varies) | $0–30 (already paying) |
| Domain (deferred until needed) | $0.75 amortized |
| Sentry free, GitHub Actions free, Supabase free, Telegram, Gmail SMTP | $0 |
| **Total new spend introduced by Phase 3** | **~$10–20/month** |

---

## 8. Data flow contract

Sub-projects communicate through three shared substrates:

1. **`ctx` dict** (in-process, per-pipeline-run) — keys are namespaced by source: `ctx["youtube_trends"]`, `ctx["gtrends_trends"]`, `ctx["adspy_trends"]`, `ctx["candidates"]`, `ctx["bcc_scores"]`, `ctx["topk_with_propensity"]`, `ctx["hil_decision"]`, `ctx["approved_products"]`, `ctx["shopify_store_url"]`.

2. **Supabase Postgres** — source of truth across runs:
   - existing: `private.hil_reviews`, `public.scraped_products`, etc.
   - new (SP1): `private.hil_events`
   - new (SP3): `private.product_embeddings`
   - new (SP6): `private.suppliers`, `private.disputes`, `private.niche_performance`

3. **Google Drive folder + Sheets** — existing, unchanged. Daily tab + curated picks tab + scraped tab + Drive-archived JSON file per run.

Sub-projects do NOT call each other's Python code directly except through:
- `el/sources/*` (SP2 produces `TrendCandidate` objects consumed by `score_rank.py`)
- `el/embeddings.py` (SP3 produces vectors consumed by SP4 chat-bot RAG and SP6 CRM similarity dashboards)
- `el/policy.py` (SP1 wraps the existing top-K selection; consumed everywhere downstream)

---

## 9. Error handling & boundaries

Inherits the existing port's fail-soft contract: every external IO node returns `ok: False` rather than raising, and downstream nodes guard against missing context keys. New rules for Phase 3:

- **SP1 `el/policy.py`** — never silent-fall-back to deterministic top-1 if propensity logging fails. If we can't write the propensity, we log an error and still serve the top-1, but mark the event with `propensity_logged=false`. The IPS estimator filters those out — biased data is worse than missing data.
- **SP4 web layer** — every endpoint returns `application/json` errors with stable error codes (`ERR_RATE_LIMIT`, `ERR_AUTH`, `ERR_RUN_NOT_FOUND`, …), never HTML stack traces. Sentry captures unhandled.
- **SP5 Shopify** — every Admin API call uses an idempotency key derived from `(run_id, product_id, action)`. Re-runs of the same approved product never duplicate.
- **SP7 research scripts** — never read from `private.hil_events` rows where `propensity_logged=false`. Refuse to produce paper figures if N<50 with a clear error message.
- **SP8 deploy** — every deploy runs a smoke test (`/healthz` + `python -m el run --dry-run`) before traffic switch.

Existing `el/error_handler.py` + `EL_DEVELOPER_ALERT_*` Telegram channel remains the master alarm sink. Sentry is additive, not replacement.

---

## 10. Testing approach

- **Maintain the 90%+ line-coverage floor** set by iter 13. Each sub-project's spec includes a tests-added section.
- **Every new node fail-soft tested** at every IO boundary, mirroring `tests/test_hardening_edges.py`.
- **Integration test per sub-project**: `tests/integration/test_sp{N}_pipeline.py` runs the relevant pipeline subset against fakes.
- **End-to-end test** added once SP4 is up: `tests/e2e/test_user_run.py` — submit a niche via the FastAPI route, mock all external services, assert the Supabase events + Drive uploads + (mocked) Shopify calls all happened.
- **Research paper analyses are unit-tested** on synthetic policies where the IPS / DR estimators have closed-form ground truth.
- **Smoke test** in CI: `python -m el run --dry-run` against fakes.

---

## 11. Docker & deployment plan (referenced by SP8 in detail)

### Files included in the runtime image

```
/app/
├── el/                          # entire package
├── scripts/
│   ├── verify_env.py
│   ├── backfill_hil_events.py
│   └── research/                # optional: only if we run analyses on the server
├── requirements.txt
├── requirements-web.txt
├── docker-entrypoint.sh
└── pyproject.toml (if we add one)
```

### Files excluded via `.dockerignore`

```
.git/
.venv/
.pytest_cache/
.vscode/
.claude/
.env
.env.example
tests/
paper/
docs/
legacy/
data/*.json
*.aux *.log *.out
main.* (LaTeX intermediates at repo root)
node_modules/
requirements-paper.txt   # paper-only deps stay out of the runtime image
```

### docker-compose for local dev

```
services:
  api:      # FastAPI on :8000, mounts ./el for hot reload
  worker:   # APScheduler container
  redis:    # only if Celery is enabled (deferred)
```

### Production (Hetzner CX22)

- Caddy reverse-proxy with auto Let's Encrypt → `:443` → `api:8000`.
- `worker` runs alongside, no public port.
- Logs: Caddy → `journalctl`; app → stdout → `docker logs`; errors → Sentry.
- Secrets: `/etc/el/.env`, mode 600, owned by deploy user, mounted via `env_file`.
- Backups: Supabase native daily backups (free tier) cover the DB. No app-state on the host worth backing up.

### CI/CD

`main` push:
1. lint + test (pytest -q)
2. build `el-api:sha-XXXX` and `el-worker:sha-XXXX` images
3. push to GHCR
4. SSH to Hetzner, `docker compose pull && docker compose up -d`
5. wait 30s, hit `/healthz`, fail the deploy if non-200

---

## 12. Open questions (to resolve before or during sub-project specs)

| # | Question | Resolution path |
|---|---|---|
| Q1 | What ε does the ε-greedy policy use? Constant 0.1, or scheduled / per-category? | Resolved in SP1 spec; default 0.1 with planned sensitivity sweep in paper. |
| Q2 | Is the chat-bot RAG corpus all candidates ever, or only approved? | Resolved in SP3/SP4 specs. Likely "all embedded candidates with `is_approved` filter" — both views useful. |
| Q3 | Does the user-facing web UI need a marketing landing page, or is it private? | Resolved in SP4 spec. Default: behind email magic-link, no public marketing. |
| Q4 | What's the actual definition of CRM here? | Resolved in SP6 spec — first deliverable of that sub-project is its own definition. |
| Q5 | Reverse-image-search externally (Bing free tier) or only in-corpus pgvector similarity? | Default: in-corpus only. External enabled by env flag if SP3 finds we need it. |
| Q6 | Does SP4 need Celery+Redis or is APScheduler enough? | Default: APScheduler. Upgrade only if a single pipeline run takes >5 min and we need parallelism. |
| Q7 | Where does ad-spy data feed into the existing `score_rank` ranking — as a separate signal or as another "trend source"? | Resolved in SP2 spec — likely a separate signal column with its own weight in `score_rank`. |
| Q8 | Phase 3 paper venue? | Outside this spec's scope; identified during SP7. Likely an HCI-recsys workshop or applied-ML conference based on n=100–200 events. |

---

## 13. Out of scope (explicitly)

- Mobile app (web-only, Telegram-secondary).
- Multi-tenant / multi-business support — single-tenant by design.
- Payment / billing — this is a research SaaS, not a commercial product.
- Real-time streaming pipelines — daily batch is sufficient.
- Kubernetes / horizontal scaling — Hetzner CX22 vertical scale only.
- Replacing existing 63 ported nodes — they're the source of truth, additive only.
- Phase 2 paper (calibration paper) modifications — separate concern.
- Localization beyond IN — same as the existing pipeline.
- A/B testing of UI variants — out of scope; the only A/B is the ε-greedy in SP1.

---

## 14. Success criteria

**Product (SaaS):**
- A non-Divyesh user can submit a niche via the web UI, receive HIL cards on Telegram, approve one, and watch a Shopify dev store auto-populate with the approved product within 30 minutes — end-to-end, no manual intervention.
- 99% of pipeline runs over a 7-day window complete without unhandled exceptions (existing fail-soft + Sentry confirms).
- Caddy serves the FastAPI app over HTTPS on a Hetzner CX22 with `/healthz` returning 200.

**Research (Paper):**
- ≥100 logged HIL events with valid propensities by Day 28.
- Phase 3 paper draft (`paper/phase3_overrides.tex`) has all sections populated, all figures generated programmatically from the events table, all references ≤15.
- IPS / DR estimators reproduce known-truth values within 95% CI on synthetic data.
- Paper passes one round of internal review (mentor + teammates) by Day 35.

**Engineering:**
- Test suite stays at ≥93% line coverage; suite size ≥500 tests.
- Total recurring infrastructure cost stays ≤$25/month.
- Image size <500MB.
- Cold-start container boot <10s.

---

## 15. Next step

Drill into **SP1 — Telemetry Foundation** as the first detailed sub-project spec. It is:
- the hard blocker for the paper,
- the smallest of the eight (3–5 days),
- a non-breaking additive change to the existing pipeline (zero risk to the merged port),
- and the right warm-up to validate this master-spec / sub-spec / plan / implement workflow before the larger sub-projects.

After this master spec is approved, the next session brainstorms SP1 in detail, writes its own design doc, then writing-plans creates its implementation plan, then we execute.
