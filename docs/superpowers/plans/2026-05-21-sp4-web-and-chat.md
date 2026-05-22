---
title: "SP4 — FastAPI Web App + RAG Chat Bot — Implementation Plan"
date: 2026-05-21
sub_project: SP4
spec: ../specs/2026-05-21-sp4-web-and-chat-design.md
---

# SP4 — Implementation Plan

TDD throughout. Each task = one commit on `feat/sp4-web-and-chat`. Squash-merge after T8.

---

## T1 — Migration + settings + supabase constants

**Files:**
- `migrations/sp4/001_run_requests.sql` — table + index (see spec §3).
- `el/supabase.py` — add constants `RUN_REQUESTS_TABLE = "run_requests"`, `RUN_REQUESTS_SCHEMA = "private"`.
- `el/web/__init__.py` — empty package marker.
- `el/web/settings.py` — `Settings` dataclass with `from_env()` classmethod.
- `.env.example` — append section 13 (see spec §5).

**Tests:**
- `tests/web/__init__.py` empty.
- `tests/web/test_settings.py` — `from_env()` reads env vars with defaults; raises `RuntimeError` when `WEB_SECRET_KEY` is unset.

**DoD:** `pytest tests/web/test_settings.py` green.

---

## T2 — Auth bearer-token

**Files:** `el/web/auth.py`
```python
def verify_bearer(authorization_header: str | None, expected_secret: str) -> str:
    """Returns principal name on success. Raises AuthError on failure."""
```
- Pure function — no FastAPI imports.
- `class AuthError(Exception)`.
- `hmac.compare_digest` for the token comparison.

**Tests:** `tests/web/test_auth.py`
- Missing header → `AuthError`.
- Wrong scheme (`Basic ...`) → `AuthError`.
- Wrong token → `AuthError`.
- Correct token → returns `"operator"`.

**DoD:** tests green.

---

## T3 — Rate limiter

**Files:** `el/web/rate_limit.py`
```python
class TokenBucket:
    def __init__(self, *, capacity: int, refill_per_sec: float, clock=time.monotonic): ...
    def try_consume(self, key: str, tokens: int = 1) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
```
- In-memory dict keyed by `key`.
- Lazy refill on each call.
- `retry_after` = `0.0` if allowed.

**Tests:** `tests/web/test_rate_limit.py`
- N consecutive consumes within capacity succeed; N+1 fails.
- After elapsed time (mocked clock), bucket refills and allows next consume.
- Different keys are independent.

**DoD:** tests green; 100% coverage of `rate_limit.py`.

---

## T4 — run_service + pipeline.run_for_request

**Files:**
- `el/web/run_service.py` — pure helpers from spec §4.6.
- `el/pipeline.py` — add `run_for_request(request_id, *, db_provider=None) -> str`. Reads `private.run_requests` row, marks running, calls existing `run(ctx)`, marks done/error.

**Tests:**
- `tests/web/test_run_service.py` — submit_run inserts correctly; get_run returns or None; mark_* call update_rows with right filters/updates.
- `tests/web/test_run_for_request.py` — happy path: row goes queued→running→done. Pipeline raise → status=error, error_message set. Missing row → raises ValueError before any pipeline call.

Uses `_FakeDB` capturing all method invocations.

**DoD:** tests green.

---

## T5 — chat_rag.stream_answer

**Files:** `el/web/chat_rag.py`
```python
def stream_answer(*, question: str, top_k: int,
                  embedding_provider, db_provider,
                  llm_stream) -> Iterator[dict]:
    """Yields event dicts: {event: 'context'|'chunk'|'done'|'error', ...}."""
```
Algorithm per spec §4.9.

**Tests:** `tests/web/test_chat_rag.py`
- Happy path: yields context event with N products, then ≥1 chunk events, then done.
- Embed failure → single error event.
- find_similar failure (db raises) → single error event.
- LLM stream raises mid-stream → context + partial chunks + error event.
- top_k passed through to find_similar.

