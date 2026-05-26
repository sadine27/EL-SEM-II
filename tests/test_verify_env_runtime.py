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
    # On Windows, subprocess needs at minimum SystemRoot/PATH/PATHEXT/COMSPEC
    # to launch a child Python process. Inject only those system vars so the
    # test env stays isolated (no accidental real secrets leaking in).
    import os
    windows_sys = {
        k: v
        for k, v in os.environ.items()
        if k.upper() in ("SYSTEMROOT", "PATH", "PATHEXT", "COMSPEC")
    }
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**windows_sys, **env},
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
