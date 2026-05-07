"""Bayesian Beta calibration of candidate quality scores."""
from __future__ import annotations

N0 = 5.0  # pseudo-count: how many real samples it takes for w to reach 0.5


def _to_float(value: object, default: float) -> float:
    """Coerce value to float; fall back to default on None/invalid input."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_alpha_beta(post: dict) -> tuple[float, float]:
    """Read alpha/beta from a posterior row, clamping to >= 1 (the cold-start prior).

    A row with alpha=0 or beta=0 would zero-divide in mu, and a row with
    alpha+beta < 2 would push n negative. Clamping to 1 is equivalent to
    treating a corrupted row as cold-start, which is the safe default.
    """
    alpha = _to_float(post.get("alpha"), 1.0)
    beta = _to_float(post.get("beta"), 1.0)
    if alpha < 1.0:
        alpha = 1.0
    if beta < 1.0:
        beta = 1.0
    return alpha, beta


def run(ctx: dict) -> dict:
    """Apply Bayesian Beta calibration to reorder candidates by calibrated score.

    Input: ctx["phase4_candidates"], ctx["bcc_posteriors"]
    Output: ctx["calibrated_candidates"] — reordered with queue_rank re-stamped
    """
    candidates = ctx.get("phase4_candidates") or []
    posteriors = ctx.get("bcc_posteriors") or []

    # Build posterior lookup: {category: (alpha, beta)}
    posterior_map: dict[str, tuple[float, float]] = {}
    for post in posteriors:
        if not isinstance(post, dict):
            continue
        category = post.get("category")
        if category:
            posterior_map[category] = _safe_alpha_beta(post)

    calibrated = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        cal_candidate = dict(candidate)

        suggested = cal_candidate.get("suggested_categories")
        first_suggested = suggested[0] if isinstance(suggested, list) and suggested else None
        category = (
            first_suggested
            or cal_candidate.get("category")
            or cal_candidate.get("phase1_category")
        )

        alpha, beta = posterior_map.get(category, (1.0, 1.0))

        n = alpha + beta - 2.0          # effective samples (>=0 after clamp)
        w = n / (n + N0)                # in [0, 1)
        mu = alpha / (alpha + beta)     # safe: alpha+beta >= 2 after clamp
        raw_score = _to_float(candidate.get("quality_score"), 0.0)

        calibrated_score = w * mu + (1.0 - w) * (raw_score / 100.0)
        cal_candidate["calibrated_score"] = calibrated_score

        calibrated.append(cal_candidate)

    # Sort by calibrated score (descending)
    calibrated.sort(key=lambda x: x["calibrated_score"], reverse=True)

    # Re-stamp queue_rank
    for rank, item in enumerate(calibrated, start=1):
        item["queue_rank"] = rank

    ctx["calibrated_candidates"] = calibrated
    return ctx
