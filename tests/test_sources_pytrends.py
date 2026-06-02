"""Tests for el/sources/pytrends_source.py."""
from __future__ import annotations

import sys
import types

from el.sources import Source, TrendCandidate
from el.sources import pytrends_source as src


# ── numpy-free fakes mimicking the slices of the pandas API the source touches ──
class _Arr(list):
    def mean(self):
        return sum(self) / len(self) if self else 0.0

    def tolist(self):
        return list(self)

    def __getitem__(self, k):
        r = list.__getitem__(self, k)
        return _Arr(r) if isinstance(k, slice) else r


class _Vals:
    def __init__(self, arr):
        self._a = arr

    def astype(self, _t):
        return _Arr(float(x) for x in self._a)


class _Series:
    def __init__(self, arr):
        self.values = _Vals(arr)


class _DF:
    def __init__(self, data):
        self._d = data
        self.empty = not data
        self.columns = list(data)

    def __getitem__(self, key):
        if isinstance(key, int):       # df[0] -> first column as a list-like
            return _Arr(self._d[self.columns[key]])
        return _Series(self._d[key])


class _RT:
    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        return enumerate(self._rows)


_RISING = [1, 1, 1, 1, 1, 50, 60, 70, 80, 90, 100, 100, 100, 100]


class _FakeClient:
    def __init__(self):
        self._last_kw = []

    def trending_searches(self, pn=None):
        return _DF({0: ["Drone X", "Air Fryer Deal"]})  # df[0].tolist()

    def realtime_trending_searches(self, pn=None):
        return _RT([{"title": "RCB jersey trend"}])

    def build_payload(self, keywords, timeframe=None, geo=None):
        self._last_kw = keywords

    def interest_over_time(self):
        return _DF({kw: _RISING for kw in self._last_kw})


def _install_pytrends(monkeypatch):
    mod = types.ModuleType("pytrends")
    req = types.ModuleType("pytrends.request")
    req.TrendReq = object
    mod.request = req
    monkeypatch.setitem(sys.modules, "pytrends", mod)
    monkeypatch.setitem(sys.modules, "pytrends.request", req)
    monkeypatch.setattr(src.time, "sleep", lambda *_a, **_k: None)


def test_source_id_and_protocol():
    assert src.SOURCE_ID == "pytrends"
    assert isinstance(src, Source)


def test_import_error_is_fail_soft(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytrends", None)
    monkeypatch.setitem(sys.modules, "pytrends.request", None)
    assert src.fetch_trends({}) == []


def test_happy_path_daily_and_realtime(monkeypatch):
    _install_pytrends(monkeypatch)
    monkeypatch.setattr(src, "_make_client", lambda: _FakeClient())
    out = src.fetch_trends({})
    assert all(isinstance(c, TrendCandidate) for c in out)
    titles = {c.title for c in out}
    assert {"Drone X", "Air Fryer Deal", "RCB jersey trend"} <= titles
    # Realtime candidates carry the dedicated source_id + moderate velocity.
    rt = [c for c in out if c.title == "RCB jersey trend"][0]
    assert rt.source_id == "pytrends_realtime"
    assert rt.velocity == 0.5
    # Daily candidates got a computed (positive) velocity from the rising series.
    daily = [c for c in out if c.title == "Drone X"][0]
    assert daily.velocity is not None and daily.velocity > 0


def test_unexpected_error_is_fail_soft(monkeypatch):
    _install_pytrends(monkeypatch)

    def boom():
        raise RuntimeError("client blew up")

    monkeypatch.setattr(src, "_make_client", boom)
    assert src.fetch_trends({}) == []


# ── _velocity_batch unit tests ──────────────────────────────────────────────
def test_velocity_batch_rising():
    client = _FakeClient()
    client._last_kw = ["x"]
    out = src._velocity_batch(client, ["x"])
    assert out["x"] > 0


def test_velocity_batch_missing_column_is_none():
    class _C:
        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return _DF({"other": _RISING})

    assert src._velocity_batch(_C(), ["x"]) == {"x": None}


def test_velocity_batch_empty_df_all_none():
    class _C:
        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return _DF({})

    assert src._velocity_batch(_C(), ["a", "b"]) == {"a": None, "b": None}


def test_velocity_batch_exception_all_none():
    class _C:
        def build_payload(self, *a, **k):
            raise RuntimeError("boom")

        def interest_over_time(self):
            raise AssertionError("should not reach")

    assert src._velocity_batch(_C(), ["a"]) == {"a": None}


def test_velocity_batch_zero_baseline_branch():
    # First-5 baseline < 1 with positive recent -> 0.5 sentinel.
    class _C:
        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return _DF({"x": [0, 0, 0, 0, 0, 0, 0, 0, 5, 9, 9, 9]})

    assert src._velocity_batch(_C(), ["x"])["x"] == 0.5


def test_velocity_batch_too_few_points_is_none():
    class _C:
        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return _DF({"x": [1, 2, 3]})  # < 10 points

    assert src._velocity_batch(_C(), ["x"]) == {"x": None}


def test_make_client_constructs_trendreq(monkeypatch):
    captured = {}

    def _TrendReq(**kwargs):
        captured.update(kwargs)
        return "client-obj"

    mod = types.ModuleType("pytrends")
    req = types.ModuleType("pytrends.request")
    req.TrendReq = _TrendReq
    mod.request = req
    monkeypatch.setitem(sys.modules, "pytrends", mod)
    monkeypatch.setitem(sys.modules, "pytrends.request", req)
    assert src._make_client() == "client-obj"
    assert captured["hl"] == "en-IN"


def test_daily_and_realtime_inner_exceptions_are_isolated(monkeypatch):
    _install_pytrends(monkeypatch)

    class _C:
        def trending_searches(self, pn=None):
            raise RuntimeError("daily down")

        def realtime_trending_searches(self, pn=None):
            raise RuntimeError("realtime down")

    monkeypatch.setattr(src, "_make_client", lambda: _C())
    # Both inner calls fail but fetch_trends still returns cleanly (no candidates).
    assert src.fetch_trends({}) == []


def test_realtime_entitynames_list_is_joined(monkeypatch):
    _install_pytrends(monkeypatch)

    class _C:
        def trending_searches(self, pn=None):
            return _DF({0: []})

        def realtime_trending_searches(self, pn=None):
            return _RT([{"entityNames": ["Virat", "Kohli"]}])

        def build_payload(self, *a, **k):
            pass

        def interest_over_time(self):
            return _DF({})

    monkeypatch.setattr(src, "_make_client", lambda: _C())
    out = src.fetch_trends({})
    assert any(c.title == "Virat Kohli" for c in out)
