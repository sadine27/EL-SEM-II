"""Tests for el/sources/amazon_in_source.py."""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import requests

from el.sources import Source, TrendCandidate
from el.sources import amazon_in_source as src


class _El:
    def __init__(self, text):
        self._t = text

    def get_text(self, strip=False):
        return self._t.strip() if strip else self._t


class _Soup:
    """Maps CSS selector -> list of element texts; mimics BeautifulSoup.select."""

    def __init__(self, mapping):
        self._mapping = mapping

    def select(self, sel):
        return [_El(t) for t in self._mapping.get(sel, [])]


def _install_bs4(monkeypatch, soup):
    mod = types.ModuleType("bs4")
    mod.BeautifulSoup = lambda html, parser=None: soup
    monkeypatch.setitem(sys.modules, "bs4", mod)


def _resp(status: int = 200, text: str = "<html></html>"):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.text = text
    return r


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "amazon_in_movers"
    assert isinstance(src, Source)


def test_import_error_is_fail_soft(monkeypatch):
    # Ensure bs4 is treated as missing -> fetch returns [].
    monkeypatch.setitem(sys.modules, "bs4", None)
    assert src.fetch_trends({}) == []


def test_extract_uses_selector_fallback(monkeypatch):
    first_sel = src._SELECTORS[0]
    third_sel = src._SELECTORS[2]
    # First selector finds nothing; a later one matches.
    soup = _Soup({first_sel: [], third_sel: ["Cordless Drill", "Yoga Mat"]})
    _install_bs4(monkeypatch, soup)
    names = src._extract_product_names("<html/>")
    assert names == ["Cordless Drill", "Yoga Mat"]


def test_happy_path_sets_rising_velocity(monkeypatch):
    soup = _Soup({src._SELECTORS[0]: ["Air Fryer XL"]})
    _install_bs4(monkeypatch, soup)
    with patch.object(src.requests.Session, "get", return_value=_resp()):
        out = src.fetch_trends({})
    assert out
    assert all(isinstance(c, TrendCandidate) for c in out)
    c = out[0]
    assert c.source_id == "amazon_in_movers"
    assert c.velocity == 0.65
    assert "amazon_category" in c.raw_payload


def test_non_200_skipped(monkeypatch):
    _install_bs4(monkeypatch, _Soup({}))
    with patch.object(src.requests.Session, "get", return_value=_resp(status=503)):
        assert src.fetch_trends({}) == []


def test_exception_is_fail_soft(monkeypatch):
    _install_bs4(monkeypatch, _Soup({}))
    with patch.object(src.requests.Session, "get", side_effect=requests.Timeout("x")):
        assert src.fetch_trends({}) == []
