"""SP1 regression-safety acceptance test.

Asserts: with EL_HIL_EPSILON=0, the hil_slate that would be inserted into
hil_reviews is byte-identical to the phase4_candidates list — i.e. SP1 makes
zero behavioral change to the HIL queue under the regression-safety mode.
"""
from __future__ import annotations

import copy
import json

from el.nodes import phase4_candidate_selection, stochastic_logger


class _NoOpProvider:
    def insert_rows(self, **_kwargs):
        return []

    def upsert_rows(self, **_kwargs):
        return []


def _candidate(idx: int) -> dict:
    raw_payload = {
        "source": "cj_dropshipping",
        "offer": {"listedNum": 20, "categoryName": "Collectibles"},
        "raw_payload": {"pid": f"PID{idx}", "productNameEn": f"Earbuds {idx}"},
    }
    return {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": "EL:2026-05-10:reg",
        "run_date": "2026-05-10",
        "source_provider": "cj_dropshipping",
        "source_topic": f"Earbuds {idx}",
        "source_pick_rank": 1,
        "opportunity_score": 8.5,
        "product_name": f"Earbuds Pro {idx}",
        "product_url": f"https://app.cjdropshipping.com/product/PID{idx}.html",
        "product_sku": f"SKU{idx}",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": f"https://img.example/{idx}.jpg",
        "image_urls": json.dumps([f"https://img.example/{idx}.jpg"]),
        "description": "Bluetooth earbuds",
        "supplier_name": "Supplier",
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": json.dumps(raw_payload),
        "scraped_at": "2026-05-10T10:00:00Z",
    }


def test_epsilon_zero_hil_slate_byte_identical_to_phase4_candidates(monkeypatch):
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "true")
    monkeypatch.setenv("EL_HIL_EPSILON", "0")
    monkeypatch.setenv("EL_HIL_LOGGING_RNG_SEED", "999")

    rows = [_candidate(i) for i in range(20)]
    ctx = {"review_candidates": copy.deepcopy(rows)}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    phase4_baseline = copy.deepcopy(ctx["phase4_candidates"])

    stochastic_logger.run(ctx, provider=_NoOpProvider())

    assert ctx["hil_slate_branch"] == "greedy"
    assert ctx["hil_slate"] == phase4_baseline


def test_logging_disabled_hil_slate_byte_identical_to_phase4_candidates(monkeypatch):
    """Master kill switch must produce the same byte-identical guarantee."""
    monkeypatch.setenv("EL_HIL_LOGGING_ENABLED", "false")

    rows = [_candidate(i) for i in range(20)]
    ctx = {"review_candidates": copy.deepcopy(rows)}
    phase4_candidate_selection.run(ctx, selected_at="2026-05-10T12:00:00Z")
    phase4_baseline = copy.deepcopy(ctx["phase4_candidates"])

    stochastic_logger.run(ctx, provider=_NoOpProvider())

    assert ctx["hil_slate_branch"] == "passthrough"
    assert ctx["hil_slate"] == phase4_baseline
    assert ctx["logging_event_id"] == ""
