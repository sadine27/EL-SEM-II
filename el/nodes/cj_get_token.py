"""Port of n8n node `CJ Get Token`."""
from __future__ import annotations

from el import cj
from el.logger import get_logger

log = get_logger(__name__)


def _extract_access_token(response: dict) -> str | None:
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if isinstance(data, dict):
        token = data.get("accessToken")
        return str(token) if token else None
    return None


def run(ctx: dict, provider: cj.CJProvider | None = None) -> dict:
    try:
        p = provider or cj.default_provider()
        response = p.get_access_token()
    except Exception as exc:  # noqa: BLE001 - IO node fails soft.
        ctx["cj_token_response"] = {"ok": False, "error": str(exc)}
        ctx["cj_get_token_result"] = {"ok": False, "error": str(exc)}
        return ctx
    access_token = _extract_access_token(response)
    if not access_token:
        error = "CJ Get Token response missing data.accessToken"
        ctx["cj_token_response"] = response
        ctx["cj_get_token_result"] = {"ok": False, "error": error}
        return ctx

    ctx["cj_token_response"] = response
    ctx["cj_access_token"] = access_token
    ctx["cj_get_token_result"] = {"ok": True}
    log.info("CJ Get Token: received access token")
    return ctx
