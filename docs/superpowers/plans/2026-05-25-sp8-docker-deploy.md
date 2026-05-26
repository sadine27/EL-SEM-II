# SP8 — Docker + Production Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Containerize the SP4 FastAPI app + a new background worker, ship as a single image to one Hetzner CX22 host via GitHub Actions with healthz-gated rollback.

**Architecture:** One Docker image, two `command:` overrides (api, worker), one Caddy in front for TLS. Worker polls `private.run_requests` with a DB-level claim — single replica makes the race impossible by construction. Deploys are immutable image tags (`:sha-<short>`) with `:latest` re-tagged after the healthz poll passes; failed deploys rollback by restoring the previous `compose.env`.

**Tech Stack:** python:3.12-slim, FastAPI, uvicorn, Caddy 2 (`tls internal`), docker compose v2, GitHub Actions, GHCR, Supabase REST.

**Spec:** [docs/superpowers/specs/2026-05-25-sp8-docker-deploy-design.md](../specs/2026-05-25-sp8-docker-deploy-design.md)

---

## File Structure

**Files to create:**
- `requirements.txt` — runtime deps only (REWRITE; current file has only test deps)
- `requirements-dev.txt` — test & lint deps
- `Dockerfile` — multi-stage, non-root, python:3.12-slim
- `.dockerignore`
- `docker-entrypoint.sh` — runs `scripts/verify_env_runtime.py`, then `exec "$@"`
- `docker-compose.yml` — api, worker, caddy
- `Caddyfile` — `tls internal`, reverse_proxy to `api:8000`
- `el/worker.py` — plain loop + SIGTERM handler; claims via DB
- `scripts/verify_env_runtime.py` — fail-fast env validation (no network)
- `scripts/deploy/hetzner_bootstrap.sh` — idempotent host setup
- `.github/workflows/deploy.yml` — test → build → deploy → healthz-poll → rollback-on-fail
- `docs/runbooks/deploy.md`
- `tests/test_worker.py`
- `tests/test_verify_env_runtime.py`
- `tests/test_dockerfile_lint.py`
- `tests/integration/__init__.py`
- `tests/integration/test_sp8_compose_smoke.py` — opt-in via `DOCKER_AVAILABLE=1`

**Files to modify:**
- `el/web/routes/health.py` — extend `/healthz` to check db + vertex_creds; return 503 on failure
- `el/web/run_service.py` — add `claim_one_queued()` helper for the worker
- `el/web/routes/runs.py:38` — remove `background.add_task(...)`; worker now owns execution
- `el/supabase.py` — extend `update_rows` to accept multi-key filter dict (for the claim)
- `tests/web/test_routes_health.py` — extend with 503 paths
- `tests/web/conftest.py` — extend `FakeDB.update_rows` to honor multi-key filters; add `FakeDB.list_queued()`
- `tests/web/test_routes_runs.py` — remove assertion that background task fires

---

## Implementation Notes

- **TDD discipline:** every code task starts with a failing test. Container/compose/CI files use "write + smoke test + commit" instead (no meaningful unit-test surface).
- **Commit cadence:** one commit per task. Conventional Commits prefix `feat(sp8):` / `test(sp8):` / `docs(sp8):` / `chore(sp8):`.
- **Do not push to remote.** All commits stay local until the user explicitly requests `git push`. The deploy workflow is meaningless until pushed, but the plan stops at "ready to push."
- **Pre-existing `scripts/verify_env.py`** reads `.env.example` for a live integration check. We add a **separate** `scripts/verify_env_runtime.py` that reads `os.environ` for fail-fast container start. Both coexist.
- **Auto memory:** if you learn anything generalizable (e.g., a Supabase REST gotcha), write a memory entry under `memory/`.

---

## Task 1: Split requirements.txt into runtime + dev

**Files:**
- Modify: [requirements.txt](../../../requirements.txt)
- Create: [requirements-dev.txt](../../../requirements-dev.txt)

- [ ] **Step 1: Walk `el/` imports to confirm the runtime set**

Run:
```powershell
Get-ChildItem -Recurse -Filter *.py el/ | Select-String -Pattern '^(import|from)\s+(\w+)' | ForEach-Object { $_.Matches[0].Groups[2].Value } | Sort-Object -Unique
```
Expected: a list including `fastapi`, `pydantic`, `uvicorn` (in `app.py` indirect), `jinja2`, `httpx` or `requests`, `dotenv`, `google` (auth + cloud-aiplatform), `supabase`, `pgvector`, etc. Cross-check against `el/web/app.py`, `el/llm.py`, `el/embeddings.py`, `el/supabase.py`. Sentry is not yet imported anywhere; we add it now because the spec requires error reporting.

- [ ] **Step 2: Overwrite `requirements.txt` with the runtime set**

```text
# Runtime deps only. See requirements-dev.txt for tests/lint.
fastapi==0.115.5
uvicorn[standard]==0.32.1
pydantic==2.9.2
jinja2==3.1.4
python-multipart==0.0.12
httpx==0.27.2
requests==2.32.3
python-dotenv==1.0.1
google-auth==2.35.0
google-cloud-aiplatform==1.71.1
supabase==2.9.1
pgvector==0.3.6
sentry-sdk==2.18.0
cachetools==5.5.2
```

(If `Step 1` surfaces a missing import, add it here; never speculate beyond what `el/` actually uses.)

- [ ] **Step 3: Create `requirements-dev.txt`**

```text
-r requirements.txt

pytest==8.3.3
pytest-cov==7.1.0
coverage==7.13.5
iniconfig==2.3.0
pluggy==1.6.0
packaging==26.2
```

- [ ] **Step 4: Verify the runtime set installs cleanly into a throwaway venv**

```powershell
python -m venv .venv-sp8-check
.\.venv-sp8-check\Scripts\pip.exe install -r requirements.txt
.\.venv-sp8-check\Scripts\python.exe -c "import fastapi, uvicorn, supabase, google.cloud.aiplatform, sentry_sdk; print('ok')"
Remove-Item -Recurse -Force .venv-sp8-check
```
Expected: `ok`.

- [ ] **Step 5: Run the existing test suite with the dev requirements**

