"""Tests for el/nodes/prepare_sheet_rows_scraped.py."""
from __future__ import annotations

import json

from el.nodes import prepare_sheet_rows_scraped as psrs


def _product(**overrides) -> dict:
    base = {
        "run_date": "2026-05-07",
        "source_pick_rank": 1,
        "opportunity_score": 0.9,
        "source_topic": "Marvel collectibles",
        "source_provider": "cj_dropshipping",
        "product_name": "Iron Man Figure",
        "product_url": "https://app.cjdropshipping.com/product/abc.html",
        "product_sku": "SKU-1",
        "price_text": "12.50",
        "price_numeric": 12.5,
        "currency": "USD",
        "image_urls": json.dumps(["https://x/img1.jpg", "https://x/img2.jpg"]),
        "offers": json.dumps([
            {
                "listedNum": 42,
                "supplierName": "Acme",
                "isFreeShipping": True,
                "shippingCountryCodes": "IN,US",
                "categoryName": "Toys",
            }
        ]),
        "scraped_at": "2026-05-07T10:00:00Z",
    }
    base.update(overrides)
    return base


def test_flattens_image_urls_and_first_offer():
    ctx = {"cj_top_products": [_product()]}
    psrs.run(ctx)
    rows = ctx["scraped_sheet_rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["image_urls"] == "https://x/img1.jpg, https://x/img2.jpg"
    assert row["image_count"] == 2
    assert row["listed_num"] == 42
    assert row["supplier"] == "Acme"
    assert row["free_shipping"] == "YES"
    assert row["category"] == "Toys"


def test_handles_empty_offers_and_images():
    ctx = {"cj_top_products": [_product(image_urls="[]", offers="[]")]}
    psrs.run(ctx)
    row = ctx["scraped_sheet_rows"][0]
    assert row["image_urls"] == ""
    assert row["image_count"] == 0
    assert row["listed_num"] == ""
    assert row["free_shipping"] == "no"


def test_handles_malformed_json_strings():
    """Regression: bad JSON in image_urls/offers must not crash."""
    ctx = {"cj_top_products": [_product(image_urls="not-json", offers="also-not-json")]}
    psrs.run(ctx)
    row = ctx["scraped_sheet_rows"][0]
    assert row["image_urls"] == ""
    assert row["image_count"] == 0
    assert row["listed_num"] == ""


def test_skips_non_dict_products():
    ctx = {"cj_top_products": [None, "string", _product()]}
    psrs.run(ctx)
    assert len(ctx["scraped_sheet_rows"]) == 1


def test_handles_empty_input():
    ctx = {}
    psrs.run(ctx)
    assert ctx["scraped_sheet_rows"] == []


def test_columns_match_known_order():
    ctx = {"cj_top_products": [_product()]}
    psrs.run(ctx)
    row = ctx["scraped_sheet_rows"][0]
    for col in psrs.SCRAPED_SHEET_ROW_COLUMNS:
        assert col in row
