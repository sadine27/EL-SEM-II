"""Tests for el/sources/youtube.py — protocol-conforming wrapper."""
from __future__ import annotations

from el.sources import Source, TrendCandidate
from el.sources import youtube as youtube_source


def test_youtube_source_id():
    assert youtube_source.SOURCE_ID == "youtube"


def test_youtube_module_satisfies_source_protocol():
    # Modules support runtime_checkable Protocol as long as the right attributes exist.
    assert isinstance(youtube_source, Source)


def test_fetch_trends_wraps_youtube_items_as_trend_candidates(monkeypatch):
    fake_items = [
        {"id": "vid1", "snippet": {"title": "Wireless earbuds review", "channelTitle": "TechCh"}},
        {"id": "vid2", "snippet": {"title": "Best mixer grinders 2026", "channelTitle": "HomeCh"}},
    ]

    def fake_run(ctx):
        ctx["youtube_items"] = fake_items
        ctx["youtube_trending_result"] = {"ok": True, "count": len(fake_items)}
        return ctx

    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    candidates = youtube_source.fetch_trends({})
    assert len(candidates) == 2
    for c, item in zip(candidates, fake_items):
        assert isinstance(c, TrendCandidate)
        assert c.title == item["snippet"]["title"]
        assert c.source_id == "youtube"
        assert c.raw_payload == item


def test_fetch_trends_returns_empty_on_failure(monkeypatch):
    def fake_run(ctx):
        ctx["youtube_items"] = []
        ctx["youtube_trending_result"] = {"ok": False, "error": "boom"}
        return ctx
    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    assert youtube_source.fetch_trends({}) == []


def test_fetch_trends_skips_items_without_title(monkeypatch):
    def fake_run(ctx):
        ctx["youtube_items"] = [
            {"id": "x", "snippet": {}},
            {"id": "y", "snippet": {"title": "kept"}},
        ]
        return ctx
    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    candidates = youtube_source.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].title == "kept"


def test_fetch_trends_swallows_run_exception(monkeypatch):
    def boom(ctx):
        raise RuntimeError("network exploded")
    monkeypatch.setattr("el.nodes.youtube_trending.run", boom)
    assert youtube_source.fetch_trends({}) == []


def test_fetch_trends_handles_non_dict_items(monkeypatch):
    def fake_run(ctx):
        ctx["youtube_items"] = ["not a dict", None, {"snippet": {"title": "ok"}}]
        return ctx
    monkeypatch.setattr("el.nodes.youtube_trending.run", fake_run)
    candidates = youtube_source.fetch_trends({})
    assert len(candidates) == 1
    assert candidates[0].title == "ok"