Uses `FakeEmbeddingProvider` + `_CapturingDB` (from SP3) + a `_fake_llm_stream` callable.

**DoD:** tests green; ≥95% coverage of `chat_rag.py`.

---

## T6 — FastAPI app + routes

**Files:**
- `el/web/app.py` — `create_app(settings)` factory.
- `el/web/routes/__init__.py` empty.
- `el/web/routes/health.py` — GET /healthz.
- `el/web/routes/runs.py` — POST/GET /api/runs.
- `el/web/routes/chat.py` — POST /api/chat (SSE).
- `el/web/errors.py` — `register_error_handlers(app)` for ERR_* codes (spec §6).

**Wiring:**
- A `Depends(get_principal)` resolves bearer auth via `el.web.auth.verify_bearer`.
- A middleware applies `TokenBucket` per `request.client.host`, skipping `/healthz` + `/static`.

**Tests:** `tests/web/test_routes_health.py`, `test_routes_runs.py`, `test_routes_chat.py`
- /healthz: 200, no auth, `{"ok": true, ...}`.
- /api/runs POST without bearer → 401 ERR_AUTH; with bearer + valid body → 202 + request_id.
- /api/runs GET unknown id → 404 ERR_RUN_NOT_FOUND.
- /api/runs POST malformed (empty niche) → 422 ERR_VALIDATION.
- /api/chat SSE returns `text/event-stream` with `data: {event:"context"...}\n\n` then chunks then done.
- Rate-limit: monkeypatch `Settings.rate_limit_per_minute=2`; 3 requests → third is 429 with `retry_after`.
- Uncaught exception in route → 500 ERR_INTERNAL (no stack trace in body).

Uses FastAPI `TestClient`. SSE parsed by reading `response.iter_lines()`.

**DoD:** tests green; coverage of `el/web/` ≥ 90%.

---

## T7 — HTMX templates

**Files:**
- `el/web/templates/base.html` — head with HTMX + Tailwind CDN + page block.
- `el/web/templates/index.html` — niche/dislikes/budget form, hx-post target = `/api/runs`.
- `el/web/templates/run.html` — polls `/api/runs/{id}` every 3s.
- `el/web/templates/chat.html` — chat box using native `EventSource`.
- `el/web/static/app.css` — minimal layout overrides.
- Routes: add `GET /`, `GET /run/{id}`, `GET /chat` that render the templates (use Jinja2Templates).

**Tests:** `tests/web/test_templates.py`
- Each page returns 200 and contains expected element IDs (`#niche-form`, `#run-status`, `#chat-form`).
- Templates render with no Jinja errors.

**DoD:** tests green. Manual smoke (documented in SP4_LOG): `uvicorn` boots, three pages render without console errors.

---

## T8 — Log + roadmap + merge

**Files:**
- `docs/SP4_LOG.md` — summary, commits-in-order table, deploy runbook, rollback, acceptance.
- `PHASE3_ROADMAP.md` — mark SP4 ✅, advance Next action to SP5.

**Actions:**
- Full `pytest` run, capture pass count + coverage.
- Squash-merge `feat/sp4-web-and-chat` → `main` with comprehensive squash message.
- Push (deferred — user does push manually per project policy).

**DoD:** main has the squash commit; all tests green; roadmap updated.

---

## Risk register (for log)

- **FastAPI as new dep.** Pin to `>=0.115,<0.116`. Add to `requirements.txt`.
- **Jinja2 transitively installed by FastAPI**, but explicit pin for safety.
- **TestClient sync-mode SSE.** FastAPI `TestClient.stream("POST", "/api/chat")` returns response with `iter_lines()`; we read until terminator event.
- **BackgroundTasks blocks request worker if pipeline runs long.** Accepted MVP risk — single operator, low concurrency. SP8 revisits.
