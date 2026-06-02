"""Tests for el/sources/rss_india_source.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from el.sources import Source, TrendCandidate
from el.sources import rss_india_source as src


def _resp(text: str, status: int = 200):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.text = text
    return r


_XML = (
    "<rss><channel><title>Channel Name</title>"
    "<item><title><![CDATA[New Air Fryer Deal]]></title></item>"
    "<item><title>Best Power Bank 2026</title></item>"
    "<item><title>ok</title></item>"  # too short (<=5 chars) -> skipped
    "</channel></rss>"
)


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "rss_india"
    assert isinstance(src, Source)


def test_parse_titles_skips_channel_and_short():
    titles = src._parse_titles(_XML)
    assert "Channel Name" not in titles
    assert "New Air Fryer Deal" in titles
    assert "Best Power Bank 2026" in titles
    assert "ok" not in titles


def test_happy_path_builds_candidates():
    with patch.object(src.requests, "get", return_value=_resp(_XML)):
        out = src.fetch_trends({})
    assert out, "expected candidates"
    assert all(isinstance(c, TrendCandidate) for c in out)
    assert all(c.source_id.startswith("rss_india:") for c in out)


def test_dedupes_across_feeds():
    with patch.object(src.requests, "get", return_value=_resp(_XML)):
        out = src.fetch_trends({})
    titles = [c.title for c in out]
    assert len(titles) == len(set(titles))  # identical XML on every feed -> deduped


def test_non_200_skipped():
    with patch.object(src.requests, "get", return_value=_resp("", status=404)):
        assert src.fetch_trends({}) == []


def test_exception_is_fail_soft():
    with patch.object(src.requests, "get", side_effect=requests.Timeout("slow")):
        assert src.fetch_trends({}) == []
