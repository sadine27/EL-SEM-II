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
