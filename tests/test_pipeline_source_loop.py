"""Tests for el/pipeline.py source-loop introduced by SP2."""
from __future__ import annotations

import pytest

from el import pipeline
from el.sources import TrendCandidate


def test_load_enabled_sources_default(monkeypatch):
    # Fenix engine: unset EL_SOURCES_ENABLED now enables every shipped source so
    # nothing trending is missed. Key-gated sources fail soft when creds are absent.
    monkeypatch.delenv("EL_SOURCES_ENABLED", raising=False)
    sources = pipeline._load_enabled_sources()
    assert [s.SOURCE_ID for s in sources] == pipeline._DEFAULT_SOURCES
    assert "youtube" in pipeline._DEFAULT_SOURCES
    assert "google_news_india" in pipeline._DEFAULT_SOURCES


def test_default_sources_all_resolve_in_registry():
    # Every name in the default list must map to a real, loadable source module.
    for name in pipeline._DEFAULT_SOURCES:
        assert name in pipeline._SOURCE_REGISTRY


def test_load_enabled_sources_explicit_list(monkeypatch):
    monkeypatch.setenv("EL_SOURCES_ENABLED", "youtube,shopify_competitor")
    sources = pipeline._load_enabled_sources()
    assert [s.SOURCE_ID for s in sources] == ["youtube", "shopify_competitor"]


def test_load_enabled_sources_unknown_name_skipped(monkeypatch):
    monkeypatch.setenv("EL_SOURCES_ENABLED", "youtube,doesnotexist")
    sources = pipeline._load_enabled_sources()
    # Unknown skipped, youtube kept.
    assert [s.SOURCE_ID for s in sources] == ["youtube"]


def test_load_enabled_sources_preserves_order(monkeypatch):
    monkeypatch.setenv("EL_SOURCES_ENABLED", "shopify_competitor,youtube")
    sources = pipeline._load_enabled_sources()
    assert [s.SOURCE_ID for s in sources] == ["shopify_competitor", "youtube"]


def test_load_enabled_sources_empty_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("EL_SOURCES_ENABLED", "")
    sources = pipeline._load_enabled_sources()
    assert [s.SOURCE_ID for s in sources] == pipeline._DEFAULT_SOURCES


def test_fetch_all_sources_aggregates(monkeypatch):
    class _Src:
        def __init__(self, sid, items):
            self.SOURCE_ID = sid
            self._items = items
        def fetch_trends(self, ctx):
            return [TrendCandidate(title=t, source_id=self.SOURCE_ID) for t in self._items]

    a = _Src("a", ["a1", "a2"])
    b = _Src("b", ["b1"])
    out = pipeline._fetch_all_sources([a, b], {})
    assert [c.title for c in out] == ["a1", "a2", "b1"]


def test_fetch_all_sources_isolates_per_source_failures(monkeypatch):
    class _GoodSrc:
        SOURCE_ID = "good"
        def fetch_trends(self, ctx):
            return [TrendCandidate(title="ok", source_id="good")]

    class _BadSrc:
        SOURCE_ID = "bad"
        def fetch_trends(self, ctx):
            raise RuntimeError("source crashed")

    out = pipeline._fetch_all_sources([_BadSrc(), _GoodSrc()], {})
    assert len(out) == 1
    assert out[0].title == "ok"
