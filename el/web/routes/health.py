"""SP4 — /healthz: liveness probe for the reverse proxy."""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter

router = APIRouter()


def _git_sha() -> str:
    """Best-effort short SHA. Returns 'unknown' on any failure (incl. no git)."""
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


@router.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "version": _git_sha()}
