"""Tests for el/nodes/write_curated_picks.py."""
from __future__ import annotations

from el.nodes import create_curated_picks_tab as ccpt
from el.nodes import write_curated_picks as wcp


class FakeProvider:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"updates": {"updatedRows": 1}}
        self.error = error
        self.calls: list[tuple[str, list[dict], tuple[str, ...]]] = []

    def append_rows(self, title: str, rows: list[dict], columns: tuple[str, ...]) -> dict:
        self.calls.append((title, rows, columns))
        if self.error:
            raise self.error
        return self.response


def _pick() -> dict:
    return {
        "run_date": "2026-05-07",
        "rank": 1,
        "topic": "Wireless Earbuds",
        "opportunity_score": 8.5,
        "reason": "Strong buyer intent",
        "suggested_product_type": "Bluetooth earbuds",
        "target_audience": "Students",
        "search_query_in": "wireless earbuds india",
    }


def test_write_curated_picks_appends_curated_rows():
    rows = [_pick()]
    provider = FakeProvider({"ok": True})
    ctx = wcp.run({"curated_picks": rows}, provider=provider)
    assert provider.calls == [
        (ccpt.CURATED_PICKS_SHEET, rows, wcp.CURATED_PICK_COLUMNS)
    ]
    assert ctx["curated_picks_append_result"] == {
        "sheet_title": "Curated Picks",
        "rows": 1,
        "ok": True,
        "response": {"ok": True},
    }


def test_curated_pick_columns_match_n8n_schema_order():
    assert wcp.CURATED_PICK_COLUMNS == (
        "run_date",
        "rank",
        "topic",
        "opportunity_score",
        "reason",
        "suggested_product_type",
        "target_audience",
        "search_query_in",
    )


def test_write_curated_picks_skips_empty_rows():
    provider = FakeProvider()
    ctx = wcp.run({"curated_picks": []}, provider=provider)
    assert provider.calls == []
    assert ctx["curated_picks_append_result"] == {
        "sheet_title": "Curated Picks",
        "rows": 0,
        "ok": True,
    }


def test_write_curated_picks_continue_on_fail_shape():
    rows = [_pick()]
    ctx = wcp.run({"curated_picks": rows},
                  provider=FakeProvider(error=RuntimeError("quota")))
    assert ctx["curated_picks_append_result"] == {
        "sheet_title": "Curated Picks",
        "rows": 1,
        "ok": False,
        "error": "quota",
    }
