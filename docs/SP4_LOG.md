# SP4 — FastAPI Web App + RAG Chat Bot Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-21-sp4-web-and-chat-design.md`
**Plan:** `docs/superpowers/plans/2026-05-21-sp4-web-and-chat.md`
**Started:** 2026-05-21
**Completed:** 2026-05-22

## Summary

SP4 ships the MVP web layer: a FastAPI app at `el/web/` that lets the
operator submit a niche run via `POST /api/runs`, poll status via
`GET /api/runs/{id}`, and chat with the SP3-grounded RAG bot over SSE at
`POST /api/chat`. Three HTMX shell pages (`/`, `/run/{id}`, `/chat`)
render the UI using Tailwind + HTMX via CDN — no build step.

Auth is a single bearer token verified with `hmac.compare_digest`
(single-operator MVP). Rate limiting is an in-memory per-IP token bucket
(30/min default). Runs execute synchronously via FastAPI `BackgroundTasks`
— no Celery, no Redis.

Per the SP4 spec §1, **Supabase Auth magic-link**, **Telegram WebApp
trigger**, **Redis/Celery**, and **APScheduler** are deferred to SP6/SP8.
The bearer-token endpoint at `/api/runs` becomes the target of the
existing Telegram listener once SP8 supplies the public HTTPS URL.

## What changed

| Area | Change |
|------|--------|
| Schema | New table `private.run_requests` (id, submitted_at, submitted_by, niche, dislikes, budget_usd, status, pipeline_run_id, error_message, started_at, finished_at). HNSW-style btree index on `(status, submitted_at DESC)`. Migration in `migrations/sp4/001_run_requests.sql`. Idempotent. |
| Supabase client | Constants `RUN_REQUESTS_SCHEMA`/`RUN_REQUESTS_TABLE` added to `el/supabase.py`; existing `insert_rows`/`select_rows`/`update_rows` used. |
| Config | `Settings` dataclass at `el/web/settings.py` with env-loader (`from_env()`); refuses to start if `WEB_SECRET_KEY` missing. |
| Auth | `el/web/auth.py` — `verify_bearer(header, *, expected_secret)` using `hmac.compare_digest`. |
| Rate limit | `el/web/rate_limit.py` — `TokenBucket(capacity, refill_per_sec, clock)` with `per_minute(N)` factory. Lazy refill, monotonic clock, in-memory dict keyed by IP. |
| Run service | `el/web/run_service.py` — `submit_run`, `get_run`, `mark_running`, `mark_done`, `mark_error`. Pure helpers, no FastAPI imports. |
| Pipeline | `el/pipeline.py` — `run()` accepts optional `initial_ctx`; new `run_for_request(request_id, *, db_provider=None)` reads the row, seeds ctx with niche/dislikes/budget_usd, runs, marks done/error. |
| RAG generator | `el/web/chat_rag.py` — `stream_answer(question, top_k, embedding_provider, db_provider, llm_stream)` yields `{event: 'context'\|'chunk'\|'done'\|'error', ...}` dicts. Embeds question → calls SP3 `find_similar_products` → emits context event → streams LLM chunks → done. |
| FastAPI app | `el/web/app.py` — `create_app(settings=None)` factory: rate-limit middleware (exempts `/healthz`, `/static`), JSON error envelope handlers (ERR_AUTH/ERR_VALIDATION/ERR_INTERNAL/ERR_RATE_LIMIT/ERR_RUN_NOT_FOUND), Jinja2 templates, static mount. |
| Routes | `el/web/routes/health.py` (`/healthz`), `runs.py` (`POST` 202, `GET` 200/404), `chat.py` (`POST` SSE), `pages.py` (`GET /`, `/run/{id}`, `/chat`). |
| Templates | `el/web/templates/{base,index,run,chat}.html` — HTMX + Tailwind via CDN. Bearer cached in `sessionStorage`, prompted once per session. Index POSTs to `/api/runs` and redirects to `/run/{id}`; run page polls `/api/runs/{id}` every 3s; chat uses `fetch` + manual SSE parsing. |
| Tests | 53 new tests across auth (7), rate-limit (6), run service (10), chat_rag (6), routes (4 modules: health 1, runs 7, chat 4, middleware 3), templates (5). All providers faked; no live FastAPI server. |
| Config | `.env.example` §13 — `EL_WEB_ENABLED`, `WEB_SECRET_KEY`, `WEB_RATE_LIMIT_PER_MINUTE`, `WEB_CHAT_TOP_K`, `WEB_LLM_MODEL`. |

## Commits (in order)