```powershell
pip install -r requirements-dev.txt
pytest -q
```
Expected: all pre-SP8 tests still pass.

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt requirements-dev.txt
git commit -m "chore(sp8): split runtime and dev requirements"
```

---

## Task 2: Add `.dockerignore`

**Files:**
- Create: [.dockerignore](../../../.dockerignore)

- [ ] **Step 1: Write the file**

```text
.git/
.venv/
.venv-*/
.pytest_cache/
.vscode/
.claude/
.env
.env.local
.env.*.local
.env.example
tests/
paper/
docs/
legacy/
data/*.json
*.aux
*.log
*.out
main.aux
main.log
main.out
node_modules/
requirements-paper.txt
memory/
.coverage
htmlcov/
.mypy_cache/
.ruff_cache/
__pycache__/
*.pyc
.DS_Store
```

- [ ] **Step 2: Commit**

```powershell
git add .dockerignore
git commit -m "chore(sp8): add .dockerignore"
```

---

## Task 3: Add `scripts/verify_env_runtime.py` (TDD)

**Files:**
- Create: [scripts/verify_env_runtime.py](../../../scripts/verify_env_runtime.py)
- Create: [tests/test_verify_env_runtime.py](../../../tests/test_verify_env_runtime.py)

- [ ] **Step 1: Write the failing test**

Create `tests/test_verify_env_runtime.py`:
```python
"""SP8 — fail-fast env validation used inside the container entrypoint."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_env_runtime.py"

REQUIRED = [
    "WEB_SECRET_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "YOUTUBE_API_KEY",
    "TAVILY_API_KEY",
    "CJ_EMAIL",
    "CJ_API_KEY",
    "BROWSERBASE_API_KEY",
    "TELEGRAM_HIL_BOT_TOKEN",
    "TELEGRAM_HIL_CHAT_ID",
]


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


def _valid_env() -> dict[str, str]:
    sa = json.dumps({
        "type": "service_account",
        "project_id": "p",
        "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n",
        "client_email": "x@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })
    return {k: "x" for k in REQUIRED} | {"GOOGLE_SERVICE_ACCOUNT_JSON": sa}


def test_all_present_exits_zero():
    result = _run(_valid_env())
    assert result.returncode == 0, result.stderr


def test_missing_var_exits_nonzero_and_names_it():
    env = _valid_env()
    del env["WEB_SECRET_KEY"]
    result = _run(env)
    assert result.returncode != 0
    assert "WEB_SECRET_KEY" in (result.stdout + result.stderr)


def test_invalid_sa_json_exits_nonzero():
    env = _valid_env()
    env["GOOGLE_SERVICE_ACCOUNT_JSON"] = "{not json"
    result = _run(env)
    assert result.returncode != 0
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" in (result.stdout + result.stderr)


def test_sa_json_missing_required_field_exits_nonzero():
    env = _valid_env()
    env["GOOGLE_SERVICE_ACCOUNT_JSON"] = json.dumps({"type": "service_account"})
    result = _run(env)
    assert result.returncode != 0
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest tests/test_verify_env_runtime.py -v
```
Expected: 4 errors (script does not exist).

- [ ] **Step 3: Write the script**

Create `scripts/verify_env_runtime.py`:
```python
"""SP8 — fail-fast env validation for the container entrypoint.

Reads from os.environ only (no .env file, no network). Used by
docker-entrypoint.sh to refuse to start the api/worker if anything
required is missing or malformed.

Unlike scripts/verify_env.py (which does live API probes), this is
synchronous, network-free, and safe to run on every container boot.
"""
from __future__ import annotations

import json
import os
import sys

REQUIRED_VARS = (
    "WEB_SECRET_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "YOUTUBE_API_KEY",
    "TAVILY_API_KEY",
    "CJ_EMAIL",
    "CJ_API_KEY",
    "BROWSERBASE_API_KEY",
    "TELEGRAM_HIL_BOT_TOKEN",
    "TELEGRAM_HIL_CHAT_ID",
)

SA_REQUIRED_FIELDS = ("type", "project_id", "private_key", "client_email", "token_uri")


def main() -> int:
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        print(f"[verify_env_runtime] missing required env vars: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    try:
        sa = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[verify_env_runtime] GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {e}",
              file=sys.stderr)
        return 1
    sa_missing = [f for f in SA_REQUIRED_FIELDS if f not in sa]
    if sa_missing:
        print(f"[verify_env_runtime] GOOGLE_SERVICE_ACCOUNT_JSON missing fields: "
              f"{', '.join(sa_missing)}", file=sys.stderr)
        return 1

    print("[verify_env_runtime] ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests and confirm pass**

```powershell
pytest tests/test_verify_env_runtime.py -v
```
Expected: 4 pass.

- [ ] **Step 5: Commit**

```powershell
git add scripts/verify_env_runtime.py tests/test_verify_env_runtime.py
git commit -m "feat(sp8): fail-fast env validator for container entrypoint"
```

---

## Task 4: Extend `el/supabase.py:update_rows` to accept multi-key filters

**Files:**
- Modify: [el/supabase.py](../../../el/supabase.py)
- Modify: [tests/web/conftest.py](../../../tests/web/conftest.py)
- Modify: [tests/test_supabase.py](../../../tests/test_supabase.py)

**Why:** The worker's claim needs `PATCH ?id=eq.<id>&status=eq.queued`. The current `update_rows` accepts a single `id` filter only; the real PostgREST endpoint already supports multi-filter, so this is bringing the helper up to the underlying capability.

- [ ] **Step 1: Read the current `update_rows` signature**

```powershell
Get-Content el/supabase.py | Select-String -Pattern "def update_rows" -Context 0,30
```
Note the current code so the change is additive (no behavior change for existing single-filter callers).

- [ ] **Step 2: Write a failing test in `tests/test_supabase.py`**

Find the existing class-based tests for `update_rows` and add (or append at end of file):
```python
def test_update_rows_passes_all_filters_as_query_params(monkeypatch):
    """Multi-key filters become multiple PostgREST query params."""
    from el.supabase import SupabaseRestProvider

    captured = {}

    class _Resp:
        status_code = 200
        text = "[]"
        def json(self): return []

    def fake_patch(url, headers=None, params=None, json=None, timeout=None):
        captured["params"] = params
        return _Resp()

    monkeypatch.setattr("el.supabase.requests.patch", fake_patch)
    p = SupabaseRestProvider(url="https://x.example", key="k")
    p.update_rows(
        schema="private",
        table="run_requests",
        filters={"id": "eq.abc", "status": "eq.queued"},
        updates={"status": "running"},
    )
    assert captured["params"]["id"] == "eq.abc"
    assert captured["params"]["status"] == "eq.queued"
```

- [ ] **Step 3: Run and confirm failure**

```powershell
pytest tests/test_supabase.py::test_update_rows_passes_all_filters_as_query_params -v
```
Expected: FAIL (current implementation likely passes only `id`, or fails on the extra key).

- [ ] **Step 4: Patch `el/supabase.py:update_rows`**

In the `update_rows` method, replace any line that builds `params={"id": filters["id"]}` (or similar single-key pattern) with `params=dict(filters)`. The function already does PATCH with `Prefer: return=representation`-style headers — that stays. If the current code uses positional indexing, generalize so that every key in `filters` becomes a query param.

- [ ] **Step 5: Run all `tests/test_supabase.py` to confirm no regression**

```powershell
pytest tests/test_supabase.py -v
```
Expected: all pass (including the new one).

- [ ] **Step 6: Update `tests/web/conftest.py:FakeDB.update_rows` to mirror real behavior**

Replace the existing `update_rows` body in `FakeDB` so it requires every filter key to match (not just `id`):
```python
def update_rows(self, *, schema, table, filters, updates):
    def _matches(row):
        for key, raw in filters.items():
            if not raw.startswith("eq."):
                return False
            if str(row.get(key)) != raw[3:]:
                return False
        return True
    matched = [r for r in self.rows.values() if _matches(r)]
    for r in matched:
        r.update(updates)
    return matched
```

Also add a helper used by worker tests:
```python
def list_queued(self):
    return [r for r in self.rows.values() if r.get("status") == "queued"]
```

- [ ] **Step 7: Run the web test suite to confirm no regression**

```powershell
pytest tests/web -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add el/supabase.py tests/test_supabase.py tests/web/conftest.py
git commit -m "feat(sp8): support multi-key filters in supabase.update_rows"
```

---

## Task 5: Add `claim_one_queued()` to `el/web/run_service.py` (TDD)

**Files:**
- Modify: [el/web/run_service.py](../../../el/web/run_service.py)
- Create: a new test in [tests/web/test_run_service.py](../../../tests/web/test_run_service.py) (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_run_service.py`:
```python
def test_claim_one_queued_returns_row_and_marks_running(fake_db):
    from el.web import run_service
    queued = fake_db.insert_rows(
        schema="private", table="run_requests",
        rows=[{"niche": "x", "dislikes": "", "budget_usd": None,
               "submitted_by": "u", "status": "queued"}],
    )[0]
    claimed = run_service.claim_one_queued(
        worker_id="worker-1", db_provider=fake_db,
    )
    assert claimed is not None
    assert claimed["id"] == queued["id"]
    assert fake_db.rows[queued["id"]]["status"] == "running"
    assert fake_db.rows[queued["id"]]["claimed_by"] == "worker-1"


def test_claim_one_queued_returns_none_when_empty(fake_db):
    from el.web import run_service
    assert run_service.claim_one_queued(worker_id="w", db_provider=fake_db) is None


def test_claim_one_queued_skips_already_running(fake_db):
    from el.web import run_service
    fake_db.insert_rows(
        schema="private", table="run_requests",
        rows=[{"niche": "x", "dislikes": "", "budget_usd": None,
               "submitted_by": "u", "status": "running"}],
    )
    assert run_service.claim_one_queued(worker_id="w", db_provider=fake_db) is None


def test_claim_one_queued_loser_in_race_returns_none(fake_db):
    """Two workers, one row: only the first claim wins."""
    from el.web import run_service
    row = fake_db.insert_rows(
        schema="private", table="run_requests",
        rows=[{"niche": "x", "dislikes": "", "budget_usd": None,
               "submitted_by": "u", "status": "queued"}],
    )[0]
    first = run_service.claim_one_queued(worker_id="w1", db_provider=fake_db)
    second = run_service.claim_one_queued(worker_id="w2", db_provider=fake_db)
    assert first is not None and first["id"] == row["id"]
    assert second is None
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest tests/web/test_run_service.py -v -k claim_one_queued
```
Expected: 4 errors (no `claim_one_queued` defined).

- [ ] **Step 3: Implement `claim_one_queued` in `el/web/run_service.py`**

Append to the file:
```python
def claim_one_queued(*, worker_id: str, db_provider) -> dict | None:
    """Atomic claim of the oldest queued run.

    Two-step (find oldest queued -> conditional update with status=queued
    guard) so concurrent workers cannot both win the same row. With
    deploy.replicas=1 this is also a defense-in-depth measure.
    """
    candidates = db_provider.select_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"status": "eq.queued"},
        limit=1,
    )
    if not candidates:
        return None
    row_id = candidates[0]["id"]
    claimed = db_provider.update_rows(
        schema=RUN_REQUESTS_SCHEMA,
        table=RUN_REQUESTS_TABLE,
        filters={"id": f"eq.{row_id}", "status": "eq.queued"},
        updates={
            "status": "running",
            "claimed_by": worker_id,
            "started_at": _now_iso(),
        },
    )
    return claimed[0] if claimed else None
```

- [ ] **Step 4: Update the `select_rows` contract**

The current `select_rows` only handles an `id` filter. Open `tests/web/conftest.py` and extend `FakeDB.select_rows` to honor a `status` filter as well:
```python
def select_rows(self, *, schema, table, filters, select="*", limit=None):
    def _matches(row):
        for key, raw in filters.items():
            if not raw.startswith("eq."):
                return False
            if str(row.get(key)) != raw[3:]:
                return False
        return True
    matched = [r for r in self.rows.values() if _matches(r)]
    if limit is not None:
        matched = matched[:limit]
    return matched
```

The real `el/supabase.py:select_rows` already passes filters through as PostgREST query params; if it does not, update it now to mirror the multi-filter pattern from Task 4. Run:
```powershell
pytest tests/test_supabase.py -v
```
Expected: all pass.

- [ ] **Step 5: Run claim tests and confirm pass**

```powershell
pytest tests/web/test_run_service.py -v -k claim_one_queued
```
Expected: 4 pass.

- [ ] **Step 6: Commit**

```powershell
git add el/web/run_service.py tests/web/test_run_service.py tests/web/conftest.py el/supabase.py
git commit -m "feat(sp8): add claim_one_queued for the SP8 worker"
```

---

## Task 6: Remove in-process BackgroundTasks from runs route (TDD)

**Files:**
- Modify: [el/web/routes/runs.py](../../../el/web/routes/runs.py)
- Modify: [tests/web/test_routes_runs.py](../../../tests/web/test_routes_runs.py)

**Why:** SP8 introduces a separate worker container. If the route also fires `background.add_task`, the in-process run and the worker race on the same row. Worker is now the only executor.

- [ ] **Step 1: Read the current test to understand what asserts on the background task**

```powershell
Get-Content tests/web/test_routes_runs.py
```

- [ ] **Step 2: Update the test to assert the row is queued AND no in-process run fires**

Modify the test that currently checks `background.add_task` was invoked. Replace its assertions with:
```python
def test_submit_run_queues_row_without_running_pipeline(client, fake_db, auth_headers):
    """SP8: the route only inserts a queued row. The worker container picks it up."""
    r = client.post(
        "/api/runs",
        json={"niche": "candles", "dislikes": "", "budget_usd": 50},
        headers=auth_headers,
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    # The row exists in the queue.
    assert fake_db.rows[body["request_id"]]["status"] == "queued"
    # No in-process execution: status must NOT have advanced to running/done/error.
    assert fake_db.rows[body["request_id"]]["status"] == "queued"
```

If a test exists that asserts a background task was registered (e.g., uses a spy on `BackgroundTasks.add_task`), delete it.

- [ ] **Step 3: Run and confirm the test fails**

```powershell
pytest tests/web/test_routes_runs.py -v -k submit_run_queues_row_without
```
Expected: FAIL if the route still calls `add_task` (the row might transition out of `queued` synchronously in some test setups, or — more likely — pass already if `_run_pipeline_safe` is async-only. Either way, run it.)

- [ ] **Step 4: Patch `el/web/routes/runs.py`**

Edit [el/web/routes/runs.py:22-39](../../../el/web/routes/runs.py#L22-L39). Remove the `BackgroundTasks` param and the `background.add_task(...)` line. Result:
```python
@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_run(
    body: RunSubmitBody,
    request: Request,
    principal: str = Depends(get_principal),
    settings=Depends(get_settings),
):
    row = run_service.submit_run(
        niche=body.niche,
        dislikes=body.dislikes,
        budget_usd=body.budget_usd,
        principal=principal,
        db_provider=settings.db_provider,
    )
    return {"request_id": row["id"], "status": row["status"]}
```

Also drop the now-unused `BackgroundTasks` import and the `_run_pipeline_safe` helper at the bottom (lines 57-65). If `_run_pipeline_safe` is referenced elsewhere, leave it; otherwise delete.

- [ ] **Step 5: Run all runs-route tests**

```powershell
pytest tests/web/test_routes_runs.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```powershell
git add el/web/routes/runs.py tests/web/test_routes_runs.py
git commit -m "feat(sp8): runs route only enqueues; worker container executes"
```

---

## Task 7: Extend `/healthz` to check db + vertex_creds (TDD)

**Files:**
- Modify: [el/web/routes/health.py](../../../el/web/routes/health.py)
- Modify: [tests/web/test_routes_health.py](../../../tests/web/test_routes_health.py)
- Modify: [el/web/settings.py](../../../el/web/settings.py) — expose `google_service_account_json` on Settings so the health route can read it without going through `os.environ` directly (testability)

- [ ] **Step 1: Extend `Settings` with a `google_service_account_json` field**

In [el/web/settings.py](../../../el/web/settings.py), add to the dataclass:
```python
    google_service_account_json: str | None = None
```
And in `from_env()`:
```python
    google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"),
```

- [ ] **Step 2: Write the failing tests**

Replace the contents of [tests/web/test_routes_health.py](../../../tests/web/test_routes_health.py):
```python
"""SP4 + SP8 — /healthz route."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from el import embeddings
from el.web.app import create_app
from el.web.settings import Settings


def _settings(*, db_provider, sa_json=None):
    return Settings(
        web_secret_key="testsecret",
        rate_limit_per_minute=100,
        chat_top_k=3,
        embedding_provider=embeddings.FakeEmbeddingProvider(),
        db_provider=db_provider,
        google_service_account_json=sa_json,
        enabled=True,
    )


def _valid_sa() -> str:
    return json.dumps({
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    })


class _DBOk:
    def ping(self): return True
    def insert_rows(self, **kw): return []
    def select_rows(self, **kw): return []
    def update_rows(self, **kw): return []


class _DBDown:
    def ping(self):
        raise TimeoutError("connection timed out")
    def insert_rows(self, **kw): return []
    def select_rows(self, **kw): return []
    def update_rows(self, **kw): return []


def test_healthz_ok_when_db_and_creds_ok():
    s = _settings(db_provider=_DBOk(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["vertex_creds"] == "ok"


def test_healthz_503_when_db_fails():
    s = _settings(db_provider=_DBDown(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    body = r.json()
    assert body["ok"] is False
    assert body["checks"]["db"].startswith("error:")
    assert body["checks"]["vertex_creds"] == "ok"


def test_healthz_503_when_sa_missing():
    s = _settings(db_provider=_DBOk(), sa_json=None)
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["checks"]["vertex_creds"].startswith("error:")


def test_healthz_503_when_sa_invalid_json():
    s = _settings(db_provider=_DBOk(), sa_json="{not json")
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 503
    assert r.json()["checks"]["vertex_creds"].startswith("error:")


def test_healthz_no_network_for_vertex_check(monkeypatch):
    """The check must not make outbound network calls."""
    def _boom(*a, **kw):
        raise AssertionError("network call attempted in healthz")
    monkeypatch.setattr("requests.get", _boom)
    monkeypatch.setattr("requests.post", _boom)
    s = _settings(db_provider=_DBOk(), sa_json=_valid_sa())
    c = TestClient(create_app(settings=s))
    r = c.get("/healthz")
    assert r.status_code == 200
```

- [ ] **Step 3: Run and confirm failure**

```powershell
pytest tests/web/test_routes_health.py -v
```
Expected: 5 failures.

- [ ] **Step 4: Rewrite `el/web/routes/health.py`**

Replace the file:
```python
"""SP4 + SP8 — /healthz: liveness + dependency check."""
from __future__ import annotations

import json
import os
import subprocess

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_SA_REQUIRED_FIELDS = ("type", "project_id", "private_key", "client_email", "token_uri")


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__),
            stderr=subprocess.DEVNULL,
            timeout=1,
        )
        return out.decode().strip() or "unknown"
    except Exception:
        return "unknown"


def _check_db(db_provider) -> str:
    """Pure check: call db_provider.ping() if available, else select_rows.
    Returns 'ok' or 'error: <message>'. No network call beyond what the
    provider does; provider is expected to enforce its own timeout."""
    try:
        if hasattr(db_provider, "ping"):
            db_provider.ping()
        else:
            db_provider.select_rows(
                schema="private", table="run_requests",
                filters={"id": "eq.__healthz__"}, limit=1,
            )
        return "ok"
    except Exception as e:
        return f"error: {type(e).__name__}: {e}"


def _check_vertex_creds(sa_json: str | None) -> str:
    """Parse the SA JSON; verify required fields. No network."""
    if not sa_json:
        return "error: GOOGLE_SERVICE_ACCOUNT_JSON missing"
    try:
        sa = json.loads(sa_json)
    except json.JSONDecodeError as e:
        return f"error: invalid JSON: {e}"
    missing = [f for f in _SA_REQUIRED_FIELDS if f not in sa]
    if missing:
        return f"error: SA missing fields: {','.join(missing)}"
    return "ok"


@router.get("/healthz")
def healthz(request: Request):
    settings = request.app.state.settings
    checks = {
        "db": _check_db(settings.db_provider),
        "vertex_creds": _check_vertex_creds(settings.google_service_account_json),
    }
    ok = all(v == "ok" for v in checks.values())
    body = {"ok": ok, "version": _git_sha(), "checks": checks}
    return JSONResponse(status_code=200 if ok else 503, content=body)
```

- [ ] **Step 5: Run tests and confirm pass**

```powershell
pytest tests/web/test_routes_health.py -v
```
Expected: 5 pass.

- [ ] **Step 6: Add a `ping()` method to `SupabaseRestProvider` for the real db check**

In [el/supabase.py](../../../el/supabase.py), add to the class:
```python
def ping(self) -> None:
    """Healthcheck: GET against the REST root with a 2s timeout."""
    r = requests.get(
        urljoin(self.url, "rest/v1/"),
        headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"},
        timeout=2,
    )
    if r.status_code >= 500:
        raise RuntimeError(f"supabase /rest/v1 returned {r.status_code}")
```

- [ ] **Step 7: Run the supabase tests to confirm nothing else regressed**

```powershell
pytest tests/test_supabase.py tests/web/test_routes_health.py -v
```
Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add el/web/routes/health.py el/web/settings.py el/supabase.py tests/web/test_routes_health.py
git commit -m "feat(sp8): /healthz checks db + vertex_creds, returns 503 on failure"
```

---

## Task 8: Implement `el/worker.py` (TDD)

**Files:**
- Create: [el/worker.py](../../../el/worker.py)
- Create: [tests/test_worker.py](../../../tests/test_worker.py)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worker.py`:
```python
"""SP8 — background worker that drains private.run_requests."""
from __future__ import annotations

import threading
import time

import pytest

from tests.web.conftest import FakeDB


class _Pipeline:
    def __init__(self, *, raise_for=None):
        self.calls = []
        self.raise_for = raise_for or set()
    def __call__(self, request_id, *, db_provider):
        self.calls.append(request_id)
        if request_id in self.raise_for:
            raise RuntimeError(f"forced failure for {request_id}")


def _seed_queued(db, n):
    return db.insert_rows(
        schema="private", table="run_requests",
        rows=[{"niche": f"n{i}", "dislikes": "", "budget_usd": None,
               "submitted_by": "u", "status": "queued"} for i in range(n)],
    )


def test_tick_claims_oldest_queued_and_runs_pipeline():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    pipeline = _Pipeline()
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    assert pipeline.calls == [rows[0]["id"]]
    assert db.rows[rows[0]["id"]]["status"] == "done"


def test_tick_empty_queue_is_noop():
    from el.worker import tick
    db = FakeDB()
    pipeline = _Pipeline()
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    assert pipeline.calls == []


def test_tick_marks_error_on_pipeline_exception():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    pipeline = _Pipeline(raise_for={rows[0]["id"]})
    tick(db_provider=db, worker_id="w", run_pipeline=pipeline)
    row = db.rows[rows[0]["id"]]
    assert row["status"] == "error"
    assert "forced failure" in row["error_message"]


def test_tick_truncates_long_error_message():
    from el.worker import tick
    db = FakeDB()
    rows = _seed_queued(db, 1)
    long_msg = "x" * 5000
    def boom(rid, **kw): raise RuntimeError(long_msg)
    tick(db_provider=db, worker_id="w", run_pipeline=boom)
    assert len(db.rows[rows[0]["id"]]["error_message"]) <= 2000


def test_claim_race_two_workers_one_row():
    """Sequential claim attempts: second sees nothing because first won."""
    from el.web import run_service
    db = FakeDB()
    _seed_queued(db, 1)
    a = run_service.claim_one_queued(worker_id="A", db_provider=db)
    b = run_service.claim_one_queued(worker_id="B", db_provider=db)
    assert a is not None
    assert b is None


def test_run_loop_exits_on_stop_event():
    """SIGTERM/SIGINT sets the event; loop returns within one tick."""
    from el.worker import run_loop
    db = FakeDB()
    pipeline = _Pipeline()
    stop = threading.Event()
    t = threading.Thread(
        target=run_loop,
        kwargs={"db_provider": db, "worker_id": "w",
                "run_pipeline": pipeline, "stop": stop, "poll_seconds": 0.05},
    )
    t.start()
    time.sleep(0.15)
    stop.set()
    t.join(timeout=1.0)
    assert not t.is_alive(), "worker did not exit after stop.set()"
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest tests/test_worker.py -v
```
Expected: 6 errors (module does not exist).

- [ ] **Step 3: Implement `el/worker.py`**

```python
"""SP8 — background worker.

Drains the private.run_requests queue. One row per tick, then sleeps.
SIGTERM/SIGINT set an event that ends the loop after the current tick.
Single replica in compose makes the claim race-free by configuration;
the conditional UPDATE is defense in depth.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
from typing import Callable

from el.web import run_service

log = logging.getLogger("el.worker")

_ERROR_MESSAGE_MAX_LEN = 2000
_POLL_SECONDS = float(os.environ.get("EL_WORKER_POLL_SECONDS", "30"))


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _default_pipeline(request_id: str, *, db_provider) -> None:
    from el.pipeline import run_for_request
    run_for_request(request_id, db_provider=db_provider)


def tick(*, db_provider, worker_id: str, run_pipeline: Callable) -> None:
    """One unit of work. Returns immediately if queue is empty."""
    claimed = run_service.claim_one_queued(worker_id=worker_id, db_provider=db_provider)
    if claimed is None:
        return
    request_id = claimed["id"]
    try:
        run_pipeline(request_id, db_provider=db_provider)
    except Exception as e:
        log.exception("pipeline failed for %s", request_id)
        run_service.mark_error(
            request_id=request_id,
            error_message=str(e)[:_ERROR_MESSAGE_MAX_LEN],
            db_provider=db_provider,
        )
        return
    run_service.mark_done(request_id=request_id, db_provider=db_provider)


def run_loop(
    *,
    db_provider,
    worker_id: str,
    run_pipeline: Callable,
    stop: threading.Event,
    poll_seconds: float = _POLL_SECONDS,
) -> None:
    log.info("worker %s starting (poll=%ss)", worker_id, poll_seconds)
    while not stop.is_set():
        try:
            tick(db_provider=db_provider, worker_id=worker_id, run_pipeline=run_pipeline)
        except Exception:
            log.exception("worker tick failed (continuing)")
        stop.wait(poll_seconds)
    log.info("worker %s stopped", worker_id)


def main() -> int:
    from el.supabase import SupabaseRestProvider
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run_loop(
        db_provider=SupabaseRestProvider(),
        worker_id=_default_worker_id(),
        run_pipeline=_default_pipeline,
        stop=stop,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and confirm pass**

```powershell
pytest tests/test_worker.py -v
```
Expected: 6 pass.

- [ ] **Step 5: Smoke-import via `python -m el.worker` (will block on connecting; just exercise the import)**

```powershell
python -c "import el.worker; print(el.worker.tick.__doc__)"
```
Expected: prints the docstring. No ImportError.

- [ ] **Step 6: Commit**

```powershell
git add el/worker.py tests/test_worker.py
git commit -m "feat(sp8): background worker that drains run_requests"
```

---

## Task 9: Write Dockerfile + lint test (TDD-lite)

**Files:**
- Create: [Dockerfile](../../../Dockerfile)
- Create: [docker-entrypoint.sh](../../../docker-entrypoint.sh)
- Create: [tests/test_dockerfile_lint.py](../../../tests/test_dockerfile_lint.py)

- [ ] **Step 1: Write the failing lint test**

```python
"""SP8 — string-level invariants for the Dockerfile."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DF = ROOT / "Dockerfile"
ENTRY = ROOT / "docker-entrypoint.sh"


def _contents() -> str:
    return DF.read_text(encoding="utf-8")


def test_dockerfile_exists():
    assert DF.exists()


def test_multi_stage_build():
    text = _contents()
    assert text.count("FROM ") >= 2, "Dockerfile must be multi-stage"
    assert "AS builder" in text or "as builder" in text


def test_base_image_pinned_to_python_312_slim():
    assert "python:3.12-slim" in _contents()


def test_runs_as_non_root_before_cmd():
    text = _contents()
    user_idx = text.lower().rfind("\nuser ")
    cmd_idx = text.lower().rfind("\ncmd ")
    assert user_idx > -1, "no USER directive"
    assert cmd_idx > -1, "no CMD directive"
    assert user_idx < cmd_idx, "USER must precede CMD"
    assert "appuser" in text


def test_no_add_directive():
    text = _contents()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.lower().startswith("add "), f"forbidden ADD: {line!r}"


def test_apt_install_uses_no_install_recommends():
    text = _contents()
    for i, line in enumerate(text.splitlines()):
        if "apt-get install" in line and "--no-install-recommends" not in line:
            # allow multi-line continuations: search next 3 lines
            tail = " ".join(text.splitlines()[i:i + 4])
            assert "--no-install-recommends" in tail, f"apt-get install without --no-install-recommends: {line!r}"


def test_entrypoint_script_exists_and_execs_verify_env():
    assert ENTRY.exists()
    body = ENTRY.read_text(encoding="utf-8")
    assert "verify_env_runtime.py" in body
    assert 'exec "$@"' in body
```

- [ ] **Step 2: Run and confirm failure**

```powershell
pytest tests/test_dockerfile_lint.py -v
```
Expected: all fail (no Dockerfile yet).

- [ ] **Step 3: Write `Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        build-essential \
        gcc \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements.txt ./
RUN pip install --prefix=/install/deps -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/install/deps/bin:$PATH

RUN apt-get update \
 && apt-get install --no-install-recommends -y \
        curl \
        ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 appuser \
 && useradd  --system --uid 10001 --gid 10001 --home /app --shell /usr/sbin/nologin appuser

COPY --from=builder /install/deps /install/deps

WORKDIR /app
COPY el ./el
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "el.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: Write `docker-entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/verify_env_runtime.py

exec "$@"
```

- [ ] **Step 5: Run lint tests**

```powershell
pytest tests/test_dockerfile_lint.py -v
```
Expected: 7 pass.

- [ ] **Step 6: Build the image locally to confirm it actually builds**

```powershell
docker build -t el:sp8-local .
```
Expected: build succeeds; resulting image < 500 MB:
```powershell
docker image inspect el:sp8-local --format "{{.Size}}"
```
Expected: value < 524288000 (500 MB in bytes).

- [ ] **Step 7: Confirm the image runs and entrypoint refuses missing env**

```powershell
docker run --rm el:sp8-local
```
Expected: exits non-zero with `missing required env vars`.

- [ ] **Step 8: Commit**

```powershell
git add Dockerfile docker-entrypoint.sh tests/test_dockerfile_lint.py
git commit -m "feat(sp8): multi-stage Dockerfile + entrypoint env validation"
```

---

## Task 10: Write Caddyfile + docker-compose.yml

**Files:**
- Create: [Caddyfile](../../../Caddyfile)
- Create: [docker-compose.yml](../../../docker-compose.yml)

- [ ] **Step 1: Write `Caddyfile`**

```text
{
    email admin@example.invalid
    auto_https disable_redirects
}

:443 {
    tls internal
    reverse_proxy api:8000
}

:80 {
    redir https://{host}{uri}
}
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  api:
    image: ghcr.io/${GHCR_OWNER}/el:${EL_IMAGE_TAG}
    env_file: /etc/el/.env
    volumes:
      - el-data:/app/data
    command: ["uvicorn", "el.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
    restart: unless-stopped
    stop_grace_period: 30s
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  worker:
    image: ghcr.io/${GHCR_OWNER}/el:${EL_IMAGE_TAG}
    env_file: /etc/el/.env
    volumes:
      - el-data:/app/data
    command: ["python", "-m", "el.worker"]
    restart: unless-stopped
    stop_grace_period: 86400s
    deploy:
      replicas: 1

  caddy:
    image: caddy:2-alpine
    ports:
      - "80:80"
      - "443:443"
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

- [ ] **Step 3: Validate compose syntax**

```powershell
docker compose -f docker-compose.yml config --quiet
```
Expected: silent exit 0. If it complains about missing env vars (`GHCR_OWNER`, `EL_IMAGE_TAG`), that is correct behavior — the compose file must error loudly when those are unset. Pass them inline to validate:
```powershell
$env:GHCR_OWNER="test"; $env:EL_IMAGE_TAG="sha-deadbee"; docker compose -f docker-compose.yml config --quiet
```
Expected: silent exit 0.

- [ ] **Step 4: Commit**

```powershell
git add Caddyfile docker-compose.yml
git commit -m "feat(sp8): docker-compose stack (api + worker + caddy)"
```

---

## Task 11: Integration smoke test for the compose stack (opt-in)

**Files:**
- Create: [tests/integration/__init__.py](../../../tests/integration/__init__.py) (empty)
- Create: [tests/integration/test_sp8_compose_smoke.py](../../../tests/integration/test_sp8_compose_smoke.py)

- [ ] **Step 1: Create the empty `__init__.py`**

```powershell
New-Item -ItemType File tests\integration\__init__.py
```

- [ ] **Step 2: Write the test (opt-in marker)**

```python
"""SP8 — full compose-stack smoke test. Opt-in via DOCKER_AVAILABLE=1.

Not part of the default pytest run because it builds an image and starts
containers. CI runs the default suite; this is for local verification.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
import urllib.error

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("DOCKER_AVAILABLE") != "1",
        reason="set DOCKER_AVAILABLE=1 to run docker smoke tests",
    ),
]


def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def _wait_for_healthz(url: str, timeout_s: int = 60) -> dict:
    deadline = time.monotonic() + timeout_s
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return {"status": r.status, "body": json.loads(r.read().decode())}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_exc = e
            time.sleep(2)
    raise AssertionError(f"healthz never came up: {last_exc}")


def test_compose_brings_api_up_and_healthz_green(tmp_path, monkeypatch):
    """Build image, run api + worker, hit healthz directly (bypass caddy)."""
    _run(["docker", "build", "-t", "el:sp8-smoke", "."])
    env_file = tmp_path / "smoke.env"
    env_file.write_text("\n".join([
        "WEB_SECRET_KEY=smoke",
        "SUPABASE_URL=https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY=smoke",
        f"GOOGLE_SERVICE_ACCOUNT_JSON={json.dumps(_valid_sa())}",
        "YOUTUBE_API_KEY=smoke",
        "TAVILY_API_KEY=smoke",
        "CJ_EMAIL=smoke",
        "CJ_API_KEY=smoke",
        "BROWSERBASE_API_KEY=smoke",
        "TELEGRAM_HIL_BOT_TOKEN=smoke",
        "TELEGRAM_HIL_CHAT_ID=smoke",
    ]))
    cid = _run([
        "docker", "run", "-d", "--rm",
        "--name", "el-sp8-smoke",
        "-p", "18000:8000",
        "--env-file", str(env_file),
        "el:sp8-smoke",
    ]).stdout.strip()
    try:
        # /healthz returns 503 because the fake Supabase URL is unreachable,
        # but the *process* came up — that's what the smoke proves.
        result = _wait_for_healthz("http://localhost:18000/healthz", timeout_s=30)
        assert result["status"] in (200, 503)
        assert "checks" in result["body"]
    finally:
        subprocess.run(["docker", "rm", "-f", "el-sp8-smoke"], capture_output=True)


def _valid_sa() -> dict:
    return {
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
```

- [ ] **Step 3: Register the marker in `pytest.ini` / `pyproject.toml`**

Search for an existing `[tool.pytest.ini_options]` block:
```powershell
Get-ChildItem pytest.ini, pyproject.toml -ErrorAction SilentlyContinue | ForEach-Object { Get-Content $_ }
```
If `markers = [...]` exists, append `"docker: SP8 docker smoke tests (opt-in via DOCKER_AVAILABLE=1)"`. If neither file declares markers, add to `pyproject.toml` (or create `pytest.ini`):
```ini
[pytest]
markers =
    docker: SP8 docker smoke tests (opt-in via DOCKER_AVAILABLE=1)
```

- [ ] **Step 4: Run with the env var unset (should skip cleanly)**

```powershell
pytest tests/integration -v
```
Expected: 1 skipped (DOCKER_AVAILABLE not set).

- [ ] **Step 5: Run with the env var set (requires Docker Desktop)**

```powershell
$env:DOCKER_AVAILABLE="1"; pytest tests/integration -v
```
Expected: 1 pass. Tear-down leaves no `el-sp8-smoke` container.

- [ ] **Step 6: Commit**

```powershell
git add tests/integration/__init__.py tests/integration/test_sp8_compose_smoke.py
# also add pytest.ini / pyproject.toml if you edited it
git commit -m "test(sp8): opt-in compose smoke test"
```

---

## Task 12: GitHub Actions — test job

**Files:**
- Create: [.github/workflows/deploy.yml](../../../.github/workflows/deploy.yml)

- [ ] **Step 1: Create the workflow file with the test job only**

```yaml
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch: {}

concurrency:
  group: deploy
  cancel-in-progress: false

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: |
            requirements.txt
            requirements-dev.txt
      - run: pip install -r requirements-dev.txt
      - run: pytest -q
```

- [ ] **Step 2: Validate the YAML parses**

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit (do not push yet)**

```powershell
git add .github/workflows/deploy.yml
git commit -m "ci(sp8): test job for deploy workflow"
```

---

## Task 13: GitHub Actions — build & push image to GHCR

**Files:**
- Modify: [.github/workflows/deploy.yml](../../../.github/workflows/deploy.yml)

- [ ] **Step 1: Append the build job**

Add after the `test` job in `.github/workflows/deploy.yml`:
```yaml
  build:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      image_tag: ${{ steps.tag.outputs.value }}
      image_short: ${{ steps.tag.outputs.short }}
    steps:
      - uses: actions/checkout@v4
      - id: tag
        shell: bash
        run: |
          short="${GITHUB_SHA::7}"
          echo "value=sha-${short}" >> "$GITHUB_OUTPUT"
          echo "short=${short}" >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ghcr.io/${{ vars.GHCR_OWNER }}/el:${{ steps.tag.outputs.value }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Validate YAML**

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```powershell
git add .github/workflows/deploy.yml
git commit -m "ci(sp8): build and push image to GHCR on main"
```

---

## Task 14: GitHub Actions — deploy with healthz-gated rollback

**Files:**
- Modify: [.github/workflows/deploy.yml](../../../.github/workflows/deploy.yml)

- [ ] **Step 1: Append the deploy job**

Add after the `build` job:
```yaml
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Push new tag to host and roll forward
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ vars.HETZNER_SSH_HOST }}
          username: ${{ secrets.HETZNER_SSH_USER }}
          key: ${{ secrets.HETZNER_SSH_KEY }}
          script: |
            set -euo pipefail
            cd /etc/el
            cp compose.env compose.env.prev
            cat > compose.env.new <<EOF
            EL_IMAGE_TAG=${{ needs.build.outputs.image_tag }}
            GHCR_OWNER=${{ vars.GHCR_OWNER }}
            EOF
            mv compose.env.new compose.env
            docker compose --env-file compose.env pull
            docker compose --env-file compose.env up -d
      - name: Poll healthz (60s ceiling)
        id: healthz
        shell: bash
        run: |
          set -u
          for i in $(seq 1 12); do
            if curl -fsS -k --max-time 5 "https://${{ vars.HETZNER_SSH_HOST }}/healthz" \
                 | tee /tmp/healthz.json \
                 | python -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)"; then
              echo "healthz green on attempt $i"
              exit 0
            fi
            echo "attempt $i: not yet"
            sleep 5
          done
          echo "::error::healthz never returned ok=true within 60s"
          exit 1
      - name: Re-tag image as :latest (only when healthz green)
        if: success()
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ghcr.io/${{ vars.GHCR_OWNER }}/el:latest
          cache-from: type=gha
      - name: Rollback on failure
        if: failure()
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ vars.HETZNER_SSH_HOST }}
          username: ${{ secrets.HETZNER_SSH_USER }}
          key: ${{ secrets.HETZNER_SSH_KEY }}
          script: |
            set -euo pipefail
            cd /etc/el
            if [ -s compose.env.prev ]; then
              mv compose.env.prev compose.env
              docker compose --env-file compose.env pull
              docker compose --env-file compose.env up -d
              echo "rolled back to previous tag"
            else
              echo "no compose.env.prev — cannot rollback"
              exit 1
            fi
      - name: Fail loudly if rollback fired
        if: failure()
        run: |
          echo "::error::Deploy failed; rollback executed. Investigate the new tag."
          exit 1
```

- [ ] **Step 2: Validate YAML**

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml')); print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```powershell
git add .github/workflows/deploy.yml
git commit -m "ci(sp8): deploy with healthz poll and automatic rollback"
```

---

## Task 15: Hetzner bootstrap script

**Files:**
- Create: [scripts/deploy/hetzner_bootstrap.sh](../../../scripts/deploy/hetzner_bootstrap.sh)

- [ ] **Step 1: Determine the pin SHA**

The bootstrap fetches `docker-compose.yml` and `Caddyfile` from GitHub raw at a **specific commit**. Before writing the script, decide:
```powershell
git log -1 --format=%H
```
Use the SHA from the commit that lands the compose+Caddyfile (Task 10's commit). After this plan is fully implemented you will need to update the SHA placeholder in the script to the actual commit hash — note this in the runbook.

- [ ] **Step 2: Write the script**

```bash
#!/usr/bin/env bash
# SP8 — idempotent provisioner for a fresh Hetzner CX22 (Ubuntu 24.04).
# Run as root on a freshly-imaged box.
set -euo pipefail

REPO="${REPO:-sadine27/EL---II-SEM}"
PIN_SHA="${PIN_SHA:-REPLACE_WITH_COMMIT_SHA_AFTER_PUSH}"
DEPLOY_USER="${DEPLOY_USER:-deploy}"

log() { printf '\n=== %s ===\n' "$*"; }

log "1/9 Verify Ubuntu 24.04"
. /etc/os-release
[ "$ID" = "ubuntu" ] && [ "$VERSION_ID" = "24.04" ] \
    || { echo "Expected Ubuntu 24.04, got $ID $VERSION_ID"; exit 1; }

log "2/9 apt update + base packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl ufw ca-certificates gnupg

log "3/9 Install Docker (official convenience script)"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi

log "4/9 Create ${DEPLOY_USER} user and add to docker group"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG docker "${DEPLOY_USER}"
mkdir -p "/home/${DEPLOY_USER}/.ssh"
chmod 700 "/home/${DEPLOY_USER}/.ssh"
chown -R "${DEPLOY_USER}:${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
echo "Paste the deploy SSH public key into /home/${DEPLOY_USER}/.ssh/authorized_keys (mode 600) before continuing."

log "5/9 Harden sshd"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl reload ssh

log "6/9 Configure firewall"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

log "7/9 Create /etc/el and /var/lib/el"
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /etc/el
install -d -m 755 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /var/lib/el

log "8/9 Fetch docker-compose.yml + Caddyfile at pinned SHA"
RAW="https://raw.githubusercontent.com/${REPO}/${PIN_SHA}"
curl -fsSL "${RAW}/docker-compose.yml" -o /etc/el/docker-compose.yml
curl -fsSL "${RAW}/Caddyfile" -o /etc/el/Caddyfile
chown "${DEPLOY_USER}:${DEPLOY_USER}" /etc/el/docker-compose.yml /etc/el/Caddyfile

log "9/9 Touch .env, compose.env, compose.env.prev (so first deploy cp doesn't fail)"
install -m 600 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/.env
install -m 644 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/compose.env
install -m 644 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" /dev/null /etc/el/compose.env.prev

echo
echo "Bootstrap complete. Next steps:"
echo "  1. Paste deploy SSH public key into /home/${DEPLOY_USER}/.ssh/authorized_keys"
echo "  2. Paste production secrets into /etc/el/.env"
echo "  3. Set vars/secrets in GitHub repo settings"
echo "  4. Push to main"
```

- [ ] **Step 3: Shellcheck the script (optional but recommended)**

```powershell
docker run --rm -v "${PWD}:/mnt" koalaman/shellcheck:stable /mnt/scripts/deploy/hetzner_bootstrap.sh
```
Expected: no SC errors (warnings about `local` and `[[` patterns OK). If shellcheck unavailable, skip.

- [ ] **Step 4: Mark executable and commit**

```powershell
git add scripts/deploy/hetzner_bootstrap.sh
git update-index --chmod=+x scripts/deploy/hetzner_bootstrap.sh
git commit -m "feat(sp8): Hetzner CX22 bootstrap script"
```

---

## Task 16: Deploy runbook

**Files:**
- Create: [docs/runbooks/deploy.md](../../../docs/runbooks/deploy.md)

- [ ] **Step 1: Verify the directory exists or create it**

```powershell
New-Item -ItemType Directory -Force docs\runbooks | Out-Null
```

- [ ] **Step 2: Write the runbook**

```markdown
# SP8 — Production deploy runbook

Single Hetzner CX22, Docker Compose, Caddy with self-signed TLS, GitHub Actions
auto-deploy on push to `main`.

## Initial provision (one-time)

1. **Spin up the box.** Hetzner Cloud Console → New Server → CX22, Ubuntu 24.04,
   nbg1, your SSH key. Cost: ~€3.79/mo.
2. **SSH in as root**, run the bootstrap:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/sadine27/EL---II-SEM/<PIN_SHA>/scripts/deploy/hetzner_bootstrap.sh \
     | PIN_SHA=<PIN_SHA> bash
   ```
   Replace `<PIN_SHA>` with the commit SHA used for that release. Keep the SHA
   pinned in the URL; do not use `main`.
3. **Paste the deploy SSH public key** into `/home/deploy/.ssh/authorized_keys`
   (mode 600, owned by `deploy:deploy`).
4. **Paste production secrets** into `/etc/el/.env` (mode 600, owner `deploy`).
   Use `.env.example` in the repo root as the template.
5. **Set repository config in GitHub** (Settings → Secrets and variables → Actions):
   - **Variables (`vars`):**
     - `GHCR_OWNER` — your GitHub username/org that owns the `el` package
     - `HETZNER_SSH_HOST` — the box's IP or DNS name
   - **Secrets (`secrets`):**
     - `HETZNER_SSH_USER` — `deploy`
     - `HETZNER_SSH_KEY` — the private key that pairs with the public key
       you pasted in step 3
6. **First deploy:** push to `main`. The workflow tests → builds → deploys →
   polls healthz → re-tags `:latest`. Watch it under Actions → deploy.

## Day-2 ops

### Logs
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env logs api worker --tail 200 -f
```

### Manual rollback
```bash
ssh deploy@<host>
cd /etc/el
mv compose.env.prev compose.env
docker compose --env-file compose.env pull
docker compose --env-file compose.env up -d
```

### Force re-deploy of current tag
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env pull
docker compose --env-file compose.env up -d --force-recreate
```

### Wipe and redeploy (preserves named volumes)
```bash
ssh deploy@<host>
cd /etc/el
docker compose --env-file compose.env down
docker compose --env-file compose.env up -d
```

### Emergency: cancel an in-flight pipeline run
The worker has `stop_grace_period: 86400s` (24 hours) to protect long-running
pipeline jobs across deploys. If you need to deploy NOW and an in-flight run is
blocking you:
```bash
ssh deploy@<host>
docker compose --env-file /etc/el/compose.env kill worker
docker compose --env-file /etc/el/compose.env up -d worker
```
The pipeline row stays in `running` state in `private.run_requests`. Either
manually mark it `error` or accept that it will sit there until you clean it up.

## Disaster recovery

The CX22 has no built-in snapshot policy by default. State that matters:

- **Business data:** lives in Supabase (separate provider, separate snapshot
  policy via Supabase free tier).
- **Local state in `/app/data` named volume:** ephemeral; nothing critical
  should land here.
- **`.env` on the host:** keep an offline copy of the production `.env` in
  a password manager. Without it, you cannot reprovision.

Recovery procedure: provision a fresh CX22, re-run the bootstrap, paste the
saved `.env`, push to `main`. The new box is back online in ~10 minutes.

## Cost monitoring

- **Hetzner:** target ≤ €5/mo. Alert if monthly invoice > €10.
- **Vertex + Browserbase:** target ≤ $25/mo combined. Alert if either line
  item is > 2× last month.
- Check Hetzner Cloud Console → Project → Billing weekly.

## Upgrading to a real domain + Let's Encrypt

The bootstrap deploys with self-signed `tls internal`. Browser users hit a
cert warning. To swap in a real domain:

1. Point an A record at the box's IP.
2. SSH in, edit `/etc/el/Caddyfile`:
   ```
   example.com {
       reverse_proxy api:8000
   }
   ```
3. Open port 80 stays open (Caddy uses it for the ACME HTTP-01 challenge).
4. `docker compose --env-file compose.env restart caddy`
5. Caddy auto-fetches a Let's Encrypt cert on first request.

## Documented out-of-scope failure modes

- **Hetzner DC outage:** no automatic failover. Manual reprovision on a new
  box. SLA: ~10 minutes given DR procedure above.
- **Supabase outage:** `/healthz` returns 503; deploys block; running app
  surfaces errors. No fallback datastore.
- **GHCR outage:** new deploys block; running containers unaffected.
- **Cert warning blocks non-technical demos:** swap to a real domain + LE
  per the procedure above.
- **Worker stuck in 24h grace:** use the emergency `docker compose kill worker`
  procedure above.
```

- [ ] **Step 3: Commit**

```powershell
git add docs/runbooks/deploy.md
git commit -m "docs(sp8): deploy runbook"
```

---

## Task 17: Full local verification

**Files:**
- (no new files)

- [ ] **Step 1: Run the full pytest suite**

```powershell
pytest -q
```
Expected: all pass. Coverage floor 93% preserved.

- [ ] **Step 2: Build the image fresh**

```powershell
docker build -t el:sp8-final .
docker image inspect el:sp8-final --format "{{.Size}}"
```
Expected: build success; size < 500 MB (524288000 bytes).

- [ ] **Step 3: Run the docker smoke test (requires Docker Desktop)**

```powershell
$env:DOCKER_AVAILABLE="1"; pytest tests/integration -v
```
Expected: 1 pass.

- [ ] **Step 4: Confirm container cold-start < 10s**

```powershell
$start = Get-Date
docker run -d --name sp8-cold --rm `
    -e WEB_SECRET_KEY=x -e SUPABASE_URL=https://x.example `
    -e SUPABASE_SERVICE_ROLE_KEY=x `
    -e GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account","project_id":"p","private_key":"x","client_email":"x@p.iam","token_uri":"https://oauth2.googleapis.com/token"}' `
    -e YOUTUBE_API_KEY=x -e TAVILY_API_KEY=x -e CJ_EMAIL=x -e CJ_API_KEY=x `
    -e BROWSERBASE_API_KEY=x -e TELEGRAM_HIL_BOT_TOKEN=x -e TELEGRAM_HIL_CHAT_ID=x `
    -p 18001:8000 el:sp8-final
do {
    Start-Sleep -Milliseconds 200
    $resp = try { Invoke-WebRequest -UseBasicParsing http://localhost:18001/healthz -TimeoutSec 1 -SkipHttpErrorCheck } catch { $null }
} until ($resp -and ($resp.StatusCode -eq 200 -or $resp.StatusCode -eq 503))
$elapsed = (Get-Date) - $start
docker rm -f sp8-cold | Out-Null
"Cold start: $($elapsed.TotalSeconds) s"
```
Expected: < 10 seconds.

- [ ] **Step 5: Confirm `git status` is clean**

```powershell
git status
```
Expected: clean. All work in commits.

- [ ] **Step 6: Print the commit list for review**

```powershell
git log --oneline main..HEAD
```
Expected: ~16 commits, one per task. (If you implemented on `main`, use `git log --oneline -16` instead.)

**No `git push` yet.** The user decides when to push and watch the first cloud deploy.

---

## SP8 success criteria checklist

After local verification passes and the user pushes, the following must all be
true. Treat them as the acceptance test:

- [ ] Bootstrap script run on a fresh CX22 leaves `/etc/el` populated and idempotent on re-run
- [ ] Push to `main` triggers the workflow; `test` → `build` → `deploy` all green
- [ ] `curl -k https://<host>/healthz` returns `{"ok": true, "checks": {"db": "ok", "vertex_creds": "ok"}}`
- [ ] Submitting a niche from the SP4 web UI produces a Telegram HIL card; approval populates a Shopify dev store (SP5 path intact)
- [ ] An intentionally bad commit (e.g., syntax error in `el/web/app.py`) deploys, healthz fails, rollback fires, prior `:sha-<short>` is restored, the job exits non-zero
- [ ] `docker image ls` shows the image < 500 MB
- [ ] Cold start time `docker compose up -d` → healthz 200 is < 10 s
- [ ] First-month bill: Hetzner ≤ €5; Vertex + Browserbase combined ≤ $25

---

## Plan Self-Review

**Spec coverage (every spec section maps to a task):**
- Goals & non-goals → Task 17 success criteria + runbook explicitly lists non-goals
- Architecture (single image, two services, Caddy) → Tasks 9, 10
- Worker contract (plain loop + SIGTERM, claim pattern) → Tasks 5, 8
- `private.run_requests` definition → referenced in Task 5; existing SP4 table reused
- State volumes → Task 10 (compose file declares `el-data`, `caddy-data`, `caddy-config`)
- Dockerfile invariants → Tasks 9 + 1 (deps split)
- /healthz contract → Task 7
- .dockerignore → Task 2
- CI/CD test → Task 12
- CI/CD build → Task 13
- CI/CD deploy + healthz poll + rollback → Task 14
- vars vs secrets → Tasks 14, 16
- Concurrency `group: deploy` → Task 12 (workflow-level)
- Migrations manual → out of plan scope; runbook does not automate
- Bootstrap script → Task 15
- Runbook → Task 16
- Tests (worker, healthz, verify_env, dockerfile_lint, compose smoke) → Tasks 3, 7, 8, 9, 11
- Stop-grace 24h → Task 10 (compose worker `stop_grace_period: 86400s`)

**Placeholder scan:** no TBD/TODO. The only "fill-in-later" value is the `PIN_SHA` in the bootstrap script — that value cannot exist before the commit that defines the file the script fetches. The runbook step 2 calls this out explicitly. This is intentional sequencing, not a placeholder gap.

**Type consistency:** `claim_one_queued(worker_id, db_provider) → dict | None` used identically in worker test, run_service implementation, and worker tick. `db_provider.update_rows(filters: dict[str, str])` extended uniformly in `el/supabase.py`, `tests/web/conftest.py:FakeDB`. `Settings.google_service_account_json: str | None` defined in Task 7 step 1, consumed in step 4. `run_pipeline(request_id, *, db_provider)` signature used in worker tests, worker tick, and the default `_default_pipeline` wrapper.

No issues to fix inline.
