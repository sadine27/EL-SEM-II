---
title: "SP4 — FastAPI Web App + RAG Chat Bot"
date: 2026-05-21
sub_project: SP4
status: design
depends_on: [SP1, SP3]
estimated_effort: "4–6 days"
---

# SP4 — FastAPI Web App + RAG Chat Bot

## 0. Context

Master spec `docs/superpowers/specs/2026-05-10-phase3-saas-master-design.md` §SP4 calls for a FastAPI app exposing run submission + a Vertex-Gemini chat bot grounded over SP3's pgvector embeddings, plus a Telegram WebApp trigger and Supabase Auth magic-link.

This sub-project ships the **minimum viable web layer** that:
- Lets a user (currently: Divyesh) submit a niche-run request through HTTP.
- Lets the same user poll run status.
- Streams a Gemini-grounded chat response over SSE, retrieving candidate products via SP3's `find_similar_products` helper.
- Provides a `/healthz` endpoint suitable for SP8's reverse proxy + uptime checks.

## 1. Scope — what's IN, what's deferred

**IN this sub-project:**
- FastAPI app at `el/web/` with route modules for runs, chat, health.
- Bearer-token auth (single shared secret, env-injected) — appropriate while the system has a single operator.
- In-memory per-IP token-bucket rate limiter.
- HTMX + Tailwind-via-CDN frontend pages (no build step): form, status, chat.
- SSE chat streaming, grounded by SP3 `find_similar_products` + Vertex Gemini.
- `private.run_requests` table + migration: pipeline writes the request synchronously via FastAPI BackgroundTasks (no broker).
- Tests: `TestClient`, fake providers, deterministic SSE stream assertions.

**DEFERRED (out-of-scope rationale documented for SP6/SP8 picks-up):**
- **Supabase Auth magic-link / multi-user auth.** YAGNI until we onboard non-Divyesh users in SP5/SP6. Bearer token gets us through demo and dogfooding.
- **Telegram WebApp trigger.** Requires public HTTPS, bot setup, and signed `init_data` verification — not buildable until SP8 deploy. Existing `el/telegram.py` listener already handles inbound; the new `/api/runs` endpoint becomes its target after SP8.
- **Redis / Celery.** APScheduler and BackgroundTasks cover MVP; defer to SP8 when we know real throughput.
- **APScheduler daily-run wiring.** Belongs in SP8 (deploy concern).
- **Marketing landing page.** Master spec Q3 default: private app, no public marketing.

## 2. Architecture

```
HTTP request ──► FastAPI app (el/web/app.py)
                   │
                   ├── /healthz                    (el/web/routes/health.py)
                   ├── /api/runs        POST/GET  (el/web/routes/runs.py)
                   │     └── run_service.submit_run(...)  ──► writes private.run_requests
                   │                                     ──► BackgroundTasks: el.pipeline.run_for_request(request_id)
                   ├── /api/chat        POST       (el/web/routes/chat.py)
                   │     └── chat_rag.stream_answer(question, ...)
                   │           ├── embed question (el/embeddings.py)
                   │           ├── find_similar_products (el/nodes/find_similar_products.py)
                   │           └── Vertex Gemini stream (el/llm.py)
                   ├── /            ┐
                   ├── /run/{id}    ├─ HTMX pages  (el/web/templates/)
                   └── /chat        ┘
```

**Middlewares:** `auth.bearer_token_required` (skips `/healthz` + static); `rate_limit.per_ip_token_bucket`.

**No new external dependencies.** FastAPI, uvicorn, Jinja2 (transitive via FastAPI templates) — all pure Python wheels. Tailwind via CDN. HTMX via CDN.

## 3. Data model

New table (migration `migrations/sp4/001_run_requests.sql`):

```sql
CREATE TABLE IF NOT EXISTS private.run_requests (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submitted_at    timestamptz NOT NULL DEFAULT now(),
  submitted_by    text NOT NULL,              -- bearer-token principal (currently "operator")
  niche           text NOT NULL,
  dislikes        text NOT NULL DEFAULT '',
  budget_usd      numeric(10,2),
  status          text NOT NULL DEFAULT 'queued'    -- queued | running | done | error
                  CHECK (status IN ('queued','running','done','error')),
  pipeline_run_id uuid,                       -- set when pipeline starts; FK-shaped, not enforced
  error_message   text,
  started_at      timestamptz,
  finished_at     timestamptz
);

CREATE INDEX IF NOT EXISTS run_requests_status_idx
  ON private.run_requests (status, submitted_at DESC);
```

