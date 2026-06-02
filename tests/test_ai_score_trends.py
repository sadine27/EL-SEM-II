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
    provider = _Provider(
        _ai_json({"i": 0, "intent": 0.5}, {"i": 1, "intent": 0.5}),
        _ai_json({"i": 0, "intent": 0.5}),
    )
    ai.run(ctx, provider=provider)
    assert len(provider.calls) == 2  # ceil(3/2)


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
