"""Validate .env credentials end-to-end.

Run:  .venv\\Scripts\\python.exe scripts\\verify_env.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.example"


def load_env(path: Path) -> dict[str, str]:
    """Use python-dotenv (same lib the app uses) so escapes are handled correctly."""
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def banner(title: str) -> None:
    print(f"\n{'=' * 70}\n {title}\n{'=' * 70}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def main() -> int:
    env = load_env(ENV_PATH)
    failures = 0

    banner("1. YouTube Data API v3")
    key = env.get("YOUTUBE_API_KEY", "")
    if not key:
        fail("missing"); failures += 1
    else:
        r = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet", "chart": "mostPopular", "maxResults": 1, "key": key},
            timeout=15,
        )
        if r.status_code == 200:
            ok(f"key works (got {len(r.json().get('items', []))} item)")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}"); failures += 1

    banner("2. Tavily Search API")
    key = env.get("TAVILY_API_KEY", "")
    if not key:
        fail("missing"); failures += 1
    else:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": key, "query": "test", "max_results": 1},
            timeout=20,
        )
        if r.status_code == 200:
            ok("key works")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}"); failures += 1

    banner("3. Gemini via Vertex AI")
    raw_sa = env.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw_sa:
        fail("GOOGLE_SERVICE_ACCOUNT_JSON missing — Vertex needs the SA"); failures += 1
    else:
        try:
            from google.auth.transport.requests import Request as _GReq
            from google.oauth2 import service_account
            creds = service_account.Credentials.from_service_account_info(
                json.loads(raw_sa),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            creds.refresh(_GReq())
            project_id = json.loads(raw_sa)["project_id"]
            location = env.get("VERTEX_LOCATION") or "global"
            host = ("https://aiplatform.googleapis.com" if location == "global"
                    else f"https://{location}-aiplatform.googleapis.com")
            url = (f"{host}/v1/projects/{project_id}/locations/{location}"
                   "/publishers/google/models/gemini-2.5-flash:generateContent")
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {creds.token}",
                         "Content-Type": "application/json"},
                json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]},
                timeout=20,
            )
            if r.status_code == 200 and r.json().get("candidates"):
                ok(f"Vertex generateContent OK (project={project_id}, location={location})")
            else:
                fail(f"Vertex HTTP {r.status_code}: {r.text[:300]}"); failures += 1
        except Exception as e:
            fail(f"Vertex auth/call failed: {e}"); failures += 1

    banner("4. Google Service Account JSON")
    raw = env.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        fail("missing"); failures += 1
    else:
        try:
            sa = json.loads(raw)
            required = ["type", "project_id", "private_key", "client_email", "token_uri"]
            missing = [k for k in required if k not in sa]
            if missing:
                fail(f"JSON parsed but missing: {missing}"); failures += 1
            else:
                ok(f"JSON parsed: {sa['client_email']} (project: {sa['project_id']})")
                # Try to mint a token
                try:
                    import base64
                    import time
                    from cryptography.hazmat.primitives import hashes, serialization
                    from cryptography.hazmat.primitives.asymmetric import padding

                    now = int(time.time())
                    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=")
                    claims = {
                        "iss": sa["client_email"],
                        "scope": "https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive",
                        "aud": sa["token_uri"],
                        "iat": now,
                        "exp": now + 3600,
                    }
                    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
                    signing_input = header + b"." + payload
                    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
                    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
                    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=")
                    jwt = (signing_input + b"." + sig_b64).decode()

                    r = requests.post(
                        sa["token_uri"],
                        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt},
                        timeout=15,
                    )
                    if r.status_code == 200 and "access_token" in r.json():
                        ok("OAuth token mint OK (Sheets + Drive scopes)")
                    else:
                        fail(f"OAuth mint failed HTTP {r.status_code}: {r.text[:200]}"); failures += 1
                except Exception as e:
                    warn(f"could not mint token (may be missing crypto lib): {e}")
        except json.JSONDecodeError as e:
            fail(f"JSON parse failed: {e}"); failures += 1
            print(f"         First 200 chars: {raw[:200]!r}")

    banner("5. CJ Dropshipping API")
    cj_email = env.get("CJ_EMAIL", "")
    cj_key = env.get("CJ_API_KEY", "")
    if not cj_email or not cj_key:
        fail("missing"); failures += 1
    else:
        r = requests.post(
            "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
            json={"email": cj_email, "password": cj_key},
            timeout=20,
        )
        if r.status_code == 200 and r.json().get("result"):
            ok("auth OK (token issued)")
        else:
            try:
                msg = r.json().get("message", r.text[:200])
            except Exception:
                msg = r.text[:200]
            fail(f"HTTP {r.status_code}: {msg}"); failures += 1

    banner("6. Supabase")
    url = env.get("SUPABASE_URL", "").rstrip("/")
    sk = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_SECRET_KEY") or env.get("SUPABASE_KEY")
    if not url or not sk:
        fail("missing"); failures += 1
    else:
        if sk.startswith("sb_publishable_"):
            warn("key in SUPABASE_SERVICE_ROLE_KEY is a PUBLISHABLE/anon key, not service_role")
            warn("  -> writes to RLS-enabled tables will fail unless RLS policies grant anon")
        r = requests.get(
            f"{url}/rest/v1/scraped_products",
            params={"select": "id", "limit": "1"},
            headers={"apikey": sk, "Authorization": f"Bearer {sk}"},
            timeout=15,
        )
        if r.status_code == 200:
            ok(f"REST read OK ({len(r.json())} row)")
        else:
            fail(f"REST HTTP {r.status_code}: {r.text[:200]}"); failures += 1
        # try a write probe (insert dry — will fail if RLS blocks)
        r2 = requests.post(
            f"{url}/rest/v1/scraped_products",
            headers={
                "apikey": sk,
                "Authorization": f"Bearer {sk}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=[{"product_url": "https://probe.example/_TEST_DELETE_ME", "source_topic": "_PROBE"}],
            timeout=15,
        )
        if r2.status_code in (200, 201, 204):
            ok("REST write OK — service-level access confirmed")
            requests.delete(
                f"{url}/rest/v1/scraped_products",
                params={"product_url": "eq.https://probe.example/_TEST_DELETE_ME"},
                headers={"apikey": sk, "Authorization": f"Bearer {sk}"},
                timeout=15,
            )
        elif r2.status_code == 400 and '"23502"' in r2.text:
            # NOT NULL violation = auth OK, probe row just incomplete
            ok("REST write auth OK (probe missing optional NOT NULL cols, expected)")
        elif r2.status_code in (401, 403) or '"42501"' in r2.text:
            fail(f"REST write blocked by RLS/auth HTTP {r2.status_code}: {r2.text[:200]}"); failures += 1
        else:
            fail(f"REST write unexpected HTTP {r2.status_code}: {r2.text[:200]}"); failures += 1

    banner("7. Browserbase")
    key = env.get("BROWSERBASE_API_KEY", "")
    if not key:
        fail("missing"); failures += 1
    else:
        r = requests.get(
            "https://api.browserbase.com/v1/projects",
            headers={"X-BB-API-Key": key},
            timeout=15,
        )
        if r.status_code in (200, 201):
            ok("key works")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}"); failures += 1

    banner("8. Telegram HIL Bot")
    tok = env.get("TELEGRAM_HIL_BOT_TOKEN", "")
    chat = env.get("TELEGRAM_HIL_CHAT_ID", "")
    if not tok or not chat:
        fail("missing"); failures += 1
    else:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15)
        if r.status_code == 200 and r.json().get("ok"):
            bot = r.json()["result"]
            ok(f"bot exists: @{bot.get('username')}")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}"); failures += 1

    banner("9. Telegram Developer Alert Bot (optional)")
    tok = env.get("EL_DEVELOPER_ALERT_TOKEN_KEY", "")
    if not tok:
        warn("missing — alerts will only go to logs")
    else:
        r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15)
        if r.status_code == 200 and r.json().get("ok"):
            bot = r.json()["result"]
            ok(f"bot exists: @{bot.get('username')}")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}"); failures += 1

    print(f"\n{'=' * 70}\n {failures} failure(s)\n{'=' * 70}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