Idempotent (re-applying = no-op).

## 4. Module-by-module contracts

### 4.1 `el/web/__init__.py`
Re-exports `create_app` from `app.py`.

### 4.2 `el/web/app.py`
```python
def create_app(*, settings: Settings | None = None) -> FastAPI: ...
```
- Wires routes, middlewares, templates, static.
- `settings` is injectable for tests (test passes a `Settings` with fake providers).
- Mounts `/static` from `el/web/static/`.

### 4.3 `el/web/settings.py`
Dataclass holding:
- `web_secret_key: str` (env `WEB_SECRET_KEY`)
- `rate_limit_per_minute: int` (default 30)
- `chat_top_k: int` (default 5)
- `embedding_provider: EmbeddingProvider` (default `VertexEmbeddingProvider()`)
- `db_provider: SupabaseRestProvider` (default real)
- `llm_provider: callable | None` (default real Gemini stream; tests pass a fake)

Fail-soft: missing `WEB_SECRET_KEY` → app refuses to start (security-critical, NOT fail-soft).

### 4.4 `el/web/auth.py`
```python
def bearer_token_required(request: Request, settings: Settings) -> str:
    """Returns principal name. Raises HTTPException 401 on missing/bad token."""
```
- Reads `Authorization: Bearer <token>`; compares to `settings.web_secret_key` with `hmac.compare_digest`.
- Returns `"operator"` on success.
- Skipped for routes registered as `public` (healthz, static, HTMX templates).

### 4.5 `el/web/rate_limit.py`
Pure-Python token bucket keyed by `request.client.host`. Configurable per-minute cap. In-memory dict + monotonic clock; refills lazily on each call. Returns 429 with `Retry-After`.

### 4.6 `el/web/run_service.py`
```python
def submit_run(*, niche: str, dislikes: str, budget_usd: float | None,
               principal: str, db_provider) -> dict
def get_run(*, request_id: str, db_provider) -> dict | None
def mark_running(*, request_id, pipeline_run_id, db_provider) -> None
def mark_done(*, request_id, db_provider) -> None
def mark_error(*, request_id, error_message, db_provider) -> None
```
Pure helpers wrapping `db_provider.insert_row`/`select_rows`/`update_row`. No FastAPI imports.

### 4.7 `el/web/routes/runs.py`
- `POST /api/runs` → validates `niche` non-empty, calls `submit_run`, schedules `BackgroundTasks.add_task(_run_pipeline, request_id)`, returns 202 with `{request_id, status}`.
- `GET /api/runs/{request_id}` → returns full row or 404.
- `_run_pipeline(request_id)` calls `el.pipeline.run_for_request(request_id)` wrapped in `try/except` that marks status=error with truncated message.

### 4.8 `el/web/routes/chat.py`
- `POST /api/chat` body: `{question: str, top_k?: int}`
- Response: `text/event-stream` SSE with events `chunk` (token batches) and `done` (final).
- Delegates entirely to `chat_rag.stream_answer(...)`.

### 4.9 `el/web/chat_rag.py`
```python
def stream_answer(*, question: str, top_k: int,
                  embedding_provider, db_provider, llm_stream) -> Iterator[str]:
    """Yields JSON-lines payloads suitable for SSE 'data:' lines."""
```
Algorithm:
1. `embedding_provider.embed_text(question)` → query vec.
2. `find_similar_products(query_text=question, ..., top_n=top_k, ...)` → context rows.
3. Build prompt: system instruction + bullet list of `{product_name}: {product_url}` for each context row + the user question.
4. Yield `{"event":"context","products":[…]}` first (so UI can show citations).
5. Stream `llm_stream(prompt)` chunks as `{"event":"chunk","text":"…"}`.
6. Yield `{"event":"done"}`.
7. On any provider exception, yield `{"event":"error","message":str(e)}` and stop.

`llm_stream` is a callable `prompt: str -> Iterator[str]`. Default impl in `el/llm.py` wraps Vertex Gemini `generate_content(stream=True)`. Tests pass a deterministic fake.

### 4.10 `el/web/routes/health.py`
`GET /healthz` → `{"ok": true, "version": <git sha or unknown>}`. No auth, no DB call.

