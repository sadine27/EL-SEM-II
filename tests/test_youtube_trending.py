"""Tests for el/nodes/youtube_trending.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from el.nodes import youtube_trending as yt


def _fake_response(json_payload: dict, ok: bool = True, status_code: int = 200):
    resp = MagicMock(spec=requests.Response)
    resp.ok = ok
    resp.status_code = status_code
    resp.json.return_value = json_payload
    if not ok:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    else:
        resp.raise_for_status.return_value = None
    return resp


def test_run_calls_youtube_api_with_expected_params(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "TESTKEY")
    with patch.object(yt.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({"items": []})
        yt.run({})
        args, kwargs = mock_get.call_args
        assert args[0] == yt.YOUTUBE_VIDEOS_URL
        params = kwargs["params"]
        assert params["chart"] == "mostPopular"
        assert params["regionCode"] == "IN"
        assert params["maxResults"] == "50"
        assert params["part"] == "snippet"
        assert params["key"] == "TESTKEY"
        assert kwargs["timeout"] == yt.DEFAULT_TIMEOUT


def test_run_stores_items_in_ctx(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "TESTKEY")
    items = [{"id": "abc123", "snippet": {"title": "video"}}]
    with patch.object(yt.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({"items": items})
        ctx = yt.run({})
    assert ctx["youtube_items"] == items


def test_run_handles_empty_items(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "TESTKEY")
    with patch.object(yt.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({})
        ctx = yt.run({})
    assert ctx["youtube_items"] == []


def test_run_raises_on_http_error(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "TESTKEY")
    with patch.object(yt.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({}, ok=False, status_code=403)
        with pytest.raises(requests.HTTPError):
            yt.run({})


def test_run_requires_api_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        yt.run({})


def test_run_preserves_existing_ctx_keys(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "TESTKEY")
    with patch.object(yt.requests, "get") as mock_get:
        mock_get.return_value = _fake_response({"items": [{"id": "x"}]})
        ctx = yt.run({"prior": "value"})
    assert ctx["prior"] == "value"
    assert "youtube_items" in ctx
