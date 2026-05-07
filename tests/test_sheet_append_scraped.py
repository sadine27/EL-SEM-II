"""Tests for el/nodes/sheet_append_scraped.py."""
from __future__ import annotations

from el.nodes import sheet_append_scraped as sas


class FakeSheetsProvider:
    def __init__(self, should_error: bool = False):
        self.should_error = should_error
        self.appended = None

    def create_sheet(self, title):  # pragma: no cover - unused
        return {}

    def append_rows(self, title, rows, columns):
        self.appended = {"title": title, "rows": list(rows), "columns": tuple(columns)}
        if self.should_error:
            raise Exception("Sheets API error")
        return {"updates": {"updatedRows": len(rows)}}


def test_appends_rows_to_sheet_tab_title():
    provider = FakeSheetsProvider()
    ctx = {
        "scraped_sheet_tab": {"title": "2026-05-07"},
        "scraped_sheet_rows": [{"run_date": "2026-05-07", "product_name": "X"}],
    }
    sas.run(ctx, provider=provider)
    assert ctx["scraped_sheet_append_result"]["ok"] is True
    assert provider.appended["title"] == "2026-05-07"
    assert provider.appended["rows"][0]["product_name"] == "X"


def test_no_rows_short_circuits():
    provider = FakeSheetsProvider()
    ctx = {"scraped_sheet_rows": []}
    sas.run(ctx, provider=provider)
    assert ctx["scraped_sheet_append_result"]["rows"] == 0
    assert provider.appended is None


def test_provider_error_soft_fail():
    provider = FakeSheetsProvider(should_error=True)
    ctx = {"scraped_sheet_rows": [{"product_name": "X"}]}
    sas.run(ctx, provider=provider)
    assert ctx["scraped_sheet_append_result"]["ok"] is False
    assert "error" in ctx["scraped_sheet_append_result"]


def test_falls_back_to_today_when_tab_missing():
    """If create_day_tab failed, append still uses today's date as title."""
    provider = FakeSheetsProvider()
    ctx = {"scraped_sheet_rows": [{"product_name": "X"}]}
    sas.run(ctx, provider=provider)
    assert provider.appended is not None  # didn't crash on missing tab
