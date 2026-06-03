"""Trend source: AI + web-search trend discovery (the Fenix "brain" front-end).

Instead of scraping fragile endpoints (pytrends/reddit/amazon — all dead or
blocked), this source asks the live web *directly*: it runs a handful of Tavily
web searches for "what is trending / selling in India right now", optionally
folds in real headlines already collected by the feed sources as grounding, and
hands the combined evidence to Gemini, which extracts a structured list of
**buyable trending products** with a citation URL each.

Web grounding + required citation URL is the anti-hallucination contract: every
candidate must trace back to a real search result, so the model cannot invent a
trend out of nothing.

Design contract (fail-soft, no credentials required to import):
  * ``EL_AI_DISCOVERY_ENABLED`` (default "true") gates the whole source.
  * Requires ``TAVILY_API_KEY`` (web search) and ``GOOGLE_SERVICE_ACCOUNT_JSON``
    (Gemini). Either absent → ``[]`` with an explicit ``EMPTY (no key)`` log.
  * Tavily and the LLM provider are injectable for tests.
  * Every external call is wrapped: any failure returns ``[]``, never raises.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from el import config
from el.logger import get_logger
from el.sources import TrendCandidate

SOURCE_ID = "ai_trend_discovery"
log = get_logger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

# Seed queries that surface *current* Indian buying signal from the live web.
_DEFAULT_QUERIES = (
    "trending products to buy online in India this week",
    "viral product India right now shopping",
    "what are Indians buying online trending now",
    "India current event fan merchandise trending product",
    "most popular products flipkart amazon india this week",
)

_MAX_GROUNDING_HEADLINES = 40
_RESULTS_PER_QUERY = 5

_SYSTEM = (
    "You are a dropshipping trend scout for the INDIAN e-commerce market. "
    "You are given (a) web search snippets gathered just now and (b) optional "
    "recent Indian news headlines. From this real evidence, identify physical "
    "products that Indian shoppers would buy online RIGHT NOW. Treat "
    "current-event fan merchandise as products: if a cricket team just won, "
    "'TEAM jersey' is a hot product; if a toy/character goes viral, the "
    "collectible is hot.\n\n"
    "Rules:\n"
    "- Only output a product if it is supported by the supplied evidence. "
    "Every item MUST cite a source_url taken from the evidence. Do not invent "
    "URLs or trends.\n"
    "- Prefer specific buyable items ('RCB IPL 2025 jersey') over vague topics "
    "('cricket').\n\n"
    "Return ONLY a JSON array, one object per product:\n"
    '{"product": "<buyable item name>", "category": "<short category>", '
    '"why_trending": "<one short phrase>", "intent": <float 0..1>, '
    '"source_url": "<url from evidence>"}\n'
    "intent = strength of immediate purchase intent (1.0 = people buying today). "
    "No commentary outside the JSON array."
)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", (text or "").strip())


def _enabled() -> bool:
    return (config.get("EL_AI_DISCOVERY_ENABLED", "true") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _int_env(name: str, default: int) -> int:
    raw = config.get(name)
    try:
        val = int(raw)  # type: ignore[arg-type]
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


def _grounding_headlines(ctx: dict) -> list[str]:
    """Pull titles from feed candidates already collected this run, if any."""
    cands = ctx.get("source_candidates") or []
    heads: list[str] = []
    for c in cands:
        title = getattr(c, "title", None)
        if isinstance(title, str) and title.strip():
            heads.append(title.strip())
        if len(heads) >= _MAX_GROUNDING_HEADLINES:
            break
    return heads


def _gather_web_evidence(tavily, queries: list[str]) -> tuple[list[dict], set[str]]:
    """Run each Tavily query; return flattened snippets + the set of valid URLs."""
    snippets: list[dict] = []
    valid_urls: set[str] = set()
    for q in queries:
        res = tavily.search(q, max_results=_RESULTS_PER_QUERY, include_raw_content=False)
        if not res.get("ok"):
            log.debug("ai_trend_discovery: tavily query failed: %s", q)
            continue
        if res.get("answer"):
            snippets.append({"query": q, "answer": res["answer"]})
        for r in res.get("results", []):
            url = (r.get("url") or "").strip()
            if url:
                valid_urls.add(url)
            snippets.append({
                "title": r.get("title", ""),
                "url": url,
                "content": (r.get("content", "") or "")[:400],
            })
    return snippets, valid_urls


def _build_user_prompt(snippets: list[dict], headlines: list[str]) -> str:
    parts = ["WEB SEARCH EVIDENCE (gathered now):", json.dumps(snippets, ensure_ascii=False)]
    if headlines:
        parts += ["\nRECENT INDIAN HEADLINES (grounding):", json.dumps(headlines, ensure_ascii=False)]
    return "\n".join(parts)


def _parse_products(raw: str) -> list[dict]:
    text = _strip_fences(raw)
    if not text:
        return []
    if not text.lstrip().startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        log.warning("ai_trend_discovery: could not parse model JSON")
        return []
    return [o for o in data if isinstance(o, dict)] if isinstance(data, list) else []


def _coerce_intent(value) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return 0.5


def fetch_trends(ctx: dict, *, tavily=None, provider=None) -> list[TrendCandidate]:
    if not _enabled():
        log.info("ai_trend_discovery: disabled (EL_AI_DISCOVERY_ENABLED) — EMPTY")
        return []

    if tavily is None:
        if not config.get("TAVILY_API_KEY"):
            log.info("ai_trend_discovery: EMPTY (no key) — TAVILY_API_KEY not set")
            return []
        try:
            from el import tavily as tavily_mod
            tavily = tavily_mod.default_provider()
        except Exception as exc:
            log.warning("ai_trend_discovery: tavily unavailable (%s) — EMPTY", exc)
            return []

    if provider is None:
        if not config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
            log.info("ai_trend_discovery: EMPTY (no key) — GOOGLE_SERVICE_ACCOUNT_JSON not set")
            return []
        try:
            from el import llm
            provider = llm.default_provider()
        except Exception as exc:
            log.warning("ai_trend_discovery: LLM unavailable (%s) — EMPTY", exc)
            return []

    snippets, valid_urls = _gather_web_evidence(tavily, list(_DEFAULT_QUERIES))
    if not snippets:
        log.info("ai_trend_discovery: BLOCKED — no web evidence gathered (Tavily returned nothing)")
        return []

    headlines = _grounding_headlines(ctx)
    try:
        raw = provider.generate(_SYSTEM, _build_user_prompt(snippets, headlines))
    except Exception as exc:
        log.warning("ai_trend_discovery: LLM call failed (%s) — EMPTY", exc)
        return []

    products = _parse_products(raw)
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    max_out = _int_env("EL_AI_DISCOVERY_MAX", 20)

    candidates: list[TrendCandidate] = []
    seen: set[str] = set()
    dropped_no_cite = 0
    for obj in products:
        name = str(obj.get("product") or "").strip()
        url = str(obj.get("source_url") or "").strip()
        if not name or name.lower() in seen:
            continue
        # Anti-hallucination: candidate must cite a URL that came from the evidence.
        if not url or url not in valid_urls:
            dropped_no_cite += 1
            continue
        seen.add(name.lower())
        intent = _coerce_intent(obj.get("intent"))
        candidates.append(TrendCandidate(
            title=name,
            source_id=SOURCE_ID,
            score_hint=intent,
            velocity=intent,
            raw_payload={
                "category": str(obj.get("category") or "").strip(),
                "why_trending": str(obj.get("why_trending") or "").strip(),
                "url": url,
                "ai_discovered": True,
            },
            fetched_at=now,
        ))
        if len(candidates) >= max_out:
            break

    status = "OK" if candidates else "EMPTY"
    log.info(
        "ai_trend_discovery: %s — %d products from %d web snippets (%d dropped: uncited)",
        status, len(candidates), len(snippets), dropped_no_cite,
    )
    return candidates