| Commit | Task | What |
|---|---|---|
| `5fded46` | spec | Design spec |
| `ff96f60` | plan | Implementation plan |
| `38d31b7` | T1 | Migration + Settings scaffolding + `.env.example` §13 |
| `380759d` | T2 | Bearer-token auth helper |
| `ae0edc7` | T3 | In-memory token-bucket rate limiter |
| `c5f4bb0` | T4 | `run_service` helpers + `pipeline.run_for_request` |
| `a81a449` | T5 | `chat_rag.stream_answer` RAG generator |
| `87d2366` | T6 | FastAPI app factory + routes (health, runs, chat) |
| `782ae54` | T7 | HTMX templates + pages route + static |

## Deploy runbook

1. **Apply the migration** in Supabase: SQL Editor or
   `psql $DATABASE_URL -f migrations/sp4/001_run_requests.sql`.
   Confirm `private.run_requests` exists and the
   `run_requests_status_idx` index is present.
2. **Generate a bearer token:** `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Store as `WEB_SECRET_KEY` in `.env`. Set `EL_WEB_ENABLED=true`.
3. **Install runtime deps:** `pip install fastapi uvicorn jinja2`.
   No other new dependencies — Tailwind + HTMX served via CDN.
4. **Boot:** `uvicorn el.web:create_app --factory --host 0.0.0.0 --port 8000`.
5. **Smoke test:**
   - `curl http://localhost:8000/healthz` → `{"ok": true, "version": "<sha>"}`.
   - `curl -H "Authorization: Bearer $WEB_SECRET_KEY" -X POST http://localhost:8000/api/runs -d '{"niche":"x"}'` → 202 with `request_id`.
   - Open `http://localhost:8000/` in a browser, enter the bearer when
     prompted, submit a form, watch `/run/{id}` poll. Open `/chat`,
     ask a question, watch SSE chunks arrive.
6. **Cost monitor:** chat hits Vertex Gemini once per question, plus one
   Vertex embedding call. Per-question cost ≤ $0.002 at typical lengths.
   Pipeline runs scheduled via `/api/runs` reuse the existing Vertex
   spend profile — no incremental cost.

## Rollback

Set `EL_WEB_ENABLED=false` in `.env` and stop the uvicorn process. The
existing pipeline-only flow (`python -m el run`) is untouched and uses
none of the new code. Table and index remain (idempotent migration); no
schema rollback needed.

## Acceptance verification

- [x] Migration is idempotent (every DDL has `if not exists`).
- [x] Bearer auth uses `hmac.compare_digest` — no timing leak.
- [x] Rate limiter is in-memory + monotonic-clock + lazy-refill; exempts `/healthz` and `/static`.
- [x] All API endpoints return JSON error envelope `{error: {code: "ERR_*", message: ...}}` — never HTML stack traces.
- [x] `chat_rag.stream_answer` degrades gracefully on each fail point (embedding failure, search failure, LLM failure) — yields `{event: "error", ...}` and stops.
- [x] `run_service` + `run_for_request` keep the BackgroundTask path uncoupled from FastAPI — both helpers and the pipeline node are testable without an HTTP layer.
- [x] HTMX pages render without a build step (Tailwind + HTMX CDN only).
- [x] 555/555 suite green, 5 subtests passed. No live Vertex / Gemini / Supabase calls in tests.
- [ ] Human smoke after deploy: apply migration, boot uvicorn, submit one run end-to-end through the browser, observe pipeline reaches `done` status. *(post-merge.)*

## Surprises / decisions deferred

- **`raise_server_exceptions=False` needed in the internal-error test.**
  Starlette's `TestClient` re-raises 500s into pytest by default; the
  ERR_INTERNAL envelope handler still runs but the response is never
  returned to the test client. Setting the flag to false on that one
  test fixture restores the production response behavior.
- **Templates use sessionStorage bearer + prompt() once per session.**
  This is a deliberate MVP choice. Once SP8 ships HTTPS + Supabase Auth
  magic-link is wired in SP6, `el/web/auth.py` will gain a session-cookie
  path and the prompt() call goes away. No template rewrite needed —
  the bearer header injection lives in `base.html`'s
  `htmx:configRequest` listener.
- **Pipeline `run()` now accepts `initial_ctx`** for backward compat.
  Existing call sites (cron + `python -m el run`) pass nothing and get
  the legacy behavior. `run_for_request` is the only caller that seeds
  `ctx["niche"]`/`ctx["dislikes"]`/`ctx["budget_usd"]` today.
- **No `el/web/__init__.py` eager imports.** Lazy re-export of
  `create_app` means importing `el.web` doesn't pull in FastAPI — only
  `el.web.app` does. Lets non-web tests stay FastAPI-free.
- **XSS guard in chat.html.** First draft used `innerHTML` to render
  product citation links from the context event; rewritten to use
  `document.createElement` + `.textContent` since product_name comes
  from the DB and isn't sanitized at the source.
