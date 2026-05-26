# SP8 — Docker + Production Deploy (Design)

**Date:** 2026-05-25
**Phase:** 3 / SP8
**Status:** Design approved; ready for implementation plan
**Depends on:** SP4 (FastAPI app + `private.run_requests` table), SP5 (Shopify auto-store + notify_business)
**Parallel with:** SP6, SP7 (other teammate continuing Shopify production-readiness on commit `8807b33`)

## 1. Goals & non-goals

### Goals
1. Ship the SP4 FastAPI app + a background worker as a single reproducible Docker image deployed to one Hetzner CX22 host (€3.79/mo, 4 GB RAM, nbg1).
2. Auto-deploy on push to `main` via GitHub Actions, with a healthz gate and automatic rollback to the prior image tag if the new container fails to come up healthy.
3. Close the runtime-dependency gap: `requirements.txt` currently only carries test/auth deps; the image must install everything the app actually imports (fastapi, uvicorn, pydantic, supabase, google-cloud-aiplatform, jinja2, httpx, sentry-sdk, etc.).
4. Replace the SP4 host-side filelock (if any) with a DB-level claim against `private.run_requests` and a single worker replica, so concurrency is correct by construction.
5. Survive a 24-hour in-flight pipeline run across deploys (worker `stop_grace_period: 86400s`).

### Non-goals
- Multi-region or failover.
- Auto-scaling (single api + single worker container is the target).
- Custom domain + Let's Encrypt (Caddy ships self-signed `tls internal`; LE swap is a documented day-2 procedure).
- DB schema drift detection or migration automation (migrations stay manual).
- Image vulnerability scanning in CI (out of scope; document as a follow-up).
- Browser-friendly demo to non-technical users (the self-signed cert warning is a blocker for that path).

## 2. Architecture

```
Internet ──443/tls-internal──▶ Caddy ──http──▶ api (uvicorn :8000)
                                         ▲
                                         │ healthz
                                         │
                            worker (loop, polls private.run_requests)
                                         │
                                         ▼
                                  Supabase Postgres
                                  (private.run_requests, etc.)
```

- **Single image, three services:** `api`, `worker`, `caddy` in one `docker-compose.yml` on the Hetzner host. `api` and `worker` are the same image with different `command:` entries. Caddy is the upstream `caddy:2-alpine`.
- **Worker contract:** plain `while not stop.is_set(): tick(); stop.wait(30)` loop. SIGTERM/SIGINT set the event. No APScheduler.
- **Claim pattern:** `process_one_queued_run()` runs
  ```sql
  UPDATE private.run_requests
     SET status = 'running', claimed_by = $worker_id, started_at = now()
   WHERE id = (SELECT id FROM private.run_requests
                WHERE status = 'queued' ORDER BY submitted_at LIMIT 1
                FOR UPDATE SKIP LOCKED)
   RETURNING *;
  ```
  Race-safe; no orphaned-lock recovery needed. Combined with `deploy.replicas: 1`, two workers cannot collide even if misconfigured.