### 4.11 `el/web/templates/`
Three Jinja2 templates inheriting from `base.html`:
- `index.html` — niche/dislikes/budget form, HTMX `hx-post="/api/runs"`.
- `run.html` — polls `/api/runs/{id}` every 3s via HTMX `hx-trigger="every 3s"`.
- `chat.html` — chat form posting to `/api/chat`; uses native `EventSource` for SSE.

Tailwind via CDN `<script src="https://cdn.tailwindcss.com"></script>`. HTMX via CDN. No build step. Total templates: ~150 LoC.

### 4.12 `el/pipeline.py` change
Add:
```python
def run_for_request(request_id: str, *, db_provider=None) -> str:
    """Marks request running, runs pipeline with niche from request row, marks done/error."""
```
Reads the row, sets `ctx["niche"]`/`ctx["dislikes"]`/`ctx["budget_usd"]` from it, calls existing `run()`.

## 5. Configuration

New `.env.example` section 13:
```
# --- SP4: web + chat ----
EL_WEB_ENABLED=false
WEB_SECRET_KEY=                  # 32-byte random; required when EL_WEB_ENABLED=true
WEB_RATE_LIMIT_PER_MINUTE=30
WEB_CHAT_TOP_K=5
WEB_LLM_MODEL=gemini-2.0-flash   # for the chat bot
```

`EL_WEB_ENABLED=false` keeps the existing pipeline-only flow untouched; tests force `true`.

## 6. Error handling

Per master spec §SP4: every API endpoint returns `application/json` with stable error codes — never HTML stack traces. Codes used:
- `ERR_AUTH` (401) — missing/bad bearer.
- `ERR_RATE_LIMIT` (429) — bucket empty; `retry_after` field.
- `ERR_VALIDATION` (422) — malformed body.
- `ERR_RUN_NOT_FOUND` (404).
- `ERR_INTERNAL` (500) — generic catch-all; logs traceback.

A global FastAPI `exception_handler(Exception)` turns any uncaught exception into `ERR_INTERNAL` with no stack-trace leak.

## 7. Testing strategy

`tests/web/` (new directory):
- `test_health.py` — `/healthz` returns 200; no auth.
- `test_auth.py` — protected route → 401 without/with-bad token; 200 with good.
- `test_rate_limit.py` — N+1 requests within window → 429.
- `test_runs_routes.py` — POST writes row, returns 202; GET returns row.
- `test_run_service.py` — pure helper logic.
- `test_chat_rag.py` — `stream_answer` with fake embedding/db/llm yields expected event sequence + handles per-step errors.
- `test_chat_route.py` — `/api/chat` SSE returns expected events; SSE format parseable.
- `test_run_for_request.py` — `pipeline.run_for_request` updates row status, handles pipeline raise.

All tests use `TestClient` (sync) + `FakeEmbeddingProvider` + `_CapturingDB` patterns reused from SP3 tests.

**Coverage target:** ≥90% for `el/web/`. No live Vertex / Supabase calls.

## 8. Definition of Done

- ✅ `tests/web/` ≥ 90% coverage; full suite green.
- ✅ Migration `migrations/sp4/001_run_requests.sql` applies idempotently.
- ✅ `uvicorn el.web:create_app --factory` boots locally; manual curl test passes:
  - `GET /healthz` → 200
  - `POST /api/runs` with bearer → 202 + row in `private.run_requests`
  - `POST /api/chat` with bearer + question → SSE stream completes
- ✅ Three HTMX pages render without console errors in a browser.
- ✅ `EL_WEB_ENABLED=false` keeps existing pipeline tests green (no regression).
- ✅ `.env.example` updated; `PHASE3_ROADMAP.md` marks SP4 ✅; `docs/SP4_LOG.md` written.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Vertex Gemini cost from open chat | Rate-limit + bearer-only access while single-operator. |
| BackgroundTasks blocks request worker for long pipeline runs | Acceptable for MVP (single user); revisit in SP8 with proper task queue if needed. |
| HTMX/Tailwind via CDN = network dep at page load | Acceptable for private app; vendoring deferred to SP8 if needed. |
| SSE buffering by upstream proxies | Add `X-Accel-Buffering: no` header in chat route; documented in SP8 nginx/caddy config later. |

## 10. Out-of-band human work

Post-merge, before exposing the app:
1. Apply `migrations/sp4/001_run_requests.sql` in Supabase SQL editor.
2. Generate and store `WEB_SECRET_KEY` (e.g., `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
3. Run a synthetic round-trip locally: submit a low-cost niche, watch the row transition queued → running → done.
