"""Tests for el/nodes/update_bcc_posterior.py."""
from __future__ import annotations

from el.nodes import update_bcc_posterior as ubp


class FakeSupabaseProvider:
    """Fake Supabase provider for testing."""

    def __init__(self, rows: list[dict] | None = None, should_error: bool = False):
        self.rows = rows or []
        self.should_error = should_error
        self.select_calls = []
        self.upsert_calls = []

    def select_rows(
        self,
        *,
        schema: str,
        table: str,
        filters: dict,
        select: str = "*",
        limit: int | None = None,
    ) -> list[dict]:
        self.select_calls.append({
            "schema": schema,
            "table": table,
            "filters": filters,
        })
        if self.should_error:
            raise Exception("Supabase API error")
        return self.rows

    def upsert_rows(
        self,
        *,
        schema: str,
        table: str,
        rows: list[dict],
        conflict_columns: tuple,
    ) -> list[dict]:
        self.upsert_calls.append({
            "schema": schema,
            "table": table,
            "rows": rows,
            "conflict_columns": conflict_columns,
        })
        if self.should_error:
            raise Exception("Supabase API error")
        return rows


def test_approval_increments_alpha():
    provider = FakeSupabaseProvider(
        rows=[{"category": "Marvel", "alpha": 5, "beta": 2}]
    )
    ctx = {
        "hil_callback_decision": {
            "decision": "approved",
            "category": "Marvel",
        }
    }
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is True
    assert result["new_alpha"] == 6
    assert result["new_beta"] == 2


def test_rejection_increments_beta():
    provider = FakeSupabaseProvider(
        rows=[{"category": "Marvel", "alpha": 5, "beta": 2}]
    )
    ctx = {
        "hil_callback_decision": {
            "decision": "rejected",
            "category": "Marvel",
        }
    }
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is True
    assert result["new_alpha"] == 5
    assert result["new_beta"] == 3


def test_unknown_decision_skips():
    provider = FakeSupabaseProvider()
    ctx = {
        "hil_callback_decision": {
            "decision": "unknown",
            "category": "Marvel",
        }
    }
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is False
    assert "Unknown decision" in result["error"]


def test_missing_category_skips():
    provider = FakeSupabaseProvider()
    ctx = {
        "hil_callback_decision": {
            "decision": "approved",
            "category": "",
        }
    }
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is False
    assert "Missing category" in result["error"]


def test_handles_none_decision_and_category():
    """decision=None or category=None must not crash on .lower()/.strip()."""
    provider = FakeSupabaseProvider()
    ctx = {"hil_callback_decision": {"decision": None, "category": None}}
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is False


def test_handles_non_dict_callback():
    """hil_callback_decision being a non-dict must not crash."""
    provider = FakeSupabaseProvider()
    ctx = {"hil_callback_decision": "not-a-dict"}
    ubp.run(ctx, provider=provider)
    assert ctx["bcc_update_result"]["ok"] is False


def test_provider_error_soft_fail():
    provider = FakeSupabaseProvider(should_error=True)
    ctx = {
        "hil_callback_decision": {
            "decision": "approved",
            "category": "Marvel",
        }
    }
    ubp.run(ctx, provider=provider)
    result = ctx["bcc_update_result"]
    assert result["ok"] is False
    assert "error" in result
