"""Tests for el/nodes/read_bcc_posteriors.py."""
from __future__ import annotations

from el.nodes import read_bcc_posteriors as rbp


class FakeSupabaseProvider:
    """Fake Supabase provider for testing."""

    def __init__(self, rows: list[dict] | None = None, should_error: bool = False):
        self.rows = rows or []
        self.should_error = should_error
        self.calls = []

    def select_rows(
        self,
        *,
        schema: str,
        table: str,
        filters: dict,
        select: str = "*",
        limit: int | None = None,
    ) -> list[dict]:
        self.calls.append({
            "schema": schema,
            "table": table,
            "filters": filters,
            "select": select,
        })
        if self.should_error:
            raise Exception("Supabase API error")
        return self.rows


def test_reads_posteriors_successfully():
    provider = FakeSupabaseProvider(
        rows=[
            {"category": "Marvel", "alpha": 5.0, "beta": 2.0},
            {"category": "DC", "alpha": 3.0, "beta": 1.0},
        ]
    )
    ctx = {}
    rbp.run(ctx, provider=provider)
    assert len(ctx["bcc_posteriors"]) == 2
    assert ctx["bcc_posteriors"][0]["category"] == "Marvel"
    assert ctx["bcc_posteriors"][0]["alpha"] == 5.0


def test_handles_empty_table():
    provider = FakeSupabaseProvider(rows=[])
    ctx = {}
    rbp.run(ctx, provider=provider)
    assert ctx["bcc_posteriors"] == []


def test_handles_provider_error():
    provider = FakeSupabaseProvider(should_error=True)
    ctx = {}
    rbp.run(ctx, provider=provider)
    assert ctx["bcc_posteriors"] == []


def test_preserves_other_context():
    provider = FakeSupabaseProvider(rows=[{"category": "Marvel", "alpha": 5, "beta": 2}])
    ctx = {"other_key": "other_value"}
    rbp.run(ctx, provider=provider)
    assert ctx["other_key"] == "other_value"
    assert len(ctx["bcc_posteriors"]) == 1
