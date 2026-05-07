"""Tests for el/nodes/create_curated_picks_tab.py."""
from __future__ import annotations

from el.nodes import create_curated_picks_tab as ccpt


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


def test_create_curated_picks_tab_calls_provider_with_fixed_title():
    provider = FakeProvider({"sheetId": 456})
    ctx = ccpt.run({}, provider=provider)
    assert provider.titles == ["Curated Picks"]
    assert ctx["curated_picks_tab"] == {
        "title": "Curated Picks",
        "created": True,
        "response": {"sheetId": 456},
    }


def test_create_curated_picks_tab_continue_on_fail_shape():
    ctx = ccpt.run({}, provider=FakeProvider(error=RuntimeError("already exists")))
    assert ctx["curated_picks_tab"] == {
        "title": "Curated Picks",
        "created": False,
        "error": "already exists",
    }
