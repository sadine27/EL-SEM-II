"""Tests for Forge preview pipeline and CLI wiring."""
from __future__ import annotations

import json

from el import __main__ as cli
from el import pipeline
from el.suppliers import SupplierCandidate


class FakeSupplierSource:
    SOURCE_ID = "fake"

    def search_products(self, query, ctx):
        return [
            SupplierCandidate(
                title=f"{query} Supplier",
                source_id="cj",
                supplier_product_id="PID1",
                cost=10,
                shipping_cost=2,
                stock=5,
            )
        ]


def test_preview_forge_query_runs_supplier_search_only(monkeypatch):
    monkeypatch.setattr(
        pipeline.supplier_search,
        "_load_enabled_sources",
        lambda: [FakeSupplierSource()],
    )
    monkeypatch.setattr(
        pipeline,
        "collect_and_rank",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("should not call Fenix")),
    )

    out = pipeline.preview_forge(query="RCB jersey", top=5)

    assert out["metadata"]["mode"] == "query"
    assert out["supplier_matches"][0]["query"] == "RCB jersey"
    assert out["supplier_matches"][0]["matches"][0]["title"] == "RCB jersey Supplier"


def test_preview_forge_from_fenix_uses_ranked_payload(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "collect_and_rank",
        lambda initial_ctx=None: {
            "metadata": {"mode": "fenix", "total_topics": 2},
            "trends": [{"rank": 1, "topic": "wireless earbuds"}, {"rank": 2, "topic": "RCB jersey"}],
        },
    )
    monkeypatch.setattr(
        pipeline.supplier_search,
        "_load_enabled_sources",
        lambda: [FakeSupplierSource()],
    )

    out = pipeline.preview_forge(from_fenix=True, top=1)

    assert out["metadata"]["mode"] == "fenix"
    assert len(out["supplier_matches"]) == 1
    assert out["supplier_matches"][0]["query"] == "wireless earbuds"


def test_preview_forge_requires_query_or_fenix():
    try:
        pipeline.preview_forge()
    except ValueError as exc:
        assert "requires query" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_forge_query_json(monkeypatch, capsys):
    monkeypatch.setattr(
        cli.pipeline,
        "preview_forge",
        lambda **kwargs: {
            "metadata": {"mode": "query"},
            "supplier_matches": [{"query": kwargs["query"], "matches": []}],
        },
    )

    assert cli.main(["forge", "--query", "test product", "--top", "5", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["supplier_matches"][0]["query"] == "test product"
