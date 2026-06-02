"""Tests for el/sources/reddit_source.py."""
from __future__ import annotations

from el.sources import Source, TrendCandidate
from el.sources import reddit_source as src

_NOW = 1_000_000.0


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"data": {"children": []}}

    def json(self):
        return self._payload


def _payload(*posts):
    return {
        "data": {
            "children": [
                {"data": post}
                for post in posts
            ]
        }
    }


def _post(title, score=100, age_hours=1.0, ratio=0.95, url="https://example.test/item"):
    return {
        "title": title,
        "score": score,
        "created_utc": _NOW - age_hours * 3600,
        "upvote_ratio": ratio,
        "url": url,
        "permalink": "/r/india/comments/abc/test/",
    }


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "reddit"
    assert isinstance(src, Source)


def test_happy_path_and_velocity(monkeypatch):
    monkeypatch.setattr(src.time, "time", lambda: _NOW)
    monkeypatch.setattr(
        src.requests,
        "get",
        lambda *a, **k: _Resp(payload=_payload(_post("Viral Labubu toy restock", score=500))),
    )

    out = src.fetch_trends({})

    assert out
    c = out[0]
    assert isinstance(c, TrendCandidate)
    assert c.title == "Viral Labubu toy restock"
    assert c.source_id == "reddit"
    assert 0.0 <= c.velocity <= 1.0
    assert c.raw_payload["subreddit"] == "india"
    assert c.raw_payload["url"].startswith("https://www.reddit.com/r/india/")


def test_low_score_posts_filtered(monkeypatch):
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _Resp(payload=_payload(
        _post("noise", score=src.MIN_SCORE - 1),
    )))

    assert src.fetch_trends({}) == []


def test_per_subreddit_exception_isolated(monkeypatch):
    monkeypatch.setattr(src.time, "time", lambda: _NOW)

    def _get(url, **kwargs):
        if "/r/india/" in url:
            return _Resp(payload=_payload(_post("good", score=100)))
        raise RuntimeError("sub exploded")

    monkeypatch.setattr(src.requests, "get", _get)
    out = src.fetch_trends({})

    assert any(c.title == "good" for c in out)


def test_non_200_is_fail_soft(monkeypatch):
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _Resp(status_code=403))
    assert src.fetch_trends({}) == []


def test_json_parse_error_is_fail_soft(monkeypatch):
    class _BadResp:
        status_code = 200

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _BadResp())
    assert src.fetch_trends({}) == []


def test_dedupes_titles_across_subreddits(monkeypatch):
    monkeypatch.setattr(
        src.requests,
        "get",
        lambda *a, **k: _Resp(payload=_payload(_post("same", score=100))),
    )

    assert [c.title for c in src.fetch_trends({})] == ["same"]
