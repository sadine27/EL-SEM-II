"""Tests for el/nodes/write_rows_to_sheet.py."""
from __future__ import annotations

from el.nodes import prepare_sheet_rows as psr
from el.nodes import write_rows_to_sheet as wrs


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


def test_write_rows_to_sheet_appends_prepared_rows():
    rows = [{"run_date": "2026-05-07", "rank": 1}]
    provider = FakeProvider({"ok": True})
    ctx = wrs.run({"sheet_tab": {"title": "2026-05-07"}, "sheet_rows": rows},
                  provider=provider)
    assert provider.calls == [("2026-05-07", rows, psr.SHEET_ROW_COLUMNS)]
    assert ctx["sheet_append_result"] == {
        "sheet_title": "2026-05-07",
        "rows": 1,
        "ok": True,
        "response": {"ok": True},
    }


def test_write_rows_to_sheet_uses_today_without_sheet_tab():
    rows = [{"rank": 1}]
    provider = FakeProvider()
    ctx = wrs.run({"sheet_rows": rows}, provider=provider)
    title = provider.calls[0][0]
    assert len(title) == 10 and title[4] == "-" and title[7] == "-"
    assert ctx["sheet_append_result"]["sheet_title"] == title


def test_write_rows_to_sheet_skips_empty_rows():
    provider = FakeProvider()
    ctx = wrs.run({"sheet_tab": {"title": "2026-05-07"}, "sheet_rows": []},
                  provider=provider)
    assert provider.calls == []
    assert ctx["sheet_append_result"] == {
        "sheet_title": "2026-05-07",
        "rows": 0,
        "ok": True,
    }


def test_write_rows_to_sheet_continue_on_fail_shape():
    rows = [{"rank": 1}]
    ctx = wrs.run({"sheet_tab": {"title": "2026-05-07"}, "sheet_rows": rows},
                  provider=FakeProvider(error=RuntimeError("quota")))
    assert ctx["sheet_append_result"] == {
        "sheet_title": "2026-05-07",
        "rows": 1,
        "ok": False,
        "error": "quota",
    }
