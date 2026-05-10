"""Tests for el/nodes/stochastic_logger.py."""
from __future__ import annotations

import math
import random
from collections import Counter

import pytest

from el.nodes import stochastic_logger


# -- compute_marginal_propensity ------------------------------------------------

def test_marginal_propensity_in_greedy_slate():
    # P(i shown | i in G) = (1 - eps) + eps * K / N
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=0.1
    )
    assert p == pytest.approx(0.9 + 0.1 * 10 / 30, rel=1e-9)


def test_marginal_propensity_not_in_greedy_slate():
    # P(i shown | i not in G) = eps * K / N
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=0.1
    )
    assert p == pytest.approx(0.1 * 10 / 30, rel=1e-9)


def test_marginal_propensity_epsilon_zero_in_greedy():
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=0.0
    )
    assert p == pytest.approx(1.0)


def test_marginal_propensity_epsilon_zero_not_in_greedy_is_zero():
    """At ε=0 a non-greedy item has 0 probability — outside policy support."""
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=0.0
    )
    assert p == pytest.approx(0.0)


def test_marginal_propensity_epsilon_one_uniform():
    p_in = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=30, epsilon=1.0
    )
    p_out = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=30, epsilon=1.0
    )
    assert p_in == pytest.approx(10 / 30)
    assert p_out == pytest.approx(10 / 30)


def test_marginal_propensity_degenerate_n_le_k():
    # When N <= K, every eligible item is shown; propensity = 1.
    p_in = stochastic_logger.compute_marginal_propensity(
        in_greedy=True, slate_size=10, pool_size=5, epsilon=0.1
    )
    p_out = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=5, epsilon=0.1
    )
    assert p_in == pytest.approx(1.0)
    assert p_out == pytest.approx(1.0)


def test_marginal_propensity_pool_size_zero_returns_zero():
    p = stochastic_logger.compute_marginal_propensity(
        in_greedy=False, slate_size=10, pool_size=0, epsilon=0.1
    )
    assert p == pytest.approx(0.0)


# -- sample_slate ---------------------------------------------------------------

def test_sample_slate_epsilon_zero_returns_greedy_exactly():
    """ε=0 must return the greedy slate byte-for-byte (regression-safety mode)."""
    eligible = [{"id": i} for i in range(20)]
    greedy = eligible[:10]
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=0.0, rng=rng)
    assert slate == greedy
    assert branch == "greedy"


def test_sample_slate_epsilon_one_returns_uniform_subset():
    eligible = [{"id": i} for i in range(20)]
    greedy = eligible[:10]
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=1.0, rng=rng)
    assert branch == "explore"
    assert len(slate) == 10
    # All items in slate are from the eligible pool
    eligible_ids = {e["id"] for e in eligible}
    slate_ids = {s["id"] for s in slate}
    assert slate_ids.issubset(eligible_ids)
    # No duplicates
    assert len(slate_ids) == len(slate)


def test_sample_slate_degenerate_pool_le_slate_returns_all():
    eligible = [{"id": i} for i in range(5)]
    greedy = list(eligible)
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=0.1, rng=rng)
    assert branch == "degenerate"
    assert slate == eligible


def test_sample_slate_empty_pool_returns_empty():
    rng = random.Random(42)
    slate, branch = stochastic_logger.sample_slate([], [], epsilon=0.1, rng=rng)
    assert slate == []
    assert branch == "degenerate"


def test_sample_slate_empirical_propensity_matches_analytical():
    """Property test: across many trials, empirical P(item shown) ≈ analytical."""
    eligible = [{"id": i} for i in range(30)]
    greedy = eligible[:10]
    epsilon = 0.1
    n_trials = 5000
    rng = random.Random(0xC0FFEE)
    counts: Counter[int] = Counter()
    for _ in range(n_trials):
        slate, _ = stochastic_logger.sample_slate(eligible, greedy, epsilon=epsilon, rng=rng)
        for item in slate:
            counts[item["id"]] += 1

    # Analytical: in-greedy ≈ 0.9333; out-greedy ≈ 0.0333.
    in_greedy_analytical = 0.9 + 0.1 * 10 / 30
    out_greedy_analytical = 0.1 * 10 / 30

    for item_id in range(10):  # in-greedy
        empirical = counts[item_id] / n_trials
        assert math.isclose(empirical, in_greedy_analytical, abs_tol=0.03), (
            f"item {item_id} (in-greedy): empirical {empirical}, analytical {in_greedy_analytical}"
        )
    for item_id in range(10, 30):  # out-greedy
        empirical = counts[item_id] / n_trials
        assert math.isclose(empirical, out_greedy_analytical, abs_tol=0.02), (
            f"item {item_id} (out-greedy): empirical {empirical}, analytical {out_greedy_analytical}"
        )


def test_sample_slate_branch_distribution_matches_epsilon():
    """Across many trials, branch=='explore' fraction ≈ ε."""
    eligible = [{"id": i} for i in range(30)]
    greedy = eligible[:10]
    epsilon = 0.3
    n_trials = 2000
    rng = random.Random(123)
    explore_count = 0
    for _ in range(n_trials):
        _, branch = stochastic_logger.sample_slate(eligible, greedy, epsilon=epsilon, rng=rng)
        if branch == "explore":
            explore_count += 1
    empirical_eps = explore_count / n_trials
    assert math.isclose(empirical_eps, epsilon, abs_tol=0.03)
