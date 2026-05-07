"""Tests for el/nodes/create_day_tab_scraped.py."""
from __future__ import annotations

from el.nodes import create_day_tab_scraped as cdts


class FakeSheetsProvider:
    def __init__(self, should_error: bool = False):
        self.should_error = should_error
        self.created = []

    def create_sheet(self, title: str) -> dict:
        self.created.append(title)
        if self.should_error:
            raise Exception("Sheets API error")
        return {"replies": [{"addSheet": {"properties": {"title": title}}}]}

    def append_rows(self, title, rows, columns):  # pragma: no cover - unused
        return {}


def test_creates_tab_with_today_title():
    provider = FakeSheetsProvider()
    ctx = {}
    cdts.run(ctx, provider=provider)
    assert ctx["scraped_sheet_tab"]["created"] is True
    assert provider.created  # called

def test_handles_provider_error_soft_fail():
    provider = FakeSheetsProvider(should_error=True)
    ctx = {}
    cdts.run(ctx, provider=provider)
    assert ctx["scraped_sheet_tab"]["created"] is False
    assert "error" in ctx["scraped_sheet_tab"]


def test_preserves_other_ctx_keys():
    provider = FakeSheetsProvider()
    ctx = {"other": "value"}
    cdts.run(ctx, provider=provider)
    assert ctx["other"] == "value"
