"""Tests for el/nodes/prepare_json_file.py."""
from __future__ import annotations

import base64
import json

from el.nodes import prepare_json_file as pjf


def _decode(item: dict) -> str:
    return base64.b64decode(item["binary"]["data"]["data"]).decode("utf-8")


def test_build_file_item_matches_n8n_binary_shape():
    item = pjf.build_file_item({"trends": [{"topic": "Wireless Earbuds"}]}, "x.json")
    assert item["json"] == {"filename": "x.json"}
    assert item["binary"]["data"]["mimeType"] == "application/json"
    assert item["binary"]["data"]["fileName"] == "x.json"
    assert item["binary"]["data"]["fileExtension"] == "json"
    assert json.loads(_decode(item)) == {"trends": [{"topic": "Wireless Earbuds"}]}


def test_build_file_item_uses_pretty_utf8_json():
    item = pjf.build_file_item({"topic": "saree offer"}, "x.json")
    assert _decode(item) == '{\n  "topic": "saree offer"\n}'


def test_run_stores_json_file_with_trending_filename():
    ctx = {"ranked_payload": {"metadata": {"geo": "IN"}, "trends": []}}
    pjf.run(ctx)
    item = ctx["json_file"]
    filename = item["json"]["filename"]
    assert filename.startswith("trending_india_")
    assert filename.endswith(".json")
    assert len(filename) == len("trending_india_2026-05-07.json")
    assert json.loads(_decode(item)) == {"metadata": {"geo": "IN"}, "trends": []}


def test_run_handles_missing_ranked_payload():
    ctx: dict = {}
    pjf.run(ctx)
    assert json.loads(_decode(ctx["json_file"])) == {}
