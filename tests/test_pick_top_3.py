"""Tests for el/nodes/pick_top_3.py."""
from __future__ import annotations

import json

from el.nodes import pick_top_3


def _query() -> dict:
    return {
        "keyword": "wireless earbuds",
        "run_date": "2026-05-07",
        "source_topic": "Earbuds",
        "source_pick_rank": 1,
        "opportunity_score": 8.4,
    }


def test_parse_price_takes_lower_bound_from_range():
    assert pick_top_3.parse_price("2.02 -- 14.10") == 2.02
    assert pick_top_3.parse_price("") is None
    assert pick_top_3.parse_price("n/a") is None


def test_pick_products_prefers_keyword_matches_by_listed_num_then_tops_up():
    response = {"data": {"list": [
        {"pid": "a", "productNameEn": "Random cable", "listedNum": 999},
        {"pid": "b", "productNameEn": "Wireless earbuds pro", "listedNum": 20},
        {"pid": "c", "productNameEn": "Earbuds case", "listedNum": 80},
        {"pid": "d", "productNameEn": "Phone stand", "listedNum": 50},
    ]}}
    picked = pick_top_3.pick_products(response, _query())
    assert [p["pid"] for p in picked] == ["c", "b", "a"]


def test_normalize_product_maps_cj_shape():
    row = pick_top_3.normalize_product(
        {
            "pid": "PID1",
            "productNameEn": "Wireless Earbuds",
            "productSku": "SKU1",
            "sellPrice": "2.02 -- 14.10",
            "productImage": "a.jpg;b.jpg;",
            "listedNum": 12,
            "supplierName": "Supplier",
            "isFreeShipping": True,
            "shippingCountryCodes": "IN,US",
            "categoryName": "Electronics",
        },
        _query(),
        scraped_at="2026-05-07T00:00:00Z",
    )
    assert row["run_date"] == "2026-05-07"
    assert row["source_provider"] == "cj_dropshipping"
    assert row["product_url"] == "https://app.cjdropshipping.com/product/PID1.html"
    assert row["price_numeric"] == 2.02
    assert json.loads(row["image_urls"]) == ["a.jpg", "b.jpg"]
    assert json.loads(row["offers"]) == [{
        "listedNum": 12,
        "supplierName": "Supplier",
        "isFreeShipping": True,
        "shippingCountryCodes": "IN,US",
        "categoryName": "Electronics",
    }]


def test_run_builds_top_products_and_skips_failed_responses():
    ctx = pick_top_3.run({
        "cj_product_list_responses": [
            {
                "query": _query(),
                "response": {"data": {"list": [
                    {"pid": "1", "productNameEn": "Wireless earbuds", "listedNum": 10},
                ]}},
                "ok": True,
            },
            {
                "query": {"keyword": "bad"},
                "ok": False,
                "error": "quota",
            },
        ],
    })
    assert len(ctx["cj_top_products"]) == 1
    assert ctx["cj_top_products"][0]["product_url"].endswith("/1.html")
