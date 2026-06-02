"""Tests for el/sources/newsapi_source.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from el.sources import Source, TrendCandidate
from el.sources import newsapi_source as src


def _resp(payload: dict, status: int = 200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = payload
    return r


def _articles(*titles):
    return {"articles": [{"title": t, "url": f"http://x/{i}",
                          "source": {"name": "src"}} for i, t in enumerate(titles)]}


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "newsapi"
    assert isinstance(src, Source)


def test_skips_when_no_key(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: None)
    assert src.fetch_trends({}) == []


def test_happy_path_builds_candidates(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: "KEY")
    with patch.object(src.requests, "get", return_value=_resp(_articles("Trending Toy"))) as g:
        out = src.fetch_trends({})
    assert g.called
    assert all(isinstance(c, TrendCandidate) for c in out)
    assert any(c.title == "Trending Toy" and c.source_id == "newsapi" for c in out)


def test_dedupes_and_skips_removed(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: "KEY")
    payload = {"articles": [
        {"title": "Same Title", "url": "a", "source": {"name": "s"}},
        {"title": "Same Title", "url": "b", "source": {"name": "s"}},
        {"title": "[Removed]", "url": "c", "source": {"name": "s"}},
        {"title": "", "url": "d", "source": {"name": "s"}},
    ]}
    with patch.object(src.requests, "get", return_value=_resp(payload)):
        out = src.fetch_trends({})
    titles = [c.title for c in out]
    assert titles.count("Same Title") == 1
    assert "[Removed]" not in titles


def test_rate_limit_breaks_loop(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: "KEY")
    with patch.object(src.requests, "get", return_value=_resp({}, status=429)) as g:
        out = src.fetch_trends({})
    assert out == []
    assert g.call_count == 1  # broke after first 429 instead of looping all queries


def test_non_200_skipped(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: "KEY")
    with patch.object(src.requests, "get", return_value=_resp({}, status=500)):
        assert src.fetch_trends({}) == []


def test_exception_is_fail_soft(monkeypatch):
    monkeypatch.setattr(src.config, "get", lambda *a, **k: "KEY")
    with patch.object(src.requests, "get", side_effect=requests.ConnectionError("down")):
        assert src.fetch_trends({}) == []
