# SP8 — Docker + Hetzner Deploy Iteration Log

**Spec:** `docs/superpowers/specs/2026-05-25-sp8-docker-deploy-design.md`
**Plan:** `docs/superpowers/plans/2026-05-25-sp8-docker-deploy.md`
**Started:** 2026-05-25
**Code-complete:** 2026-05-26
**Branch:** `claude/task-8-commit-review-iIbaW` (awaiting squash-merge to `main`)

## Summary

SP8 turns the SP4 FastAPI app into a deployable production stack: one
multi-stage Docker image used by two services (`api` running uvicorn,
`worker` running `python -m el.worker`), fronted by Caddy with
`tls internal`, deployed to a single Hetzner CX22 by GitHub Actions on
push to `main`. Deploys are immutable image tags (`:sha-<short>`) with
`:latest` only re-tagged after the post-deploy `/healthz` poll passes;
healthz failure restores the previous `compose.env` and re-pulls the
prior tag.

The worker replaces SP4's in-process `BackgroundTasks` execution. The
`/api/runs` route is now enqueue-only — it inserts a `queued` row in
`private.run_requests` and returns 202. A single worker container polls
the queue, claims the oldest queued row via a conditional UPDATE
(`status=queued` guard), runs the pipeline, and marks `done`/`error`.
Compose declares `replicas: 1`, making the claim race-free by
configuration; the conditional UPDATE is defense in depth.

Per the SP8 plan §Implementation Notes, **Sentry DSN wiring**,
**APScheduler / `el/web/scheduler.py`**, **`el/web/asgi.py`**, and
**Let's Encrypt** are deferred (the runbook documents the LE swap
procedure). Sentry's SDK is pinned in `requirements.txt` so wiring is
a one-import change when monitoring is decided.

## What changed

| Area | Change |
|------|--------|
| Deps | `requirements.txt` rewritten to runtime-only (fastapi, uvicorn, supabase, google-cloud-aiplatform, sentry-sdk, etc.); `requirements-dev.txt` added with pytest + coverage. |
| Container | `Dockerfile` multi-stage (python:3.12-slim builder + runtime), non-root `appuser` (uid 10001), `PYTHONPATH=/app`, `EXPOSE 8000`. `docker-entrypoint.sh` runs `verify_env_runtime.py` then `exec "$@"`. `.dockerignore` excludes git/venv/tests/docs/paper/data JSON. |
| Env validator | `scripts/verify_env_runtime.py` — reads `os.environ` only (no network, no `.env` file). Checks 11 required vars + parses `GOOGLE_SERVICE_ACCOUNT_JSON` and verifies its 5 required fields. Coexists with the existing `scripts/verify_env.py` (which does live API probes). |
| Worker | `el/worker.py` — `tick()` (one unit of work), `run_loop()` (stop-event-gated polling), `main()` (binds SIGTERM/SIGINT → stop event). `_POLL_SECONDS` configurable via `EL_WORKER_POLL_SECONDS` (default 30s). `_ERROR_MESSAGE_MAX_LEN=2000`. |
| Run service | `el/web/run_service.py:claim_one_queued(*, worker_id, db_provider)` — find oldest queued row, conditional-update with `filters={"id": ..., "status": "eq.queued"}` guard. Returns `dict \| None`. |
| Routes | `el/web/routes/runs.py` no longer takes `BackgroundTasks` or calls `_run_pipeline_safe` — the route is pure enqueue. `el/web/routes/health.py` rewritten: `/healthz` returns 200 with `{ok: true, version, checks: {db, vertex_creds}}` or 503 with the same shape on any failure. No network calls in the vertex_creds check (parses SA JSON only). |
| Settings | `el/web/settings.py` exposes `google_service_account_json: str \| None`, loaded from `os.environ` in `from_env()`. |
| Supabase client | `el/supabase.py:update_rows` now accepts multi-key filter dicts (e.g. `{"id": "eq.X", "status": "eq.queued"}`); `select_rows` already handled it. New `SupabaseRestProvider.ping()` (2s GET against `/rest/v1`) used by `/healthz`. |
| Test infra | `tests/web/conftest.py:FakeDB.update_rows` honors multi-key filters; new `FakeDB.list_queued()` helper. `pytest.ini` registers the `docker` marker for opt-in integration tests. |
| Compose | `docker-compose.yml` — api (with `/healthz` healthcheck, 30s stop_grace), worker (`replicas: 1`, 24h stop_grace), caddy (depends on api `service_healthy`). Named volumes `el-data`, `caddy-data`, `caddy-config`. Image ref `ghcr.io/${GHCR_OWNER}/el:${EL_IMAGE_TAG}`. |
| Reverse proxy | `Caddyfile` — `:443` with `tls internal` + `reverse_proxy api:8000`; `:80` redirects to https. |
| CI/CD | `.github/workflows/deploy.yml` — `test` (pytest -q) → `build` (buildx + GHCR push of `:sha-<short>`, GHA cache) → `deploy` (ssh-action writes new `compose.env`, `docker compose up -d`, polls `/healthz` 12× over 60s, on success re-tags `:latest`, on failure restores `compose.env.prev` and re-pulls). `concurrency: deploy` (no cancel). |
| Bootstrap | `scripts/deploy/hetzner_bootstrap.sh` — idempotent: verifies Ubuntu 24.04, installs Docker via convenience script, creates `deploy` user, hardens sshd (no root, no password auth), `ufw` allow 22/80/443, creates `/etc/el` (mode 700) + `/var/lib/el`, fetches `docker-compose.yml` + `Caddyfile` from GitHub raw at pinned SHA, touches `.env`/`compose.env`/`compose.env.prev`. |
| Tests (new) | `tests/test_verify_env_runtime.py` (4), `tests/test_worker.py` (6), `tests/test_dockerfile_lint.py` (7), `tests/integration/test_sp8_compose_smoke.py` (1 opt-in). Existing tests updated: `tests/web/test_routes_health.py` rewritten for db + vertex_creds; `tests/web/test_routes_runs.py` no longer asserts background task; `tests/test_supabase.py` adds multi-key-filter test. |
| Docs | `docs/runbooks/deploy.md` (initial provision, day-2 ops, manual rollback, disaster recovery, cost monitoring, LE swap, documented out-of-scope failure modes). |

