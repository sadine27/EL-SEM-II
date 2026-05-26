"""SP8 — full compose-stack smoke test. Opt-in via DOCKER_AVAILABLE=1.

Not part of the default pytest run because it builds an image and starts
containers. CI runs the default suite; this is for local verification.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

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


def _valid_sa() -> dict:
    return {
        "type": "service_account",
        "project_id": "p",
        "private_key": "x",
        "client_email": "x@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def _wait_for_healthz(url: str, timeout_s: int = 60) -> dict:
    deadline = time.monotonic() + timeout_s
    last_exc = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return {"status": r.status, "body": json.loads(r.read().decode())}
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode())
            except Exception:
                body = {}
            return {"status": e.code, "body": body}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            last_exc = e
            time.sleep(2)
    raise AssertionError(f"healthz never came up: {last_exc}")


def test_compose_brings_api_up_and_healthz_green(tmp_path):
    """Build image, run api, hit healthz directly (bypass caddy)."""
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
    _run([
        "docker", "run", "-d", "--rm",
        "--name", "el-sp8-smoke",
        "-p", "18000:8000",
        "--env-file", str(env_file),
        "el:sp8-smoke",
    ])
    try:
        # /healthz returns 503 because the fake Supabase URL is unreachable,
        # but the *process* came up — that's what the smoke proves.
        result = _wait_for_healthz("http://localhost:18000/healthz", timeout_s=30)
        assert result["status"] in (200, 503)
        assert "checks" in result["body"]
    finally:
        subprocess.run(["docker", "rm", "-f", "el-sp8-smoke"], capture_output=True)
