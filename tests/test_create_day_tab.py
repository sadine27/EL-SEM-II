"""Tests for el/nodes/create_day_tab.py."""
from __future__ import annotations

from el.nodes import create_day_tab as cdt


class FakeProvider:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"ok": True}
        self.error = error
        self.titles: list[str] = []

    def create_sheet(self, title: str) -> dict:
        self.titles.append(title)
        if self.error:
            raise self.error
        return self.response


def test_create_day_tab_calls_provider_and_stores_result():
    provider = FakeProvider({"sheetId": 123})
    ctx = cdt.run({}, provider=provider)
    title = provider.titles[0]
    assert len(title) == 10 and title[4] == "-" and title[7] == "-"
    assert ctx["sheet_tab"] == {
        "title": title,
        "created": True,
        "response": {"sheetId": 123},
    }


def test_create_day_tab_continue_on_fail_shape():
    ctx = cdt.run({}, provider=FakeProvider(error=RuntimeError("boom")))
    assert ctx["sheet_tab"]["created"] is False
    assert ctx["sheet_tab"]["error"] == "boom"


def test_create_day_tab_idempotent_when_tab_already_exists():
    ctx = cdt.run({}, provider=FakeProvider(error=RuntimeError("already exists")))
    assert ctx["sheet_tab"]["created"] is False
    assert ctx["sheet_tab"]["existed"] is True
    assert "error" not in ctx["sheet_tab"]
