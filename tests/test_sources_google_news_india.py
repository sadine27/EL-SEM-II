"""Tests for el/sources/google_news_india_source.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from el.sources import Source, TrendCandidate
from el.sources import google_news_india_source as src


def _resp(text: str, status: int = 200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.text = text
    return r


_XML = (
    "<rss><channel><title>Google News</title>"
    "<item><title>RCB jersey sells out after IPL win</title></item>"
    "<item><title>Labubu doll goes viral in India</title></item>"
    "</channel></rss>"
)


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "google_news_india"
    assert isinstance(src, Source)


def test_parse_titles_skips_channel():
    titles = src._parse_titles(_XML)
    assert "Google News" not in titles
    assert "RCB jersey sells out after IPL win" in titles


def test_happy_path_segments_topic_in_source_id():
    with patch.object(src.requests, "get", return_value=_resp(_XML)):
        out = src.fetch_trends({})
    assert out
    assert all(isinstance(c, TrendCandidate) for c in out)
    # source_id is "google_news_india:<topic_id>"
    assert all(c.source_id.startswith("google_news_india:") for c in out)
    assert any("Labubu" in c.title for c in out)


def test_dedupes_identical_titles_across_topics():
    with patch.object(src.requests, "get", return_value=_resp(_XML)):
        out = src.fetch_trends({})
    titles = [c.title for c in out]
    assert len(titles) == len(set(titles))


def test_non_200_skipped():
    with patch.object(src.requests, "get", return_value=_resp("", status=503)):
        assert src.fetch_trends({}) == []


def test_exception_is_fail_soft():
    with patch.object(src.requests, "get", side_effect=requests.ConnectionError("x")):
        assert src.fetch_trends({}) == []