## Commits (in order)

| Commit | Task | What |
|---|---|---|
| `4acd8aa` | spec+plan | Design spec + implementation plan |
| `d79edf1` | T1 | Split runtime and dev requirements |
| `75d9326` | T2 | `.dockerignore` |
| `f6f98bc` | T3 | Fail-fast env validator for container entrypoint |
| `47d15fc` | T4 | FakeDB honors multi-key filters; `list_queued` helper |
| `9ff86b9` | T5 | `claim_one_queued` for the SP8 worker |
| `f2e1ea8` | T6 | Runs route only enqueues; worker container executes |
| `89850c7` | T7 | `/healthz` checks db + vertex_creds, returns 503 on failure |
| `91260eb` | T8 | Background worker that drains `run_requests` |
| `820d7d2` | T9 | Multi-stage Dockerfile + entrypoint env validation |
| `a7cce6a` | T10 | Docker-compose stack (api + worker + caddy) |
| `4ee96b6` | T11 | Opt-in compose smoke test |
| `6a11171` | T12 | Test job for deploy workflow |
| `0100890` | T13 | Build and push image to GHCR on main |
| `3c7d4f2` | T14 | Deploy with healthz poll and automatic rollback |
| `30632ef` | T15 | Hetzner CX22 bootstrap script |
| `2c03502` | T16 | Deploy runbook |

## Deploy runbook (summary; full version: `docs/runbooks/deploy.md`)

1. **Spin up a Hetzner CX22** (Ubuntu 24.04, nbg1, ~€3.79/mo).
2. **Bootstrap as root:**
   ```bash
   curl -fsSL https://raw.githubusercontent.com/sadine27/EL-SEM-II/<PIN_SHA>/scripts/deploy/hetzner_bootstrap.sh \
     | PIN_SHA=<PIN_SHA> bash
   ```
   Substitute `<PIN_SHA>` with the squash-merge SHA. Never use `main`.
