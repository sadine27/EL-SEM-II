"""Tests for el/nodes/ai_score_trends.py — the AI scoring brain."""
from __future__ import annotations

import json

from el.nodes import ai_score_trends as ai


class _Provider:
    """Fake LLMProvider: returns queued responses, records prompts."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        return self._responses.pop(0) if self._responses else "[]"


class _BoomProvider:
    def generate(self, system, user):
        raise RuntimeError("vertex down")


def _cfg(monkeypatch, **vals):
    monkeypatch.setattr(ai.config, "get", lambda name, default=None: vals.get(name, default))


def _payload(*topics):
    trends = []
    for i, topic in enumerate(topics):
        trends.append({
            "rank": i + 1, "topic": topic, "product_intent_score": 0.0,
            "suggested_categories": ["uncategorized"], "velocity": None,
            "cross_source_count": 1,
        })
    return {"ranked_payload": {"metadata": {"total_topics": len(trends)}, "trends": trends}}


def _ai_json(*objs):
    return json.dumps(list(objs))


# ── gating ──────────────────────────────────────────────────────────────────
def test_disabled_flag_is_noop(monkeypatch):
    _cfg(monkeypatch, EL_AI_SCORING_ENABLED="false")
    ctx = _payload("Labubu")
    out = ai.run(ctx, provider=_Provider(_ai_json({"i": 0, "intent": 0.9})))
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.0


def test_empty_trends_is_noop(monkeypatch):
    _cfg(monkeypatch)
    ctx = {"ranked_payload": {"metadata": {}, "trends": []}}
    assert ai.run(ctx, provider=_Provider()) is ctx


def test_no_creds_and_no_provider_keeps_keyword_scores(monkeypatch):
    # provider=None and GOOGLE_SERVICE_ACCOUNT_JSON absent -> no-op.
    _cfg(monkeypatch)
    ctx = _payload("Labubu")
    out = ai.run(ctx)
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.0
    assert "ai_scored" not in out["ranked_payload"]["trends"][0]


# ── happy path ────────────────────────────────────────────────────────────────
def test_ai_overrides_keyword_score_for_unknown_product(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("Labubu", "how to fix a phone")
    provider = _Provider(_ai_json(
        {"i": 0, "is_product": True, "intent": 0.92, "category": "Toys & Collectibles",
         "canonical_product": "Labubu blind box"},
        {"i": 1, "is_product": False, "intent": 0.0, "category": "none"},
    ))
    out = ai.run(ctx, provider=provider)
    trends = out["ranked_payload"]["trends"]
    labubu = [t for t in trends if t["topic"] == "Labubu"][0]
    assert labubu["product_intent_score"] == 0.92          # keyword 0.0 -> AI 0.92
    assert labubu["suggested_categories"] == ["toys_&_collectibles"]
    assert labubu["canonical_product"] == "Labubu blind box"
    assert labubu["is_product"] is True and labubu["ai_scored"] is True
    assert out["ranked_payload"]["metadata"]["ai_scored_count"] == 2


def test_rerank_after_ai_scores(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("low intent topic", "viral product")
    provider = _Provider(_ai_json(
        {"i": 0, "is_product": True, "intent": 0.10},
        {"i": 1, "is_product": True, "intent": 0.95},
    ))
    out = ai.run(ctx, provider=provider)
    trends = out["ranked_payload"]["trends"]
    assert trends[0]["topic"] == "viral product"   # higher AI intent floats to rank 1
    assert trends[0]["rank"] == 1


def test_is_product_false_without_intent_zeroes_score(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("political news")
    ctx["ranked_payload"]["trends"][0]["product_intent_score"] = 0.5  # keyword false positive
    provider = _Provider(_ai_json({"i": 0, "is_product": False}))
    out = ai.run(ctx, provider=provider)
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.0


# ── batching / cap ──────────────────────────────────────────────────────────
def test_batching_makes_multiple_calls(monkeypatch):
    _cfg(monkeypatch, EL_AI_SCORING_BATCH="2")
    ctx = _payload("a", "b", "c")
    # The prompt numbers topics by GLOBAL index, so the 2nd batch's lone topic is
    # echoed back as i=2 (not i=0). Every topic must still get enriched.
    provider = _Provider(
        _ai_json({"i": 0, "intent": 0.5}, {"i": 1, "intent": 0.5}),
        _ai_json({"i": 2, "intent": 0.5}),
    )
    out = ai.run(ctx, provider=provider)
    assert len(provider.calls) == 2  # ceil(3/2)
    trends = out["ranked_payload"]["trends"]
    assert all(t.get("ai_scored") for t in trends)              # no batch silently dropped
    assert out["ranked_payload"]["metadata"]["ai_scored_count"] == 3


def test_max_topics_cap(monkeypatch):
    _cfg(monkeypatch, EL_AI_SCORING_MAX_TOPICS="1")
    ctx = _payload("first", "second")
    provider = _Provider(_ai_json({"i": 0, "intent": 0.8}))
    out = ai.run(ctx, provider=provider)
    trends = out["ranked_payload"]["trends"]
    scored = [t for t in trends if t.get("ai_scored")]
    assert len(scored) == 1


# ── fail-soft ─────────────────────────────────────────────────────────────────
def test_malformed_json_keeps_keyword_scores(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("Labubu")
    out = ai.run(ctx, provider=_Provider("not json at all"))
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.0
    assert "ai_scored_count" not in out["ranked_payload"]["metadata"]


def test_provider_exception_keeps_keyword_scores(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("Labubu")
    out = ai.run(ctx, provider=_BoomProvider())
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.0


def test_prose_wrapped_json_is_recovered(monkeypatch):
    _cfg(monkeypatch)
    ctx = _payload("Labubu")
    wrapped = 'Here you go:\n[{"i": 0, "is_product": true, "intent": 0.7}]\nThanks!'
    out = ai.run(ctx, provider=_Provider(wrapped))
    assert out["ranked_payload"]["trends"][0]["product_intent_score"] == 0.7


# ── cost cap ──────────────────────────────────────────────────────────────────
def test_cost_cap_below_first_batch_skips_all(monkeypatch):
    """A cost cap too low for even one batch should skip all AI scoring."""
    _cfg(monkeypatch, EL_AI_SCORING_MAX_COST_USD="0.0000001")
    ctx = _payload("Labubu", "viral toy")
    provider = _Provider(
        _ai_json({"i": 0, "intent": 0.9}, {"i": 1, "intent": 0.8}),
    )
    out = ai.run(ctx, provider=provider)
    trends = out["ranked_payload"]["trends"]
    # Both should retain their keyword scores (0.0), not AI scores
    assert all(t.get("product_intent_score") == 0.0 for t in trends)
    assert all("ai_scored" not in t for t in trends)
    assert "ai_scored_count" not in out["ranked_payload"].get("metadata", {})


def test_cost_cap_after_first_batch_does_not_make_second_call(monkeypatch):
    """A cap that fits one batch but not two should only score the first batch."""
    # One batch of 40 topics costs ~$0.0013. Two batches ~$0.0026.
    # Setting cap to $0.002 allows batch 1 but blocks batch 2.
    _cfg(
        monkeypatch,
        EL_AI_SCORING_MAX_COST_USD="0.002",
        EL_AI_SCORING_BATCH="40",
        EL_AI_SCORING_MAX_TOPICS="80",
    )
    ctx = _payload(*[f"topic_{i}" for i in range(80)])
    # Return valid json for batch 1 (first 40 topics)
    payloads = [{"i": i, "intent": 0.5} for i in range(40)]
    provider = _Provider(_ai_json(*payloads))
    out = ai.run(ctx, provider=provider)
    assert len(provider.calls) == 1  # only batch 1 was called
    meta = out["ranked_payload"].get("metadata", {})
    assert meta.get("ai_scored_count", 0) == 40  # only first batch scored
    assert meta.get("ai_cost_estimate_usd", 0) > 0


def test_cost_estimate_in_metadata(monkeypatch):
    """Metadata should include an estimated cost after scoring."""
    _cfg(monkeypatch)
    ctx = _payload("Labubu")
    provider = _Provider(_ai_json({"i": 0, "intent": 0.9}))
    out = ai.run(ctx, provider=provider)
    meta = out["ranked_payload"].get("metadata", {})
    assert "ai_cost_estimate_usd" in meta
    assert isinstance(meta["ai_cost_estimate_usd"], float)
    assert meta["ai_cost_estimate_usd"] > 0


def test_default_cost_cap_allows_full_batch(monkeypatch):
    """Default cap of $0.05 should allow full batch of 120 topics."""
    _cfg(monkeypatch, EL_AI_SCORING_BATCH="120")  # one big batch
    ctx = _payload(*[f"topic_{i}" for i in range(120)])
    provider = _Provider(_ai_json(*[{"i": i, "intent": 0.5} for i in range(120)]))
    out = ai.run(ctx, provider=provider)
    meta = out["ranked_payload"].get("metadata", {})
    assert meta.get("ai_scored_count", 0) == 120
    assert meta.get("ai_cost_estimate_usd", 0) <= 0.05
