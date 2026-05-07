"""Tests for el/nodes/bundle_json_scraped.py."""
from __future__ import annotations

import base64
import json

from el.nodes import bundle_json_scraped as bjs


def test_bundles_products_with_metadata():
    ctx = {
        "cj_top_products": [
            {"run_date": "2026-05-07", "source_provider": "cj_dropshipping", "product_name": "A"},
            {"run_date": "2026-05-07", "source_provider": "cj_dropshipping", "product_name": "B"},
        ]
    }
    bjs.run(ctx)
    file_item = ctx["scraped_json_file"]
    assert file_item["json"]["filename"] == "scraped_products_2026-05-07.json"
    assert file_item["json"]["total"] == 2
    decoded = base64.b64decode(file_item["binary"]["data"]["data"]).decode("utf-8")
    payload = json.loads(decoded)
    assert payload["metadata"]["total_products"] == 2
    assert payload["metadata"]["run_date"] == "2026-05-07"
    assert payload["metadata"]["source_providers"] == ["cj_dropshipping"]
    assert len(payload["products"]) == 2


def test_handles_empty_products_list():
    """Empty list must still produce a valid file with today's date."""
    ctx = {"cj_top_products": []}
    bjs.run(ctx)
    file_item = ctx["scraped_json_file"]
    assert file_item["json"]["total"] == 0
    decoded = base64.b64decode(file_item["binary"]["data"]["data"]).decode("utf-8")
    payload = json.loads(decoded)
    assert payload["products"] == []
    assert payload["metadata"]["source_providers"] == []


def test_skips_non_dict_products():
    ctx = {"cj_top_products": [None, "x", {"run_date": "2026-05-07", "source_provider": "p1"}]}
    bjs.run(ctx)
    file_item = ctx["scraped_json_file"]
    assert file_item["json"]["total"] == 1


def test_filename_uses_first_product_run_date():
    ctx = {"cj_top_products": [{"run_date": "2025-12-31", "source_provider": "p"}]}
    bjs.run(ctx)
    assert "2025-12-31" in ctx["scraped_json_file"]["json"]["filename"]


def test_binary_is_valid_json():
    ctx = {"cj_top_products": [{"run_date": "2026-05-07", "product_name": "X"}]}
    bjs.run(ctx)
    decoded = base64.b64decode(ctx["scraped_json_file"]["binary"]["data"]["data"]).decode("utf-8")
    json.loads(decoded)  # must not raise
