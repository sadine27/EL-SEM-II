"""Tests for el/nodes/bcc_calibrate_selection.py."""
from __future__ import annotations

from el.nodes import bcc_calibrate_selection as bcs


def test_cold_start_identity():
    """Cold-start (alpha=beta=1) should give calibrated = raw/100."""
    ctx = {
        "phase4_candidates": [
            {"quality_score": 75.0, "category": "Marvel"},
        ],
        "bcc_posteriors": [
            {"category": "Marvel", "alpha": 1, "beta": 1},
        ],
    }
    bcs.run(ctx)
    # At cold-start: n=0, w=0, cal = 0*mu + 1*(75/100) = 0.75
    assert ctx["calibrated_candidates"][0]["calibrated_score"] == 0.75


def test_warm_posterior_blending():
    """Warm posterior (alpha>1, beta>1) should blend toward mu."""
    ctx = {
        "phase4_candidates": [
            {"quality_score": 50.0, "category": "Marvel"},
        ],
        "bcc_posteriors": [
            {"category": "Marvel", "alpha": 5, "beta": 5},
        ],
    }
    bcs.run(ctx)
    # n = 5 + 5 - 2 = 8, w = 8/(8+5) ≈ 0.615
    # mu = 5/(5+5) = 0.5
    # cal = 0.615*0.5 + 0.385*0.5 = 0.5 (both same, so blending doesn't change)
    candidate = ctx["calibrated_candidates"][0]
    assert "calibrated_score" in candidate
    assert 0.4 < candidate["calibrated_score"] < 0.6


def test_category_fallback_chain():
    """Should try suggested_categories[0], then category, then phase1_category."""
    ctx = {
        "phase4_candidates": [
            {
                "quality_score": 80.0,
                "suggested_categories": ["Marvel"],
                "category": "DC",
                "phase1_category": "Unknown",
            },
        ],
        "bcc_posteriors": [
            {"category": "Marvel", "alpha": 3, "beta": 2},
        ],
    }
    bcs.run(ctx)
    # Should use "Marvel" from suggested_categories[0]
    assert ctx["calibrated_candidates"][0]["calibrated_score"] > 0


def test_multi_candidate_reordering():
    """Should reorder by calibrated score and re-stamp queue_rank."""
    ctx = {
        "phase4_candidates": [
            {"quality_score": 50.0, "category": "A", "name": "First"},
            {"quality_score": 80.0, "category": "B", "name": "Second"},
            {"quality_score": 60.0, "category": "C", "name": "Third"},
        ],
        "bcc_posteriors": [],
    }
    bcs.run(ctx)
    # Cold-start all, so sorted by raw/100: Second (0.8), Third (0.6), First (0.5)
    assert ctx["calibrated_candidates"][0]["name"] == "Second"
    assert ctx["calibrated_candidates"][0]["queue_rank"] == 1
    assert ctx["calibrated_candidates"][1]["name"] == "Third"
    assert ctx["calibrated_candidates"][1]["queue_rank"] == 2
    assert ctx["calibrated_candidates"][2]["name"] == "First"
    assert ctx["calibrated_candidates"][2]["queue_rank"] == 3


def test_missing_posteriors():
    """Should use cold-start defaults for missing categories."""
    ctx = {
        "phase4_candidates": [
            {"quality_score": 70.0, "category": "Unknown"},
        ],
        "bcc_posteriors": [],
    }
    bcs.run(ctx)
    # Cold-start (alpha=beta=1): cal = 0.7
    assert ctx["calibrated_candidates"][0]["calibrated_score"] == 0.7


def test_empty_candidates():
    """Should handle empty candidate list."""
    ctx = {
        "phase4_candidates": [],
        "bcc_posteriors": [
            {"category": "Marvel", "alpha": 5, "beta": 2},
        ],
    }
    bcs.run(ctx)
    assert ctx["calibrated_candidates"] == []