- **`private.run_requests`** is the Postgres schema/table created in SP4 (Supabase). Defined here only as the worker's queue.
- **Caddy** terminates TLS with a self-signed cert (`tls internal`). Reverse-proxies to `api:8000`. The web UI from SP4 (HTMX) is browser-facing through this Caddy — users will hit a cert warning. That is acceptable only for the testing audience SP8 targets. Domain + LE upgrade is documented in the runbook.
- **State:**
  - `el-data` named volume mounted at `/app/data` for any local artifacts (so `docker compose down` doesn't wipe them).
  - `caddy-data`, `caddy-config` named volumes so the self-signed CA survives restarts (preventing fresh cert prompts on every redeploy).
  - All persistent business state lives in Supabase, not on the host.

## 3. Image, deps, compose

### Dockerfile
- Multi-stage:
  - **Stage 1 (builder):** `python:3.12-slim`. `apt-get install --no-install-recommends` for compilers needed by any wheels missing manylinux builds. `pip install -r requirements.txt` into `/install`.
  - **Stage 2 (runtime):** `python:3.12-slim`. Copy `/install` from builder. Create `appuser` (uid 10001), `chown -R appuser /app`, `USER appuser` **before** `CMD`. `COPY` only (never `ADD`). Default `CMD` is the uvicorn entrypoint; `docker-compose.yml` overrides for the worker.
- **Entrypoint:** `docker-entrypoint.sh` runs `python scripts/verify_env.py` then `exec "$@"`. The verify step fails fast on missing/invalid env vars at container start, so misconfiguration surfaces in `docker compose up -d` instead of mid-request.
- Image size budget: **< 500 MB**. Achieved by multi-stage + `--no-install-recommends` + no dev deps in the runtime layer.

### requirements split
- `requirements.txt` — runtime only. Expected set (verify by walking `el/` imports during implementation): `fastapi`, `uvicorn[standard]`, `pydantic`, `jinja2`, `httpx`, `python-dotenv`, `google-auth`, `google-cloud-aiplatform`, `supabase`, `pgvector`, `sentry-sdk`, `requests`, `cachetools`.
- `requirements-dev.txt` — `pytest`, `pytest-cov`, `coverage`, `ruff` (if used). **Never** installed into the runtime image.

### docker-compose.yml
```yaml
services:
  api:
    image: ghcr.io/${GHCR_OWNER}/el:${EL_IMAGE_TAG}   # no default — errors loudly if unset
    env_file: /etc/el/.env
    volumes: [el-data:/app/data]
    command: ["uvicorn", "el.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
    restart: unless-stopped
    stop_grace_period: 30s
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3

  worker:
    image: ghcr.io/${GHCR_OWNER}/el:${EL_IMAGE_TAG}
    env_file: /etc/el/.env
    volumes: [el-data:/app/data]
    command: ["python", "-m", "el.worker"]
    restart: unless-stopped
    stop_grace_period: 86400s   # 24h — protects an in-flight pipeline run from being killed by a deploy
    deploy:
      replicas: 1

  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    restart: unless-stopped
    depends_on:
      api:
        condition: service_healthy

volumes:
  el-data: {}
  caddy-data: {}
  caddy-config: {}
```

### Caddyfile
```
{
  email admin@example.invalid
}

:443 {
  tls internal
  reverse_proxy api:8000
}
```

### /healthz contract
Returns JSON:
- **200** when all checks pass:
  ```json
  {"ok": true, "checks": {"db": "ok", "vertex_creds": "ok"}}
  ```
- **503** if any check fails, with the failing check's message:
  ```json
  {"ok": false, "checks": {"db": "error: timeout", "vertex_creds": "ok"}}
  ```
- `db` check: `SELECT 1` against Supabase with a 2-second timeout.
- `vertex_creds` check: parse the service-account JSON and verify the token's `exp` is in the future. No network call.
- The Docker healthcheck probe (`curl -fsS http://localhost:8000/healthz`) and the CI deploy gate both hit this endpoint. Its truthfulness is the only thing standing between a broken deploy and an outage, so it must check live dependencies, not just process liveness.

### .dockerignore
Excludes: `.git/`, `.venv/`, `.pytest_cache/`, `.vscode/`, `.claude/`, `.env`, `.env.example`, `tests/`, `paper/`, `docs/`, `legacy/`, `data/*.json`, `*.aux`, `*.log`, `*.out`, `main.*` (LaTeX artifacts), `node_modules/`, `requirements-paper.txt`, `memory/`, `.coverage`.

## 4. CI/CD

### Workflow: `.github/workflows/deploy.yml`
Two jobs.

**Job 1 — `test`:** `actions/setup-python@v5` with 3.12, install `requirements.txt` + `requirements-dev.txt`, run `pytest -q`. Gate; nothing downstream runs on failure.

**Job 2 — `build-and-deploy` (`needs: test`):**
1. `docker/setup-buildx-action`, `docker/login-action` against `ghcr.io` with `GITHUB_TOKEN` (`packages: write` at job scope; no separate GHCR token).
2. Build & push `ghcr.io/<owner>/el:sha-${{ github.sha }}` (immutable tag).
3. `appleboy/ssh-action` to the host:
   ```bash
   set -euo pipefail
   cd /etc/el
   cp compose.env compose.env.prev                    # save current tag for rollback
   echo "EL_IMAGE_TAG=sha-<short>" > compose.env.new
   echo "GHCR_OWNER=<owner>"      >> compose.env.new
   mv compose.env.new compose.env                     # atomic swap
   docker compose --env-file compose.env pull
   docker compose --env-file compose.env up -d
   ```
4. Back on the runner, poll healthz with a 60 s ceiling:
   ```bash
   for i in $(seq 1 12); do
     curl -fsS -k https://<host>/healthz && exit 0
     sleep 5
   done
   exit 1
   ```
5. **On success:** re-tag `:sha-<short>` as `:latest` via a second `docker buildx imagetools create`.
6. **On failure:** SSH back, run
   ```bash
   cd /etc/el
   mv compose.env.prev compose.env
   docker compose --env-file compose.env pull
   docker compose --env-file compose.env up -d
   ```
   then fail the job loudly so the human knows rollback fired.

### GitHub vars vs secrets
- **`vars`** (config, not sensitive): `GHCR_OWNER`, `HETZNER_SSH_HOST`.
- **`secrets`** (credentials): `HETZNER_SSH_KEY`, `HETZNER_SSH_USER`.

### Concurrency
```yaml
concurrency:
  group: deploy
  cancel-in-progress: false
```
Subsequent deploys queue while one is in progress. Combined with the worker's 24 h `stop_grace_period`, this means a backlog of deploys can sit waiting for a long pipeline run to finish. That is the intended behavior; emergency override is `docker compose kill worker` on the host (documented in the runbook).

### Migrations
Manual via the Supabase dashboard or the `supabase` CLI. SP8 does not automate.

## 5. Host bootstrap, runbook, testing, success criteria

### `scripts/deploy/hetzner_bootstrap.sh`
Idempotent. Run once per fresh CX22 (Ubuntu 24.04). Steps:
1. Sanity-check Ubuntu 24.04.
2. `apt-get update && apt-get install -y curl ufw ca-certificates`.
3. Install Docker via the official convenience script.
4. Create `deploy` user, add to `docker` group.
5. Harden `sshd`: `PermitRootLogin no`, `PasswordAuthentication no`.
6. `ufw default deny incoming`, `ufw allow 22,80,443`, `ufw enable`.
7. `mkdir -p /etc/el` (mode 700, `chown deploy:deploy`); `mkdir -p /var/lib/el`.
8. `curl` `docker-compose.yml` and `Caddyfile` from the GitHub raw URL **pinned to a specific commit SHA** (not `main`). Reproducible; intentional friction.
9. `touch /etc/el/.env` (mode 600), `touch /etc/el/compose.env`, `touch /etc/el/compose.env.prev` (so the first deploy's `cp` cannot fail).

After the script, a human pastes secrets into `/etc/el/.env`. No CI step ever writes that file.

### `docs/runbooks/deploy.md`
Covers:
- **Initial provision:** click Hetzner CX22 in Hetzner Cloud Console (nbg1, Ubuntu 24.04), SSH in as root, run the bootstrap script, paste `.env`, set `vars`/`secrets` in GitHub, push to `main`.
- **Day-2 ops:**
  - Logs: `docker compose logs api worker --tail 200 -f`.
  - Manual rollback: `cd /etc/el && mv compose.env.prev compose.env && docker compose --env-file compose.env up -d`.
  - Wipe-and-redeploy: `docker compose down && docker compose --env-file compose.env up -d`.
- **Disaster recovery:** Supabase free-tier snapshots + re-bootstrap of a fresh Hetzner box.
- **Cost monitoring:** alert if Hetzner or Vertex line item exceeds 2× MoM.
- **Domain + LE swap:** procedure to replace `tls internal` with a real Caddy site block once a DNS name exists.
- **Emergency `docker compose kill worker`** to bypass the 24 h grace period when a deploy is urgent.

### Tests
- `tests/test_worker.py` — claim race (two workers, one row), SIGTERM mid-tick (loop exits cleanly), empty queue (no error, just sleeps), pipeline raises (row marked `error`, error_message truncated to 2000 chars).
- `tests/test_healthz.py` — extend SP4 test to cover both 200 and 503 paths; vertex_creds check must not touch the network (mock the SA file).
- `tests/test_verify_env.py` — all required Phase 3 vars present → exit 0; missing one → non-zero exit with the var name in the message.
- `tests/integration/test_sp8_compose_smoke.py` — `@pytest.mark.docker`, opt-in via `DOCKER_AVAILABLE=1` env var. Builds the image, runs `docker compose up -d`, hits `/healthz` through Caddy, tears down. Not part of the default `pytest -q` run.
- `tests/test_dockerfile_lint.py` — string-level assertions: multi-stage present, `USER appuser` appears before `CMD`, no `ADD` directive, no `apt-get install` without `--no-install-recommends`.

Coverage floor remains 93%. No CI coverage gate added.

### SP8 success criteria
1. **First-deploy gate:** on a clean Hetzner box, bootstrap + push to `main` results in `docker compose ps` showing all three services healthy and `curl -k https://<host>/healthz` returning `{"ok": true}`.
2. **End-to-end gate:** submit a niche from the SP4 web UI; the Telegram HIL card arrives; approving it populates a Shopify dev store (proves SP5 path survives containerization).
3. **Rollback gate:** intentionally push a commit that fails healthz (e.g., add a syntax error to `el/web/app.py`); CI builds, deploys, healthz poll fails, rollback fires, the prior `:sha-<short>` tag is restored, and the job exits non-zero. The site stays up the entire time.
4. **Image size:** `docker image ls` reports < 500 MB for the runtime image.
5. **Cold start:** time from `docker compose up -d` to healthz returning 200 is < 10 s on the CX22.
6. **Cost:** monthly Hetzner ≤ €5; combined Vertex + Browserbase ≤ $25.

### Documented out-of-scope failure modes
- Hetzner data-center outage → no automatic failover; manual rebuild on a new box.
- Supabase outage → app surfaces a 503 from /healthz; no fallback datastore.
- GHCR outage → deploys block; current running containers unaffected.
- Cert warning blocks non-technical demos → domain + LE is the documented fix.

## 6. Open questions resolved during brainstorming

| Question | Resolution |
|---|---|
| APScheduler vs plain loop? | Plain loop + `signal.signal(SIGTERM, ...)`. APScheduler is overkill for one 30 s tick. |
| Host-side filelock? | Dropped. DB-level claim + `deploy.replicas: 1` is race-safe without orphaned-lock recovery. |
| `private.run_requests` definition? | Postgres schema on Supabase, created in SP4. |
| Self-signed Caddy — is the browser audience aware? | Yes; documented as testing-only. LE swap is a runbook procedure. |
| `EL_IMAGE_TAG:-latest` default? | Removed. Compose errors loudly if unset; the deploy script always writes both vars. |
| Healthz probe fragility? | /healthz must check db (`SELECT 1`, 2 s timeout) + vertex_creds (token exp, no network). |
| `docker-entrypoint.sh` as pure ceremony? | Given a real job: `python scripts/verify_env.py` before `exec`. |
| Caddy starting before api? | `depends_on: api: condition: service_healthy`. |
| `compose.env.prev` never written? | `cp compose.env compose.env.prev` added before the atomic swap; bootstrap touches the file. |
| 30 s magic sleep before healthz? | Poll loop: 12× 5 s = 60 s ceiling. |
| `GHCR_OWNER` as secret? | Moved to `vars`. Same for `HETZNER_SSH_HOST`. |
| Deploy-vs-running-pipeline conflict? | Worker `stop_grace_period: 86400s` (24 h). Deploys queue via `concurrency: group: deploy`. Emergency override is `docker compose kill worker`. |
