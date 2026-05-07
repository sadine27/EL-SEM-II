"""Tests for el/nodes/normalize_cj_review.py."""
from __future__ import annotations

import json

from el.nodes import normalize_cj_review


def _cj_row() -> dict:
    return {
        "run_date": "2026-05-07",
        "source_topic": "Wireless Earbuds",
        "source_pick_rank": 2,
        "opportunity_score": 8.7,
        "product_name": "Wireless Earbuds Pro",
        "product_url": "https://app.cjdropshipping.com/product/PID1.html",
        "product_sku": "SKU1",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "description": "A" * 350,
        "image_urls": json.dumps(["https://img.example/1.jpg", "https://img.example/2.jpg"]),
        "offers": json.dumps([{
            "listedNum": 12,
            "supplierName": "Supplier One",
            "isFreeShipping": True,
        }]),
        "raw_payload": json.dumps({"pid": "PID1"}),
        "scraped_at": "2026-05-07T10:00:00Z",
    }


def test_parse_json_returns_fallback_for_bad_or_missing_values():
    assert normalize_cj_review.parse_json("{bad", []) == []
    assert normalize_cj_review.parse_json(None, {"x": 1}) == {"x": 1}


def test_normalize_row_maps_cj_product_to_hil_contract():
    row = normalize_cj_review.normalize_row(
        _cj_row(),
        now_iso="2026-05-07T11:00:00Z",
        execution_id="exec-1",
    )

    assert row is not None
    assert row["review_schema_version"] == "hil_v1"
    assert row["workflow_name"] == "EL"
    assert row["workflow_run_id"] == "EL:2026-05-07:exec-1"
    assert row["source_provider"] == "cj_dropshipping"
    assert row["source_topic"] == "Wireless Earbuds"
    assert row["product_name"] == "Wireless Earbuds Pro"
    assert row["image_url"] == "https://img.example/1.jpg"
    assert json.loads(row["image_urls"]) == [
        "https://img.example/1.jpg",
        "https://img.example/2.jpg",
    ]
    assert len(row["description"]) == 300
    assert row["supplier_name"] == "Supplier One"
    assert row["marketplace"] == "cjdropshipping"
    assert row["approval_status"] == "pending"
    assert row["approval_channel"] == "telegram"
    assert json.loads(row["raw_payload"]) == {
        "source": "cj_dropshipping",
        "offer": {
            "listedNum": 12,
            "supplierName": "Supplier One",
            "isFreeShipping": True,
        },
        "raw_payload": {"pid": "PID1"},
    }


def test_normalize_row_defaults_and_preserves_unparseable_raw_payload():
    source = _cj_row()
    source.pop("run_date")
    source.pop("currency")
    source["image_urls"] = "{bad"
    source["offers"] = "{bad"
    source["raw_payload"] = "{bad"
    source.pop("scraped_at")

    row = normalize_cj_review.normalize_row(
        source,
        now_iso="2026-05-07T11:00:00Z",
    )

    assert row is not None
    assert row["run_date"] == "2026-05-07"
    assert row["workflow_run_id"] == "EL:2026-05-07:manual"
    assert row["currency"] == "USD"
    assert row["image_url"] is None
    assert json.loads(row["image_urls"]) == []
    assert row["supplier_name"] is None
    assert json.loads(row["raw_payload"])["raw_payload"] == "{bad"
    assert row["scraped_at"] == "2026-05-07T11:00:00Z"


def test_normalize_row_skips_incomplete_required_product_fields():
    for missing_key in ("product_url", "source_topic", "product_name"):
        source = _cj_row()
        source.pop(missing_key)
        assert normalize_cj_review.normalize_row(source) is None


def test_run_stores_cj_review_items():
    ctx = normalize_cj_review.run(
        {"cj_top_products": [_cj_row(), {"product_name": "missing url"}]},
        now_iso="2026-05-07T11:00:00Z",
        execution_id="exec-1",
    )

    assert len(ctx["cj_review_items"]) == 1
    assert ctx["cj_review_items"][0]["workflow_run_id"] == "EL:2026-05-07:exec-1"
