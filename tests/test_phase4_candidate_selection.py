"""Tests for el/nodes/phase4_candidate_selection.py."""
from __future__ import annotations

import json

from el.nodes import phase4_candidate_selection


def _candidate(**overrides) -> dict:
    raw_payload = {
        "source": "cj_dropshipping",
        "offer": {"listedNum": 20, "categoryName": "Collectibles"},
        "raw_payload": {"pid": "PID1", "productNameEn": "Wireless Earbuds Pro"},
    }
    row = {
        "review_schema_version": "hil_v1",
        "workflow_name": "EL",
        "workflow_run_id": "EL:2026-05-07:manual",
        "run_date": "2026-05-07",
        "source_provider": "cj_dropshipping",
        "source_topic": "Wireless Earbuds",
        "source_pick_rank": 1,
        "opportunity_score": 8.5,
        "product_name": "Wireless Earbuds Pro",
        "product_url": "https://app.cjdropshipping.com/product/PID1.html",
        "product_sku": "SKU1",
        "price_text": "2.02 -- 14.10",
        "price_numeric": 2.02,
        "currency": "USD",
        "product_rating": None,
        "reviews_count": None,
        "image_url": "https://img.example/1.jpg",
        "image_urls": json.dumps(["https://img.example/1.jpg"]),
        "description": "Bluetooth earbuds with compact charging case",
        "supplier_name": "Supplier",
        "marketplace": "cjdropshipping",
        "availability_status": "unknown",
        "approval_status": "pending",
        "approval_channel": "telegram",
        "raw_payload": json.dumps(raw_payload),
        "scraped_at": "2026-05-07T10:00:00Z",
    }
    row.update(overrides)
    return row


def _debug(row: dict) -> dict:
    return json.loads(row["raw_payload"])["phase4_debug"]


def _selection(row: dict) -> dict:
    return json.loads(row["raw_payload"])["phase4_selection"]


def test_prepare_candidate_scores_and_keeps_clean_cj_candidate():
    prepared = phase4_candidate_selection.prepare_candidate(_candidate())

    assert prepared.score >= phase4_candidate_selection.MIN_SCORE
    assert prepared.rejection_reasons == []
    assert prepared.context["topic_intent_type"] == "direct_product"
    assert prepared.context["topic_overlap"] >= 1


def test_select_candidates_attaches_phase4_selection_and_debug_payload():
    selected = phase4_candidate_selection.select_candidates(
        [_candidate()],
        selected_at="2026-05-07T12:00:00Z",
    )

    assert len(selected) == 1
    selection = _selection(selected[0])
    debug = _debug(selected[0])
    assert selection["phase"] == "phase4_candidate_selection"
    assert selection["queue_rank"] == 1
    assert selection["selected_at"] == "2026-05-07T12:00:00Z"
    assert debug["decision"] == "selected"
    assert debug["rejection_reasons"] == []


def test_select_candidates_blocks_missing_required_fields():
    selected = phase4_candidate_selection.select_candidates([
        _candidate(product_url=""),
    ])

    assert selected == []


def test_select_candidates_dedupes_same_canonical_url():
    first = _candidate(product_url="https://example.com/product?pid=1&utm=x")
    second = _candidate(
        product_name="Wireless Earbuds Pro Duplicate",
        product_url="https://example.com/product?pid=1&utm=y",
        opportunity_score=7,
    )
    selected = phase4_candidate_selection.select_candidates([first, second])

    assert len(selected) == 1
    assert selected[0]["product_url"] == first["product_url"]


def test_select_candidates_applies_topic_and_provider_caps():
    rows = [
        _candidate(
            product_name=f"Wireless Earbuds Pro {i}",
            product_url=f"https://supplier{i}.example/product/PID{i}.html",
            image_url=f"https://img.example/{i}.jpg",
            raw_payload=json.dumps({
                "source": "cj_dropshipping",
                "offer": {"listedNum": 10 + i},
                "raw_payload": {"pid": f"PID{i}", "productNameEn": f"Wireless Earbuds Pro {i}"},
            }),
        )
        for i in range(4)
    ]

    selected = phase4_candidate_selection.select_candidates(rows)

    assert len(selected) == phase4_candidate_selection.TOPIC_CAP


def test_select_candidates_uses_fallback_when_only_score_is_low():
    row = _candidate(
        opportunity_score=0,
        source_pick_rank=30,
        source_topic="Earbuds",
        description="",
    )
    prepared = phase4_candidate_selection.prepare_candidate(row)
    assert 20 <= prepared.score < phase4_candidate_selection.MIN_SCORE

    selected = phase4_candidate_selection.select_candidates([row])

    assert len(selected) == 1
    reasons = _debug(selected[0])["rejection_reasons"]
    assert reasons == [{
        "stage": "fallback",
        "code": "fallback_selected",
        "message": "Selected by fallback because strict phase 4 produced an empty queue.",
        "details": {
            "score": prepared.score,
            "fallback_min_score": phase4_candidate_selection.FALLBACK_MIN_SCORE,
        },
    }]


def test_select_candidates_rejects_hard_block_terms():
    selected = phase4_candidate_selection.select_candidates([
        _candidate(
            source_topic="Bluetooth Gadget",
            product_name="Women shoes",
            description="",
            raw_payload=json.dumps({
                "source": "cj_dropshipping",
                "offer": {"listedNum": 10},
                "raw_payload": {"productNameEn": "Women shoes"},
            }),
        )
    ])

    assert selected == []


def test_run_stores_phase4_candidates():
    ctx = phase4_candidate_selection.run(
        {"review_candidates": [_candidate()]},
        selected_at="2026-05-07T12:00:00Z",
    )

    assert len(ctx["phase4_candidates"]) == 1
    assert _selection(ctx["phase4_candidates"][0])["queue_rank"] == 1
