"""Fenix Engine — AI trend scoring / categorization (the "brain").

The keyword scorer in ``score_rank`` is fast but blind to anything outside its
fixed vocabulary: a brand-new viral product (e.g. "Labubu") matches no keyword
and scores ~0, even though the live sources surfaced it. This node fixes that by
asking Gemini to judge each *already-collected* topic with an open vocabulary::

    is this a physical product Indians would buy online right now (including
    fan merch for current events), how strong is the buy-intent, what category?

It runs **after** ``score_rank`` and overrides the keyword ``product_intent_score``
and ``suggested_categories`` for topics the model recognises, then re-ranks.

Design contract (fail-soft, no credentials required to import/run):

* ``EL_AI_SCORING_ENABLED`` (default "true") gates the whole node.
* Requires ``GOOGLE_SERVICE_ACCOUNT_JSON``; absent → no-op, keyword scores kept.
* Topics are batched (``EL_AI_SCORING_BATCH``) and capped
  (``EL_AI_SCORING_MAX_TOPICS``) to bound cost.
* A **dollar cost cap** (``EL_AI_SCORING_MAX_COST_USD``) stops issuing API calls
  once an estimated running total would exceed the budget. Default: $0.05/run.
* Provider creation, each batch call, and JSON parsing are individually
  wrapped: any failure leaves the affected topics on their keyword scores.
* ``provider`` is injectable for tests (anything with ``.generate(system, user)``).
"""
from __future__ import annotations

import json
import re

from el import config
from el.logger import get_logger
from el.nodes._score_config import CATEGORIES

log = get_logger(__name__)

_DEFAULT_BATCH = 40
_DEFAULT_MAX_TOPICS = 120
_DEFAULT_MODEL = "gemini-2.5-pro-exp-03-25"
_DEFAULT_MAX_COST_USD = 0.05

# Model pricing per 1M tokens (Gemini 2.5 Flash, Vertex pricing as of 2025).
_INPUT_COST_PER_M = 0.15
_OUTPUT_COST_PER_M = 0.60

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


# ── helpers ──────────────────────────────────────────────────────────────────


def _strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", (text or "").strip())


def _int_env(name: str, default: int) -> int:
    raw = config.get(name)
    try:
        val = int(raw)  # type: ignore[arg-type]
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    raw = config.get(name)
    try:
        val = float(raw)  # type: ignore[arg-type]
        return val if val > 0.0 else default
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


def _estimate_batch_cost(
    batch_size: int,
    model: str = _DEFAULT_MODEL,
) -> float:
    """Rough dollar estimate for one model call over *batch_size* topics.

    Uses a coarse heuristic (~4 chars ≈ 1 token) because we don't have a real
    tokeniser.  Gemini pricing varies by model; only ``gemini-2.5-pro-exp-03-25`` is
    recognised by name — everything else falls back to the same rate.
    """
    # Input: system prompt (~250 tokens) + user prompt (~10 tokens/topic)
    est_input_tokens = int(250 + batch_size * 10)
    # Output: ~50 tokens per topic (JSON envelope)
    est_output_tokens = int(batch_size * 50)

    input_cost = est_input_tokens / 1_000_000 * _INPUT_COST_PER_M
    output_cost = est_output_tokens / 1_000_000 * _OUTPUT_COST_PER_M
    return round(input_cost + output_cost, 6)


# ── public API ───────────────────────────────────────────────────────────────



def _call_with_retry(provider, system: str, prompt: str, max_retries: int = 2) -> str:
    """Call provider.generate with simple retry + exponential backoff."""
    import time as _time
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return provider.generate(system, prompt)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = (attempt + 1) * 2.0
                log.warning(
                    "ai_score_trends: retry %d/%d after %s in %.1fs",
                    attempt + 1, max_retries, exc, wait,
                )
                _time.sleep(wait)
    raise last_exc  # type: ignore[misc]


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
    max_cost = _float_env("EL_AI_SCORING_MAX_COST_USD", _DEFAULT_MAX_COST_USD)

    scored_idx = list(range(min(len(trends), max_topics)))
    # str.replace (not .format) — _SYSTEM contains literal JSON braces.
    system = _SYSTEM.replace("{cats}", ", ".join(CATEGORIES.keys()))

    ai_count = 0
    cumulative_cost = 0.0
    for start in range(0, len(scored_idx), batch_size):
        window = scored_idx[start : start + batch_size]
        window_size = len(window)

        # ---- cost gate ----------------------------------------------------
        batch_cost = _estimate_batch_cost(window_size, model_hint)
        if cumulative_cost + batch_cost > max_cost:
            remaining = len(scored_idx) - start
            log.info(
                "ai_score_trends: cost cap $%.4f reached "
                "(estimated $%.4f so far, skipping %d remaining topics)",
                max_cost, cumulative_cost + batch_cost, remaining,
            )
            # Record the last batch that DID run (if any) before breaking.
            if ai_count == 0:
                log.warning("ai_score_trends: cost cap $%.4f too low — no topics enriched", max_cost)
            break

        batch = [(i, trends[i].get("topic", "")) for i in window]
        try:
            raw = _call_with_retry(provider, system, _build_user_prompt(batch))
        except Exception as exc:
            log.warning(
                "ai_score_trends: batch %d call failed (%s) — keyword scores kept",
                start, exc,
            )
            continue

        # Only accumulate cost AFTER a successful call
        cumulative_cost += batch_cost

        results = _parse_response(raw)
        # Prompt lines are numbered by GLOBAL index, so the model echoes the
        # global "i" — look results up by global_i. (Using local_i silently
        # dropped every batch after the first, where global_i != local_i.)
        for global_i, _topic in batch:
            res = results.get(global_i)
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
    meta["ai_cost_estimate_usd"] = round(cumulative_cost, 6)
    log.info(
        "ai_score_trends: enriched %d/%d topics (est. cost $%.6f) via AI",
        ai_count, len(trends), cumulative_cost,
    )
    return ctx
