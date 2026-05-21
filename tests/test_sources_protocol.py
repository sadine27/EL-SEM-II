"""Tests for el/sources/__init__.py — Source protocol + TrendCandidate."""
from __future__ import annotations

import dataclasses

import pytest

from el.sources import Source, TrendCandidate


def test_trend_candidate_is_frozen():
    c = TrendCandidate(title="t", source_id="x", raw_payload={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.title = "modified"  # type: ignore[misc]


def test_trend_candidate_default_fields():
    c = TrendCandidate(title="t", source_id="x", raw_payload={"k": "v"})
    assert c.region == "IN"
    assert c.score_hint is None
    assert c.fetched_at is None
    assert c.raw_payload == {"k": "v"}


def test_trend_candidate_default_raw_payload_is_empty_dict():
    c = TrendCandidate(title="t", source_id="x")
    assert c.raw_payload == {}


def test_trend_candidate_equality_by_value():
    a = TrendCandidate(title="t", source_id="x", raw_payload={"k": 1})
    b = TrendCandidate(title="t", source_id="x", raw_payload={"k": 1})
    assert a == b


def test_source_protocol_runtime_check_recognizes_conforming_class():
    class GoodSource:
        SOURCE_ID = "good"
        def fetch_trends(self, ctx):
            return []
    assert isinstance(GoodSource(), Source)


def test_source_protocol_runtime_check_rejects_missing_method():
    class BadSource:
        SOURCE_ID = "bad"
    assert not isinstance(BadSource(), Source)
