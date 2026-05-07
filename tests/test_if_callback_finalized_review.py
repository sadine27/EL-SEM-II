"""Tests for el/nodes/if_callback_finalized_review.py."""
from __future__ import annotations

from el.nodes import if_callback_finalized_review


def test_is_finalized_requires_true_boolean():
    assert if_callback_finalized_review.is_finalized({"message_should_finalize": True}) is True
    assert if_callback_finalized_review.is_finalized({"message_should_finalize": 1}) is False
    assert if_callback_finalized_review.is_finalized({"message_should_finalize": False}) is False


def test_run_splits_finalized_and_non_finalized_callbacks():
    finalized = {"review_id": 1, "message_should_finalize": True}
    already_done = {"review_id": 2, "message_should_finalize": False}
    invalid = {"review_id": 3}

    ctx = if_callback_finalized_review.run(
        {"hil_callback_answers": [finalized, already_done, invalid, None, "bad"]}
    )

    assert ctx["hil_finalized_callbacks"] == [finalized]
    assert ctx["hil_non_finalized_callbacks"] == [already_done, invalid]
    assert ctx["if_callback_finalized_review_result"] == {
        "checked": 3,
        "finalized": 1,
        "not_finalized": 2,
    }
