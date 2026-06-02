"""Tests for the Forge supplier search node."""
from __future__ import annotations

from el.nodes import supplier_search
from el.suppliers import SupplierCandidate


class FakeSource:
    SOURCE_ID = "fake"

    def __init__(self, results):
        self.results = results
        self.queries = []

    def search_products(self, query, ctx):
        self.queries.append(query)
        return list(self.results)


class CrashingSource:
    SOURCE_ID = "crash"

    def search_products(self, query, ctx):
        raise RuntimeError("boom")


def _candidate(title, **kwargs):
    return SupplierCandidate(title=title, source_id=kwargs.pop("source_id", "cj"), **kwargs)


def test_run_reads_ranked_payload_trends_and_writes_supplier_matches():
    source = FakeSource([
        _candidate(
            "Wireless Earbuds Pro",
            product_url="https://supplier.example/products/earbuds",
            image_url="https://supplier.example/earbuds.jpg",
            cost=12.0,
            currency="USD",
            shipping_cost=3.0,
            shipping_days_min=5,
            shipping_days_max=8,
            stock=50,
        ),
    ])
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds", "rank": 1}]}}

    out = supplier_search.run(ctx, sources=[source])

    assert source.queries == ["wireless earbuds"]
    assert out["supplier_matches"][0]["query"] == "wireless earbuds"
    match = out["supplier_matches"][0]["matches"][0]
    assert match["title"] == "Wireless Earbuds Pro"
    assert match["landed_cost"] == 15.0
    assert match["match_score"] > 0


def test_run_supports_ranked_compatibility_fallback():
    source = FakeSource([_candidate("RCB Jersey", stock=10)])
    ctx = {"ranked": [{"title": "RCB jersey"}]}

    out = supplier_search.run(ctx, sources=[source])

    assert source.queries == ["RCB jersey"]
    assert out["supplier_matches"][0]["matches"][0]["title"] == "RCB Jersey"


def test_run_dedupes_by_normalized_product_url_keeps_best_match():
    expensive = _candidate(
        "Wireless Earbuds",
        product_url="HTTPS://SUPPLIER.EXAMPLE/Product/1?ref=x",
        cost=50.0,
        shipping_cost=10.0,
        shipping_days_min=20,
        stock=0,
    )
    better = _candidate(
        "Wireless Earbuds",
        product_url="https://supplier.example/Product/1",
        image_url="https://supplier.example/1.jpg",
        cost=10.0,
        shipping_cost=2.0,
        shipping_days_min=4,
        stock=25,
    )
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}

    out = supplier_search.run(ctx, sources=[FakeSource([expensive, better])])

    matches = out["supplier_matches"][0]["matches"]
    assert len(matches) == 1
    assert matches[0]["cost"] == 10.0


def test_run_dedupes_by_normalized_title_when_url_missing():
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}
    out = supplier_search.run(ctx, sources=[FakeSource([
        _candidate("Wireless Earbuds!!", cost=18.0, stock=0),
        _candidate("wireless earbuds", cost=9.0, stock=12),
    ])])

    matches = out["supplier_matches"][0]["matches"]
    assert len(matches) == 1
    assert matches[0]["cost"] == 9.0


def test_scoring_ranking_prefers_available_lower_landed_cost_faster_with_image():
    weak = _candidate(
        "Wireless Earbuds",
        image_url=None,
        cost=50.0,
        shipping_cost=15.0,
        shipping_days_min=25,
        stock=0,
    )
    strong = _candidate(
        "Wireless Earbuds Pro",
        image_url="https://supplier.example/img.jpg",
        cost=8.0,
        shipping_cost=2.0,
        shipping_days_min=4,
        stock=100,
    )
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}

    out = supplier_search.run(ctx, sources=[FakeSource([weak, strong])])

    matches = out["supplier_matches"][0]["matches"]
    assert matches[0]["title"] == "Wireless Earbuds Pro"
    assert matches[0]["match_score"] > matches[1]["match_score"]


def test_run_isolates_source_failures():
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}

    out = supplier_search.run(ctx, sources=[
        CrashingSource(),
        FakeSource([_candidate("Wireless Earbuds", stock=1)]),
    ])

    assert out["supplier_matches"][0]["matches"][0]["title"] == "Wireless Earbuds"


def test_run_with_no_sources_returns_empty_matches_not_crash():
    ctx = {"ranked_payload": {"trends": [{"topic": "test product"}]}}

    out = supplier_search.run(ctx, sources=[])

    assert out["supplier_matches"] == [{
        "trend": {"topic": "test product", "rank": 1},
        "query": "test product",
        "matches": [],
    }]
