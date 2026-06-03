"""Forge supplier search node."""
from __future__ import annotations

from dataclasses import asdict
from difflib import SequenceMatcher
from importlib import import_module
import re
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from el import config
from el.logger import get_logger
from el.suppliers import SupplierCandidate, SupplierSource

log = get_logger(__name__)

# marketplace = real Indian marketplace listings (Amazon.in/Flipkart/Meesho),
# the only source that covers India-viral items. cj/eprolo remain importable but
# off the default path: CJ has no India items, eprolo is a stub. Opt back in via
# EL_SUPPLIER_SOURCES_ENABLED if ever needed.
_DEFAULT_SUPPLIER_SOURCES = ["marketplace"]
_SUPPLIER_MODULES = {
    "marketplace": "el.suppliers.marketplace_source",
    "cj": "el.suppliers.cj_source",
    "eprolo": "el.suppliers.eprolo_source",
}
_SOURCE_RELIABILITY = {
    "marketplace": 0.92,
    "cj": 0.90,
    "eprolo": 0.75,
}


def _int_config(name: str, default: int) -> int:
    raw = config.get(name)
    try:
        return max(0, int(str(raw).strip())) if raw is not None else default
    except ValueError:
        return default


def _enabled_source_names() -> list[str]:
    raw = config.get("EL_SUPPLIER_SOURCES_ENABLED")
    names = [n.strip().lower() for n in (raw or "").split(",") if n.strip()]
    return names or list(_DEFAULT_SUPPLIER_SOURCES)


def _load_enabled_sources() -> list[SupplierSource]:
    sources: list[SupplierSource] = []
    for name in _enabled_source_names():
        module_name = _SUPPLIER_MODULES.get(name)
        if module_name is None:
            log.warning("EL_SUPPLIER_SOURCES_ENABLED: unknown source %r - skipping", name)
            continue
        try:
            module = import_module(module_name)
            source = module.default_source()
        except ModuleNotFoundError:
            log.warning("supplier source %s is not available yet - skipping", name)
            continue
        except Exception:
            log.exception("supplier source %s failed to initialize - skipping", name)
            continue
        if source is not None:
            sources.append(source)
    return sources


def _trend_query(trend: object) -> str:
    if isinstance(trend, str):
        return trend.strip()
    if isinstance(trend, dict):
        # canonical_product is the AI-normalised buyable name (e.g. raw headline
        # "Vivo X300 Ultra Review | ..." -> "Vivo X300 Ultra"). Prefer it so the
        # supplier searches a real product, not a news headline or category label.
        for key in ("canonical_product", "topic", "title", "query", "search_query_in", "suggested_product_type"):
            value = trend.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_trends(ctx: dict, top: int | None = None) -> list[dict]:
    ranked_payload = ctx.get("ranked_payload")
    if isinstance(ranked_payload, dict):
        source_trends = ranked_payload.get("trends", [])
    else:
        source_trends = ctx.get("ranked", [])

    if not isinstance(source_trends, list):
        return []

    limit = _int_config("EL_SUPPLIER_SEARCH_TOP_TRENDS", 10) if top is None else max(0, top)
    trends: list[dict] = []
    for index, item in enumerate(source_trends[:limit], start=1):
        query = _trend_query(item)
        if not query:
            continue
        trend = dict(item) if isinstance(item, dict) else {"topic": query}
        trend.setdefault("rank", index)
        trends.append(trend)
    return trends


def _normalize_title(title: str | None) -> str:
    if not title:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _title_similarity(query: str, title: str) -> float:
    query_norm = _normalize_title(query)
    title_norm = _normalize_title(title)
    if not query_norm or not title_norm:
        return 0.0

    query_tokens = set(query_norm.split())
    title_tokens = set(title_norm.split())
    token_score = len(query_tokens & title_tokens) / len(query_tokens | title_tokens)
    sequence_score = SequenceMatcher(None, query_norm, title_norm).ratio()
    return max(token_score, sequence_score)


def _landed_cost(candidate: SupplierCandidate) -> float | None:
    cost = candidate.cost
    shipping = candidate.shipping_cost or 0.0
    if cost is None:
        return None
    return float(cost) + float(shipping)


def score_candidate(query: str, candidate: SupplierCandidate) -> float:
    title_score = _title_similarity(query, candidate.title)
    stock_score = 1.0 if (candidate.stock is not None and candidate.stock > 0) else 0.0
    image_score = 1.0 if candidate.image_url else 0.0
    reliability_score = _SOURCE_RELIABILITY.get(candidate.source_id, 0.50)

    landed = _landed_cost(candidate)
    cost_score = 0.35 if landed is None else 1.0 / (1.0 + max(0.0, landed) / 25.0)

    days = candidate.shipping_days_min or candidate.shipping_days_max
    delivery_score = 0.35 if days is None else 1.0 / (1.0 + max(0, days) / 10.0)

    score = (
        title_score * 0.36
        + stock_score * 0.18
        + cost_score * 0.18
        + delivery_score * 0.12
        + image_score * 0.08
        + reliability_score * 0.08
    )
    return round(score, 4)


def _dedupe_candidates(candidates: Iterable[SupplierCandidate], query: str) -> list[SupplierCandidate]:
    best_by_key: dict[str, SupplierCandidate] = {}
    for candidate in candidates:
        url_key = _normalize_url(candidate.product_url)
        title_key = _normalize_title(candidate.title)
        key = f"url:{url_key}" if url_key else f"title:{title_key}"
        if not title_key:
            continue
        current = best_by_key.get(key)
        if current is None or score_candidate(query, candidate) > score_candidate(query, current):
            best_by_key[key] = candidate
    return list(best_by_key.values())


def _candidate_payload(query: str, candidate: SupplierCandidate) -> dict:
    payload = asdict(candidate)
    payload["landed_cost"] = _landed_cost(candidate)
    payload["match_score"] = score_candidate(query, candidate)
    return payload


def run(
    ctx: dict,
    *,
    sources: list[SupplierSource] | None = None,
    top: int | None = None,
) -> dict:
    supplier_sources = sources if sources is not None else _load_enabled_sources()
    max_results = _int_config("EL_SUPPLIER_SEARCH_MAX_RESULTS_PER_SOURCE", 20)

    supplier_matches: list[dict] = []
    for trend in _extract_trends(ctx, top=top):
        query = _trend_query(trend)
        raw_candidates: list[SupplierCandidate] = []
        for source in supplier_sources:
            try:
                results = source.search_products(query, ctx)
            except Exception:
                log.exception("supplier source %s: search_products crashed", getattr(source, "SOURCE_ID", "?"))
                continue
            raw_candidates.extend(results[:max_results])

        deduped = _dedupe_candidates(raw_candidates, query)
        ranked = sorted(
            deduped,
            key=lambda candidate: score_candidate(query, candidate),
            reverse=True,
        )
        supplier_matches.append({
            "trend": trend,
            "query": query,
            "matches": [_candidate_payload(query, candidate) for candidate in ranked],
        })

    ctx["supplier_matches"] = supplier_matches
    return ctx
