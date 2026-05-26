#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/verify_env_runtime.py

exec "$@"
