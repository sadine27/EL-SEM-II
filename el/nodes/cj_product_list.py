"""Port of n8n node `CJ Product List`."""
from __future__ import annotations

import time
from collections.abc import Callable

from el import cj
from el.logger import get_logger

log = get_logger(__name__)

DEFAULT_BATCH_INTERVAL = 1.5
DEFAULT_MAX_TRIES = 3
DEFAULT_WAIT_BETWEEN_TRIES = 2.0


def _fetch_with_retry(
    provider: cj.CJProvider,
    keyword: str,
    access_token: str,
    max_tries: int,
    wait_between_tries: float,
    sleep: Callable[[float], None],
) -> dict:
    last_exc: Exception | None = None
    for attempt in range(max_tries):
        try:
            return provider.list_products(keyword, access_token)
        except Exception as exc:
            last_exc = exc
            if attempt < max_tries - 1:
                sleep(wait_between_tries)
    raise last_exc or RuntimeError("CJ Product List failed")


def run(
    ctx: dict,
    provider: cj.CJProvider | None = None,
    batch_interval: float = DEFAULT_BATCH_INTERVAL,
    max_tries: int = DEFAULT_MAX_TRIES,
    wait_between_tries: float = DEFAULT_WAIT_BETWEEN_TRIES,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    queries = ctx.get("cj_search_queries") or []
    access_token = ctx.get("cj_access_token")
    if not queries:
        ctx["cj_product_list_responses"] = []
        log.warning("CJ Product List: no cj_search_queries to fetch")
        return ctx
    if not access_token:
        raise RuntimeError("CJ Product List requires ctx['cj_access_token']")

    p = provider or cj.default_provider()
    responses = []
    for index, query in enumerate(queries):
        keyword = str(query.get("keyword") or "").strip()
        if not keyword:
            continue
        try:
            response = _fetch_with_retry(
                p,
                keyword,
                access_token,
                max_tries=max_tries,
                wait_between_tries=wait_between_tries,
                sleep=sleep,
            )
            responses.append({"query": query, "response": response, "ok": True})
        except Exception as exc:
            responses.append({"query": query, "ok": False, "error": str(exc)})
            log.warning("CJ Product List failed for %s; continuing: %s", keyword, exc)
        if index < len(queries) - 1:
            sleep(batch_interval)

    ctx["cj_product_list_responses"] = responses
    log.info("CJ Product List: fetched %d keyword responses", len(responses))
    return ctx