3. **Paste deploy SSH pubkey** into `/home/deploy/.ssh/authorized_keys` (mode 600).
4. **Paste production `.env`** into `/etc/el/.env` (mode 600, owner `deploy`) — see `.env.example`.
5. **Set GitHub repo config:** vars `GHCR_OWNER`, `HETZNER_SSH_HOST`; secrets `HETZNER_SSH_USER`, `HETZNER_SSH_KEY`.
6. **First deploy:** push to `main`. Workflow tests → builds → deploys → polls `/healthz` → re-tags `:latest`.
7. **Smoke:** `curl -k https://<host>/healthz` → `{"ok": true, "checks": {"db": "ok", "vertex_creds": "ok"}}`. Submit a niche through the SP4 web UI; confirm Telegram HIL card; approval populates the SP5 Shopify dev store.

## Rollback

Automatic: deploy workflow restores `/etc/el/compose.env.prev` and re-pulls
the previous tag on any healthz failure within 60s of `docker compose up -d`.

Manual:
```bash
ssh deploy@<host>
cd /etc/el
mv compose.env.prev compose.env
docker compose --env-file compose.env pull
docker compose --env-file compose.env up -d
```

Per-feature kill-switch: SP5/SP6 env flags (e.g. `EL_SHOPIFY_AUTO_STORE_ENABLED`)
remain untouched by SP8 and continue to work as documented.

## Iteration outcomes (post-merge verification)

**Date:** 2026-05-26  
**Environment:** Laptop (Ryzen 5 7235HS, 24 GB RAM, Windows 11) with Docker Desktop + Cloudflare Quick Tunnel  
**Deployment strategy:** Laptop-hosted Docker Compose (replaces Hetzner CX22 for zero-cost local hosting)

### Task A — Docker local verification

| Check | Result |
|-------|--------|
| `docker build -t el:local .` | PASS — image builds clean |
| Image size | PASS — under 500 MB |
| `DOCKER_AVAILABLE=1 pytest tests/integration/test_sp8_compose_smoke.py -v` | PASS |
| Cold-start `https://localhost/healthz` | PASS — 200 within 10s |
| Real env loaded (SUPABASE_URL, WEB_SECRET_KEY, GOOGLE_SERVICE_ACCOUNT_JSON) | PASS |
| `/healthz` with live credentials: `{"ok":true,"checks":{"db":"ok","vertex_creds":"ok"}}` | PASS |

### Task D1 — Public /healthz via Cloudflare Quick Tunnel

Public URL: `https://yrs-baghdad-indie-coaches.trycloudflare.com` (ephemeral — regenerates on each tunnel restart)

```json
{"ok":true,"version":"unknown","checks":{"db":"ok","vertex_creds":"ok"}}
```

PASS — real Supabase + real Google SA both verified over public HTTPS with no port forwarding or VPS.

### Task D2 — POST /api/runs smoke

BLOCKED — `private.run_requests` table not yet created in Supabase (SP4 migration not applied).  
Fix: apply `migrations/sp4/001_run_requests.sql` in Supabase SQL Editor and expose `private` schema in API settings.  
Once unblocked: re-run `curl -X POST https://<tunnel>/api/runs -H "Authorization: Bearer <WEB_SECRET_KEY>" -d '{"niche":"smoke-test"}'`.

### Deploy workflow

`test` + `build` jobs run on every push to main. `deploy` job is skipped (not failed) when `HETZNER_SSH_HOST` is unset — safe for laptop-hosting mode.

### Task E — Post-merge housekeeping (2026-05-26)

| Item | Result |
|------|--------|
| Node.js 20 deprecation: added `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` to `ci.yml` + `deploy.yml` | DONE — CI green on new SHA `682455d` |
| `ci.yml` Python version bumped 3.10 → 3.12 to match Dockerfile | DONE |
| `migrations/combined_apply_all.sql` created (SP1→SP3→SP4→SP6 in one paste) | DONE |
| `.env.example` sections 16 (SP6 CRM) + 17 (SP8 worker) added; `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` documented as Option B for SP5b | DONE |
| `PHASE3_ROADMAP.md` Next action updated to reference combined migration script | DONE |

---

## Acceptance verification

