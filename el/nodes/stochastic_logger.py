"""SP1 telemetry node — slate-level ε-greedy sampler + propensity logging.

Pure helpers (compute_marginal_propensity, sample_slate) are stateless and
seedable for testing. The run(ctx) entry point is added in Task 4.

Spec: docs/superpowers/specs/2026-05-10-sp1-telemetry-foundation-design.md
"""
from __future__ import annotations

import random
from typing import Literal

Branch = Literal["greedy", "explore", "degenerate"]


def compute_marginal_propensity(
    *, in_greedy: bool, slate_size: int, pool_size: int, epsilon: float
) -> float:
    """Marginal P(item shown) under slate-level ε-greedy mixture.

    Mixture: with prob (1-ε) S = G; with prob ε S = uniform K-subset of E.
    For item i:
        P(i in S) = (1 - ε) · 𝟙[i ∈ G] + ε · K / N

    Edge cases:
      pool_size == 0  → 0.0  (item is not in any pool, so not loggable)
      pool_size <= slate_size  → 1.0  (degenerate: everyone shown)
    """
    if pool_size <= 0:
        return 0.0
    if pool_size <= slate_size:
        return 1.0
    explore_term = epsilon * slate_size / pool_size
    if in_greedy:
        return (1.0 - epsilon) + explore_term
    return explore_term


def sample_slate(
    eligible: list[dict],
    greedy: list[dict],
    *,
    epsilon: float,
    rng: random.Random,
) -> tuple[list[dict], Branch]:
    """Sample a slate via the ε-greedy mixture.

    Returns (slate, branch). slate is a list of items drawn from `eligible`;
    branch ∈ {'greedy', 'explore', 'degenerate'}.

    - Empty pool → ([], 'degenerate').
    - pool_size <= slate_size (== len(greedy) by phase4 contract) → return all
      eligible items, branch='degenerate'. ε is ignored in this case.
    - Otherwise: with prob 1-ε return greedy unchanged ('greedy');
      with prob ε return a uniform random K-subset of eligible ('explore').
    """
    pool_size = len(eligible)
    if pool_size == 0:
        return [], "degenerate"
    slate_size = len(greedy)
    if pool_size <= slate_size:
        return list(eligible), "degenerate"
    if rng.random() < epsilon:
        slate = rng.sample(eligible, slate_size)
        return slate, "explore"
    return list(greedy), "greedy"
