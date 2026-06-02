"""Tests for the Forge CJ supplier adapter."""
from __future__ import annotations

from el.suppliers import SupplierCandidate
from el.suppliers import cj_source


class FakeProvider:
    def __init__(self, token_response=None, product_response=None, errors=None):
        self.token_response = token_response if token_response is not None else {
            "code": 200,
            "data": {"accessToken": "TOKEN"},
        }
        self.product_response = product_response if product_response is not None else {
            "code": 200,
            "data": {"list": []},
        }
        self.errors = list(errors or [])
        self.calls = []

    def get_access_token(self):
        self.calls.append(("get_access_token",))
        if self.errors:
            raise self.errors.pop(0)
        return self.token_response

    def list_products(self, keyword, access_token, page_num=1, page_size=20):
        self.calls.append(("list_products", keyword, access_token, page_num, page_size))
        if self.errors:
            raise self.errors.pop(0)
        return self.product_response


def test_missing_credentials_returns_empty_and_does_not_construct_provider(monkeypatch):
    monkeypatch.delenv("CJ_EMAIL", raising=False)
    monkeypatch.delenv("CJ_API_KEY", raising=False)
    constructed = []

    source = cj_source.CJSource(provider_factory=lambda: constructed.append(True))

    assert source.search_products("wireless earbuds", {}) == []
    assert constructed == []


def test_non_200_token_api_error_returns_empty(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    provider = FakeProvider(token_response={"code": 401, "data": {}})

    out = cj_source.CJSource(provider_factory=lambda: provider).search_products("earbuds", {})

    assert out == []
    assert provider.calls == [("get_access_token",)]


def test_non_200_product_api_error_returns_empty(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    provider = FakeProvider(product_response={"code": 500, "data": {"list": []}})

    out = cj_source.CJSource(provider_factory=lambda: provider).search_products("earbuds", {})

    assert out == []
    assert provider.calls[-1] == ("list_products", "earbuds", "TOKEN", 1, 20)


def test_malformed_json_returns_empty(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    provider = FakeProvider(product_response="not-json")

    assert cj_source.CJSource(provider_factory=lambda: provider).search_products("earbuds", {}) == []


def test_provider_exception_returns_empty(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    provider = FakeProvider(errors=[ValueError("malformed json")])

    assert cj_source.CJSource(provider_factory=lambda: provider).search_products("earbuds", {}) == []


def test_happy_path_maps_response_into_supplier_candidate(monkeypatch):
    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    product = {
        "pid": "PID123",
        "productNameEn": "Wireless Earbuds Pro",
        "productImage": "https://img.example/1.jpg;https://img.example/2.jpg",
        "sellPrice": "12.50",
        "listedNum": "42",
        "isFreeShipping": True,
        "shippingDaysMin": "5",
        "shippingDaysMax": "9",
        "moq": "2",
        "rating": "4.7",
    }
    provider = FakeProvider(product_response={"code": 200, "data": {"list": [product]}})

    out = cj_source.CJSource(provider_factory=lambda: provider).search_products("wireless earbuds", {})

    assert len(out) == 1
    candidate = out[0]
    assert isinstance(candidate, SupplierCandidate)
    assert candidate.title == "Wireless Earbuds Pro"
    assert candidate.source_id == "cj"
    assert candidate.supplier_product_id == "PID123"
    assert candidate.product_url == "https://app.cjdropshipping.com/product/PID123.html"
    assert candidate.image_url == "https://img.example/1.jpg"
    assert candidate.cost == 12.50
    assert candidate.currency == "USD"
    assert candidate.shipping_cost == 0.0
    assert candidate.shipping_days_min == 5
    assert candidate.shipping_days_max == 9
    assert candidate.stock == 42
    assert candidate.moq == 2
    assert candidate.rating == 4.7
    assert candidate.raw_payload == product


def test_scoring_ranking_prefers_available_lower_landed_cost_faster_matches(monkeypatch):
    from el.nodes import supplier_search

    monkeypatch.setenv("CJ_EMAIL", "user@example.com")
    monkeypatch.setenv("CJ_API_KEY", "KEY")
    provider = FakeProvider(product_response={"code": 200, "data": {"list": [
        {
            "pid": "SLOW",
            "productNameEn": "Wireless Earbuds",
            "sellPrice": "80",
            "shippingCost": "20",
            "shippingDaysMin": "25",
            "listedNum": 0,
        },
        {
            "pid": "FAST",
            "productNameEn": "Wireless Earbuds Pro",
            "productImage": "https://img.example/fast.jpg",
            "sellPrice": "9",
            "shippingCost": "2",
            "shippingDaysMin": "4",
            "listedNum": 100,
        },
    ]}})
    source = cj_source.CJSource(provider_factory=lambda: provider)
    ctx = {"ranked_payload": {"trends": [{"topic": "wireless earbuds"}]}}

    out = supplier_search.run(ctx, sources=[source])

    matches = out["supplier_matches"][0]["matches"]
    assert matches[0]["supplier_product_id"] == "FAST"
    assert matches[0]["match_score"] > matches[1]["match_score"]
