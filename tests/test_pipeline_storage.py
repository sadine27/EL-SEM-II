"""Pipeline smoke tests for the Iter 5a storage branch."""
from __future__ import annotations

from el import pipeline


def _ranked_payload() -> dict:
    return {
        "metadata": {"scraped_at": "2026-05-07T10:00:00.000Z"},
        "trends": [{
            "rank": 1,
            "topic": "Wireless Earbuds",
            "source": "youtube_trending",
            "traffic_estimate": "N/A",
            "product_intent_score": 0.8,
            "related_queries": ["bluetooth"],
            "suggested_categories": ["electronics"],
        }],
    }


def test_pipeline_prepares_sheet_rows_without_google_credentials(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fake_score_rank(ctx: dict) -> dict:
        ctx["ranked_payload"] = _ranked_payload()
        return ctx

    monkeypatch.setattr(pipeline.score_rank, "run", fake_score_rank)
    ctx = pipeline.run()
    assert "sheet_tab" not in ctx
    assert "sheet_append_result" not in ctx
    assert ctx["sheet_rows"][0]["topic"] == "Wireless Earbuds"
    assert ctx["filtered"]["total"] == 1


def test_pipeline_runs_sheet_nodes_when_google_credentials_exist(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    def fake_score_rank(ctx: dict) -> dict:
        ctx["ranked_payload"] = _ranked_payload()
        return ctx

    def fake_create_tab(ctx: dict) -> dict:
        ctx["sheet_tab"] = {"title": "2026-05-07", "created": True}
        return ctx

    def fake_write_rows(ctx: dict) -> dict:
        ctx["sheet_append_result"] = {"sheet_title": "2026-05-07", "rows": 1, "ok": True}
        return ctx

    monkeypatch.setattr(pipeline.score_rank, "run", fake_score_rank)
    monkeypatch.setattr(pipeline.create_day_tab, "run", fake_create_tab)
    monkeypatch.setattr(pipeline.write_rows_to_sheet, "run", fake_write_rows)
    ctx = pipeline.run()
    assert ctx["sheet_tab"]["created"] is True
    assert ctx["sheet_rows"][0]["run_date"] == "2026-05-07"
    assert ctx["sheet_append_result"]["ok"] is True
