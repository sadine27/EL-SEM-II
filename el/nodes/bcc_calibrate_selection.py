"""Bayesian Beta calibration of candidate quality scores."""
from __future__ import annotations


def run(ctx: dict) -> dict:
    """Apply Bayesian Beta calibration to reorder candidates by calibrated score.

    Input: ctx["phase4_candidates"], ctx["bcc_posteriors"]
    Output: ctx["calibrated_candidates"] — reordered with queue_rank re-stamped
    """
    candidates = ctx.get("phase4_candidates", [])
    posteriors = ctx.get("bcc_posteriors", [])

    # Build posterior lookup: {category: {alpha, beta}}
    posterior_map = {}
    for post in posteriors:
        category = post.get("category")
        if category:
            posterior_map[category] = {
                "alpha": post.get("alpha", 1),
                "beta": post.get("beta", 1),
            }

    N0 = 5.0

    # Calibrate each candidate
    calibrated = []
    for candidate in candidates:
        cal_candidate = dict(candidate)

        # Resolve category from multiple sources
        category = (
            (cal_candidate.get("suggested_categories") or [None])[0]
            or cal_candidate.get("category")
            or cal_candidate.get("phase1_category")
        )

        # Get posterior priors (default to cold-start)
        posterior = posterior_map.get(category, {"alpha": 1, "beta": 1})
        alpha = posterior["alpha"]
        beta = posterior["beta"]

        # Compute BCC formula
        n = alpha + beta - 2  # effective samples
        w = n / (n + N0)  # weight toward posterior mean
        mu = alpha / (alpha + beta)  # posterior mean
        raw_score = candidate.get("quality_score", 0)

        # Blend: cold-start (w=0) → identity, warm (w>0) → blended
        calibrated_score = w * mu + (1 - w) * (raw_score / 100.0)
        cal_candidate["calibrated_score"] = calibrated_score

        calibrated.append(cal_candidate)

    # Sort by calibrated score (descending)
    calibrated.sort(key=lambda x: x["calibrated_score"], reverse=True)

    # Re-stamp queue_rank
    for rank, item in enumerate(calibrated, start=1):
        item["queue_rank"] = rank

    ctx["calibrated_candidates"] = calibrated
    return ctx
