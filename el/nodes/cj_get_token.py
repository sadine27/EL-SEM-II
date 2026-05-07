"""Port of n8n node `CJ Get Token`."""
from __future__ import annotations

from el import cj
from el.logger import get_logger

log = get_logger(__name__)


def _extract_access_token(response: dict) -> str | None:
    data = response.get("data")
    if isinstance(data, dict):
        token = data.get("accessToken")
        return str(token) if token else None
    return None


def run(ctx: dict, provider: cj.CJProvider | None = None) -> dict:
    p = provider or cj.default_provider()
    response = p.get_access_token()
    access_token = _extract_access_token(response)
    if not access_token:
        raise RuntimeError("CJ Get Token response missing data.accessToken")

    ctx["cj_token_response"] = response
    ctx["cj_access_token"] = access_token
    log.info("CJ Get Token: received access token")
    return ctx
