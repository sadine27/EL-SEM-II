"""Fenix Engine — AI trend scoring / categorization (the "brain").

The keyword scorer in ``score_rank`` is fast but blind to anything outside its
fixed vocabulary: a brand-new viral product (e.g. "Labubu") matches no keyword
and scores ~0, even though the live sources surfaced it. This node fixes that by
asking Gemini to judge each *already-collected* topic with an open vocabulary:

    is this a physical product Indians would buy online right now (including
    fan merch for current events), how strong is the buy-intent, what category?

It runs **after** ``score_rank`` and overrides the keyword ``product_intent_score``
and ``suggested_categories`` for topics the model recognises, then re-ranks.

Design contract (fail-soft, no credentials required to import/run):
  * ``EL_AI_SCORING_ENABLED`` (default "true") gates the whole node.
  * Requires ``GOOGLE_SERVICE_ACCOUNT_JSON``; absent → no-op, keyword scores kept.
  * Topics are batched (``EL_AI_SCORING_BATCH``) and capped
    (``EL_AI_SCORING_MAX_TOPICS``) to bound cost.
  * Provider creation, each batch call, and JSON parsing are individually
    wrapped: any failure leaves the affected topics on their keyword scores.
  * ``provider`` is injectable for tests (anything with ``.generate(system, user)``).
"""
from __future__ import annotations

import json
import re

from el import config
from el.logger import get_logger
from el.nodes.score_rank import CATEGORIES

log = get_logger(__name__)

_DEFAULT_BATCH = 40
_DEFAULT_MAX_TOPICS = 120
_DEFAULT_MODEL = "gemini-2.5-flash"

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_SYSTEM = (
    "You are a dropshipping trend analyst for the INDIAN e-commerce market. "
    "You are given a numbered list of raw trending topics scraped from Google "
    "Trends, Reddit, news and marketplaces. For EACH topic decide whether it "
    "represents a physical product that Indian shoppers would buy online RIGHT "
    "NOW. Treat current-event fan merchandise as products: if a cricket team "
    "just won, 'TEAM jersey' is a hot product; if a toy or character is going "
    "viral (e.g. Labubu), the collectible is a hot product.\n\n"
    "Return ONLY a JSON array, one object per input topic, each shaped:\n"
    '{"i": <int index>, "is_product": <bool>, "intent": <float 0..1>, '
    '"category": "<short category>", "canonical_product": "<buyable item name>"}\n\n'
    "canonical_product MUST be a SPECIFIC, SEARCHABLE product a shopper could type "
    "into Amazon.in or Flipkart and get the exact item — include the brand and/or "
    "model whenever the topic implies one (e.g. 'Vivo X300 Ultra', 'RCB IPL 2025 "
    "Jersey', 'Labubu Macaron Blind Box'). NEVER return a vague category like "
    "'Smart Wearable', 'Clean Beauty Product' or 'Athleisure Clothing'. If the "
    "topic is not a concrete buyable product, set is_product=false and leave "
    "canonical_product as an empty string.\n\n"
    "intent = how strong the immediate purchase intent is (1.0 = people are "
    "actively buying this today; 0.0 = not a product / no commercial intent). "
    "Prefer these categories when they fit, else use a short sensible label: "
    "{cats}. Do not add commentary outside the JSON array."
)


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", (text or "").strip())


def _int_env(name: str, default: int) -> int:
    raw = config.get(name)
    try:
        val = int(raw)  # type: ignore[arg-type]
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return (config.get("EL_AI_SCORING_ENABLED", "true") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _build_user_prompt(batch: list[tuple[int, str]]) -> str:
    lines = [f"{i}. {topic}" for i, topic in batch]
    return "Topics:\n" + "\n".join(lines)


def _parse_response(raw: str) -> dict[int, dict]:
    """Parse the model's JSON array into {index: result-dict}. Tolerant of junk."""
    text = _strip_fences(raw)
    if not text:
        return {}
    # The model occasionally wraps the array in prose; grab the outermost [...].
    if not text.lstrip().startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        log.warning("ai_score_trends: could not parse model JSON")
        return {}
    out: dict[int, dict] = {}
    if isinstance(data, list):
        for obj in data:
            if isinstance(obj, dict) and isinstance(obj.get("i"), int):
                out[obj["i"]] = obj
    return out


def _coerce_intent(value) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except (TypeError, ValueError):
        return None


def run(ctx: dict, *, provider=None) -> dict:
    """Override keyword scores with AI judgement where available, then re-rank."""
    if not _enabled():
        log.info("ai_score_trends: disabled (EL_AI_SCORING_ENABLED) — keeping keyword scores")
        return ctx

    payload = ctx.get("ranked_payload") or {}
    trends = payload.get("trends") or []
    if not trends:
        return ctx

    if provider is None:
        if not config.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
            log.info("ai_score_trends: GOOGLE_SERVICE_ACCOUNT_JSON not set — keeping keyword scores")
            return ctx
        try:
            from el import llm
            provider = llm.default_provider()
        except Exception as exc:  # creds malformed, import error, etc.
            log.warning("ai_score_trends: provider unavailable (%s) — keeping keyword scores", exc)
            return ctx

    max_topics = _int_env("EL_AI_SCORING_MAX_TOPICS", _DEFAULT_MAX_TOPICS)
    batch_size = _int_env("EL_AI_SCORING_BATCH", _DEFAULT_BATCH)
    model_hint = config.get("EL_AI_SCORING_MODEL", _DEFAULT_MODEL)

    scored_idx = list(range(min(len(trends), max_topics)))
    # str.replace (not .format) — _SYSTEM contains literal JSON braces.
    system = _SYSTEM.replace("{cats}", ", ".join(CATEGORIES.keys()))

    ai_count = 0
    for start in range(0, len(scored_idx), batch_size):
        window = scored_idx[start : start + batch_size]
        batch = [(i, trends[i].get("topic", "")) for i in window]
        try:
            raw = provider.generate(system, _build_user_prompt(batch))
        except Exception as exc:
            log.warning("ai_score_trends: batch %d call failed (%s) — keyword scores kept", start, exc)
            continue
        results = _parse_response(raw)
        for local_i, (global_i, _topic) in enumerate(batch):
            res = results.get(local_i)
            if not isinstance(res, dict):
                continue
            trend = trends[global_i]
            intent = _coerce_intent(res.get("intent"))
            if res.get("is_product") is False and intent is None:
                intent = 0.0
            if intent is not None:
                trend["product_intent_score"] = intent
            category = res.get("category")
            if isinstance(category, str) and category.strip():
                trend["suggested_categories"] = [category.strip().lower().replace(" ", "_")]
            if isinstance(res.get("canonical_product"), str):
                trend["canonical_product"] = res["canonical_product"].strip()
            trend["is_product"] = bool(res.get("is_product"))
            trend["ai_scored"] = True
            ai_count += 1

    if ai_count == 0:
        log.info("ai_score_trends: no topics enriched (model returned nothing usable)")
        return ctx

    # Re-rank with AI-adjusted scores: intent → velocity → cross-source count.
    trends.sort(key=lambda t: (
        -t.get("product_intent_score", 0.0),
        -(t.get("velocity") or 0.0),
        -t.get("cross_source_count", 1),
    ))
    for new_rank, trend in enumerate(trends, start=1):
        trend["rank"] = new_rank

    meta = payload.setdefault("metadata", {})
    meta["ai_scored_count"] = ai_count
    meta["ai_model"] = model_hint
    log.info("ai_score_trends: enriched %d/%d topics via AI", ai_count, len(trends))
    return ctx