- [x] Multi-stage Dockerfile, python:3.12-slim, non-root `appuser`, no `ADD`, every `apt-get install` uses `--no-install-recommends` (enforced by `tests/test_dockerfile_lint.py`).
- [x] `verify_env_runtime.py` is synchronous, reads `os.environ` only, fails non-zero with named missing vars (4 unit tests).
- [x] `claim_one_queued` two-step claim guarantees no double-execution under sequential claim attempts (`tests/test_worker.py::test_claim_race_two_workers_one_row`).
- [x] `/healthz` returns 200 only when both db and vertex_creds checks pass; otherwise 503 with structured error per check; no network call for vertex_creds (5 unit tests).
- [x] Worker truncates error messages to ≤2000 chars; SIGTERM/SIGINT cleanly exits `run_loop` within one tick.
- [x] `docker-compose.yml` healthcheck-gates `caddy` on `api: service_healthy`; worker has `stop_grace_period: 86400s` to protect long pipeline runs.
- [x] 652/652 unit + web suite green; +1 opt-in compose smoke skipped without `DOCKER_AVAILABLE=1`.
- [x] Docker-daemon verification (image builds, image-size < 500 MB, cold-start < 10s, `DOCKER_AVAILABLE=1 pytest tests/integration -v` passes). *(verified 2026-05-26 on local laptop.)*
- [x] Substitute `PIN_SHA` placeholders in `scripts/deploy/hetzner_bootstrap.sh` and `docs/runbooks/deploy.md` with the squash-merge SHA at merge time. *(done in commit 45f5c20.)*
- [ ] End-to-end smoke (niche → Telegram HIL → Shopify dev store). *(blocked on `private.run_requests` migration — see Task D2 above.)*
- [ ] Bad-commit rollback test: intentional syntax error in `el/web/app.py`, push, confirm healthz fails, rollback restores prior `:sha-<short>`, workflow exits non-zero. *(post-merge.)*

## Surprises / decisions deferred

- **Worker single-replica is the primary race guard.** The spec also requires a
  conditional UPDATE; SP8 ships both. Compose `replicas: 1` is the simple
  contract (impossible to race), the UPDATE-with-`status=queued`-guard is
  defense-in-depth in case a future deploy scales workers up by mistake.
- **`/healthz` performs no network check for Vertex credentials** — only
  parses the SA JSON and validates the five required fields
  (`type`, `project_id`, `private_key`, `client_email`, `token_uri`). A
  network probe would make healthz slow and flaky; the existing
  `scripts/verify_env.py` covers live API verification at deploy time.
- **`scripts/verify_env_runtime.py` is a separate script from
  `scripts/verify_env.py`.** The runtime one is synchronous, network-free,
  and safe to run on every container boot; the existing one does live API
  probes against `.env.example`. Both coexist; entrypoint uses runtime
  only.
- **`PIN_SHA` placeholder is intentional sequencing, not a TODO.** The
  bootstrap script fetches `docker-compose.yml` + `Caddyfile` from GitHub
  raw at a specific commit, but that commit hash cannot exist until the
  branch is squash-merged to `main`. Runbook step 2 documents the
  substitution explicitly.
- **`run_for_request` (SP4) is now called only by the worker.** The
  `_run_pipeline_safe` helper in `el/web/routes/runs.py` and its
  `BackgroundTasks` invocation were removed; the route is pure enqueue.
  Existing SP4 tests for `run_for_request` continue to exercise the
  pipeline-execution path through the worker fakes.
- **Sentry SDK is pinned but not wired.** `sentry-sdk==2.18.0` is in
  `requirements.txt` so a future commit can call `sentry_sdk.init(...)`
  in `el/web/app.py` without a deploy-time dependency change. Monitoring
  stack decision (Sentry vs OpenTelemetry vs nothing) deferred — the spec
  only requires error reporting, not a specific vendor.
- **No `el/web/__init__.py` change.** The `create_app` re-export is
  unchanged from SP4; the worker imports `el.web.run_service` directly,
  which keeps non-web tests FastAPI-free (same property SP4 added).
- **Caddy uses `tls internal` (self-signed) by default.** Browser users
  will see a cert warning. `docs/runbooks/deploy.md` §"Upgrading to a
  real domain + Let's Encrypt" documents the swap.
- **Working directory must be a git repo for `/healthz` to surface a
  version.** `el/web/routes/health.py:_git_sha()` shells out to
  `git rev-parse --short HEAD` with a 1s timeout and falls back to
  `"unknown"` — production container will get `"unknown"` because `.git`
  is excluded by `.dockerignore`. This is the desired SP4 behavior
  preserved (the GHA workflow can later inject `EL_GIT_SHA` if we want a
  real value in production).
