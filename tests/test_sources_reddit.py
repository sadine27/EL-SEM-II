"""Tests for el/sources/reddit_source.py."""
from __future__ import annotations

import sys
import types

from el.sources import Source, TrendCandidate
from el.sources import reddit_source as src

_NOW = 1_000_000.0


class _Post:
    def __init__(self, title, score, age_hours=1.0, ratio=0.95, url="u"):
        self.title = title
        self.score = score
        self.created_utc = _NOW - age_hours * 3600
        self.upvote_ratio = ratio
        self.url = url


class _Subreddit:
    def __init__(self, posts):
        self._posts = posts

    def hot(self, limit):
        return self._posts[:limit]


def _install_praw(monkeypatch, posts_by_sub):
    class _Reddit:
        def __init__(self, **kw):
            pass

        def subreddit(self, name):
            return _Subreddit(posts_by_sub.get(name, []))

    mod = types.ModuleType("praw")
    mod.Reddit = _Reddit
    monkeypatch.setitem(sys.modules, "praw", mod)


def _creds(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda name, *a, **k: {
        "REDDIT_CLIENT_ID": "id", "REDDIT_CLIENT_SECRET": "sec",
    }.get(name))
    monkeypatch.setattr(src.time, "time", lambda: _NOW)


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "reddit"
    assert isinstance(src, Source)


def test_skips_when_no_creds(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: None)
    assert src.fetch_trends({}) == []


def test_import_error_is_fail_soft(monkeypatch):
    _creds(monkeypatch)
    monkeypatch.setitem(sys.modules, "praw", None)  # force ImportError
    assert src.fetch_trends({}) == []


def test_happy_path_and_velocity(monkeypatch):
    _creds(monkeypatch)
    _install_praw(monkeypatch, {"india": [_Post("Viral Labubu toy restock", score=500)]})
    out = src.fetch_trends({})
    assert out
    c = out[0]
    assert isinstance(c, TrendCandidate)
    assert c.title == "Viral Labubu toy restock"
    assert c.source_id == "reddit"
    assert 0.0 <= c.velocity <= 1.0
    assert c.raw_payload["subreddit"] == "india"


def test_low_score_posts_filtered(monkeypatch):
    _creds(monkeypatch)
    _install_praw(monkeypatch, {"india": [_Post("noise", score=src.MIN_SCORE - 1)]})
    assert src.fetch_trends({}) == []


def test_per_subreddit_exception_isolated(monkeypatch):
    _creds(monkeypatch)

    class _BoomReddit:
        def __init__(self, **kw):
            pass

        def subreddit(self, name):
            if name == "india":
                return _Subreddit([_Post("good", score=100)])
            raise RuntimeError("sub exploded")

    mod = types.ModuleType("praw")
    mod.Reddit = _BoomReddit
    monkeypatch.setitem(sys.modules, "praw", mod)
    out = src.fetch_trends({})
    # The one healthy subreddit still yields a candidate despite others raising.
    assert any(c.title == "good" for c in out)


def test_reddit_client_construction_failure_is_fail_soft(monkeypatch):
    _creds(monkeypatch)

    class _BoomReddit:
        def __init__(self, **kw):
            raise RuntimeError("auth failed")

    mod = types.ModuleType("praw")
    mod.Reddit = _BoomReddit
    monkeypatch.setitem(sys.modules, "praw", mod)
    assert src.fetch_trends({}) == []
