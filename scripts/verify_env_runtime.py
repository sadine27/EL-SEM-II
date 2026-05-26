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
