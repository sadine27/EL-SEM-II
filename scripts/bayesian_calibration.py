"""BCC-HIL: Bayesian Calibration with Conjugate Human-in-the-Loop Feedback.

For each product category, maintain a Beta(alpha, beta) posterior over the
probability that a product in that category is approved by the Telegram
reviewer. Update incrementally as approve/reject callbacks arrive. At
inference time, blend the LLM-agent's raw `opportunity_score` with the
posterior approval rate via empirical-Bayes shrinkage to produce a
calibrated 0-1 score.

The posterior is conjugate (Beta prior + Bernoulli likelihood), so the
update is closed-form: alpha += y, beta += (1 - y). Shrinkage weight
w_c = n_c / (n_c + n0) interpolates between raw score (cold start) and
the learned posterior mean (warm).

This module is pure stdlib so it can run on any Python 3.8+ environment
and later be ported verbatim into an n8n Code node (Python execution
node) with no dependency surface.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Iterable, Tuple


PHASE1_CATEGORIES: Tuple[str, ...] = (
    "electronics",
    "fashion",
    "home",
    "fitness",
    "beauty",
    "accessories",
    "automotive",
    "baby_and_kids",
    "pets",
    "office_and_stationery",
    "health_and_medical",
    "tools_and_hardware",
    "grocery_and_food",
)


class BCCHIL:
    """Beta-Bernoulli calibrator with empirical-Bayes shrinkage.

    Parameters
    ----------
    prior_a, prior_b : float
        Initial pseudo-counts for the Beta prior. Defaults give a uniform
        Beta(1, 1). Use Beta(2, 2) for a weak pull toward 0.5.
    n0 : float
        Shrinkage hyperparameter. Larger n0 means more observations are
        needed before the posterior dominates the raw score. Default 5
        was chosen so a category needs roughly one full HIL batch
        (~10 products) before its posterior carries majority weight.
    """

    def __init__(self, prior_a: float = 1.0, prior_b: float = 1.0, n0: float = 5.0) -> None:
        if prior_a <= 0 or prior_b <= 0:
            raise ValueError("Beta prior pseudo-counts must be positive")
        if n0 <= 0:
            raise ValueError("Shrinkage hyperparameter n0 must be positive")
        self.prior_a = float(prior_a)
        self.prior_b = float(prior_b)
        self.n0 = float(n0)
        self._params: Dict[str, Tuple[float, float]] = {}

    def _get(self, category: str) -> Tuple[float, float]:
        return self._params.get(category, (self.prior_a, self.prior_b))

    def update(self, category: str, approved: bool) -> None:
        a, b = self._get(category)
        if approved:
            a += 1.0
        else:
            b += 1.0
        self._params[category] = (a, b)

    def update_batch(self, observations: Iterable[Tuple[str, bool]]) -> None:
        for cat, y in observations:
            self.update(cat, y)

    def posterior_mean(self, category: str) -> float:
        a, b = self._get(category)
        return a / (a + b)

    def posterior_std(self, category: str) -> float:
        a, b = self._get(category)
        denom = (a + b) * (a + b) * (a + b + 1.0)
        return math.sqrt((a * b) / denom)

    def effective_sample_size(self, category: str) -> float:
        a, b = self._get(category)
        n = a + b - (self.prior_a + self.prior_b)
        return max(0.0, n)

    def shrinkage_weight(self, category: str) -> float:
        n = self.effective_sample_size(category)
        return n / (n + self.n0)

    def score(self, category: str, raw_score: float) -> float:
        """Calibrated score in [0, 1].

        raw_score is the LLM-agent opportunity_score on its native [0, 10]
        scale. The output is the convex combination of the category
        posterior mean and the normalized raw score, weighted by the
        shrinkage factor.
        """
        if raw_score < 0 or raw_score > 10:
            raise ValueError(f"raw_score must be in [0, 10], got {raw_score}")
        w = self.shrinkage_weight(category)
        mu = self.posterior_mean(category)
        return w * mu + (1.0 - w) * (raw_score / 10.0)

    def categories(self) -> Tuple[str, ...]:
        return tuple(sorted(self._params.keys()))

    def state(self) -> Dict[str, Tuple[float, float]]:
        return dict(self._params)

    def to_json(self, path: str | Path) -> None:
        payload = {
            "prior_a": self.prior_a,
            "prior_b": self.prior_b,
            "n0": self.n0,
            "params": {c: list(ab) for c, ab in self._params.items()},
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: str | Path) -> "BCCHIL":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        bcc = cls(
            prior_a=payload["prior_a"],
            prior_b=payload["prior_b"],
            n0=payload["n0"],
        )
        bcc._params = {c: (float(a), float(b)) for c, (a, b) in payload["params"].items()}
        return bcc


if __name__ == "__main__":
    bcc = BCCHIL()
    print("Cold-start score (electronics, raw 8.5):", round(bcc.score("electronics", 8.5), 4))
    for _ in range(20):
        bcc.update("fashion", True)
    for _ in range(5):
        bcc.update("fashion", False)
    print("After 20 approvals + 5 rejections in fashion:")
    print("  posterior_mean:", round(bcc.posterior_mean("fashion"), 4))
    print("  posterior_std :", round(bcc.posterior_std("fashion"), 4))
    print("  shrinkage w   :", round(bcc.shrinkage_weight("fashion"), 4))
    print("  cal(raw=5.0)  :", round(bcc.score("fashion", 5.0), 4))
    print("  cal(raw=9.0)  :", round(bcc.score("fashion", 9.0), 4))
