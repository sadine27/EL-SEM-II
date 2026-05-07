"""Port of n8n node `Prepare JSON File`.

Serializes ctx["ranked_payload"] as pretty JSON, base64-encodes it, and stores
an n8n-like file item at ctx["json_file"]. The next node, `Drive Upload`, will
consume this shape.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

from el.logger import get_logger

log = get_logger(__name__)


def _today_filename() -> str:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"trending_india_{date}.json"


def build_file_item(payload: dict, filename: str) -> dict:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return {
        "json": {"filename": filename},
        "binary": {
            "data": {
                "data": encoded,
                "mimeType": "application/json",
                "fileName": filename,
                "fileExtension": "json",
            }
        },
    }


def run(ctx: dict) -> dict:
    payload = ctx.get("ranked_payload") or {}
    filename = _today_filename()
    ctx["json_file"] = build_file_item(payload, filename)
    log.info("Prepare JSON File: prepared %s", filename)
    return ctx
