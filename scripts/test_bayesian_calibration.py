"""Unit tests for BCCHIL. Run with: python -m unittest scripts.test_bayesian_calibration

Tests cover the four properties that matter for the paper's correctness
claims: cold-start = raw, convergence to the empirical rate, monotonic
shrinkage, and exact JSON persistence.
"""

import json
import math
import tempfile
import unittest
from pathlib import Path

from bayesian_calibration import BCCHIL, PHASE1_CATEGORIES


class TestColdStart(unittest.TestCase):
    def test_cold_start_returns_raw(self):
        bcc = BCCHIL()
        for raw in (0.0, 2.5, 5.0, 8.5, 10.0):
            with self.subTest(raw=raw):
                self.assertAlmostEqual(bcc.score("electronics", raw), raw / 10.0, places=10)

    def test_cold_start_zero_shrinkage(self):
        bcc = BCCHIL()
        self.assertEqual(bcc.shrinkage_weight("any_unseen_category"), 0.0)
        self.assertEqual(bcc.effective_sample_size("any_unseen_category"), 0.0)

    def test_cold_start_posterior_mean_equals_prior_mean(self):
        bcc = BCCHIL(prior_a=2.0, prior_b=8.0)
        self.assertAlmostEqual(bcc.posterior_mean("unseen"), 0.2, places=10)


class TestConvergence(unittest.TestCase):
    def test_pure_approvals_converge_to_one(self):
        bcc = BCCHIL()
        for _ in range(100):
            bcc.update("fashion", True)
        mean = bcc.posterior_mean("fashion")
        self.assertGreater(mean, 0.98)
        cal = bcc.score("fashion", 0.0)
        self.assertGreater(cal, 0.9)

    def test_pure_rejections_converge_to_zero(self):
        bcc = BCCHIL()
        for _ in range(100):
            bcc.update("fashion", False)
        mean = bcc.posterior_mean("fashion")
        self.assertLess(mean, 0.02)
        cal = bcc.score("fashion", 10.0)
        self.assertLess(cal, 0.1)

    def test_mixed_observations_match_empirical_rate(self):
        bcc = BCCHIL(prior_a=1.0, prior_b=1.0)
        n_pos = 30
        n_neg = 70
        for _ in range(n_pos):
            bcc.update("home", True)
        for _ in range(n_neg):
            bcc.update("home", False)
        empirical = (n_pos + 1.0) / (n_pos + n_neg + 2.0)
        self.assertAlmostEqual(bcc.posterior_mean("home"), empirical, places=10)


class TestShrinkageMonotonicity(unittest.TestCase):
    def test_shrinkage_strictly_increasing(self):
        bcc = BCCHIL(n0=5.0)
        prev_w = -1.0
        for k in range(1, 50):
            bcc.update("pets", True)
            w = bcc.shrinkage_weight("pets")
            self.assertGreater(w, prev_w, msg=f"weight not increasing at k={k}")
            self.assertLess(w, 1.0)
            prev_w = w

    def test_shrinkage_approaches_one_in_the_limit(self):
        bcc = BCCHIL(n0=5.0)
        for _ in range(10000):
            bcc.update("beauty", True)
        self.assertGreater(bcc.shrinkage_weight("beauty"), 0.999)

    def test_calibrated_score_in_unit_interval(self):
        bcc = BCCHIL()
        for k in range(50):
            bcc.update("sports", k % 3 == 0)
        for raw in (0.0, 3.7, 8.5, 10.0):
            cal = bcc.score("sports", raw)
            self.assertGreaterEqual(cal, 0.0)
            self.assertLessEqual(cal, 1.0)


class TestPersistence(unittest.TestCase):
    def test_json_roundtrip_preserves_state(self):
        bcc = BCCHIL(prior_a=2.0, prior_b=3.0, n0=7.5)
        bcc.update_batch([
            ("electronics", True),
            ("electronics", True),
            ("electronics", False),
            ("fashion", False),
            ("fashion", True),
        ])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "post.json"
            bcc.to_json(path)
            loaded = BCCHIL.from_json(path)
        self.assertEqual(loaded.prior_a, bcc.prior_a)
        self.assertEqual(loaded.prior_b, bcc.prior_b)
        self.assertEqual(loaded.n0, bcc.n0)
        for c in bcc.categories():
            self.assertEqual(loaded._get(c), bcc._get(c))
            self.assertAlmostEqual(loaded.score(c, 7.5), bcc.score(c, 7.5), places=12)

    def test_json_format_is_human_readable(self):
        bcc = BCCHIL()
        bcc.update("electronics", True)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "post.json"
            bcc.to_json(path)
            payload = json.loads(path.read_text())
        self.assertIn("prior_a", payload)
        self.assertIn("params", payload)
        self.assertEqual(payload["params"]["electronics"], [2.0, 1.0])


class TestValidation(unittest.TestCase):
    def test_invalid_priors_rejected(self):
        with self.assertRaises(ValueError):
            BCCHIL(prior_a=0)
        with self.assertRaises(ValueError):
            BCCHIL(prior_b=-1)
        with self.assertRaises(ValueError):
            BCCHIL(n0=0)

    def test_raw_score_bounds_enforced(self):
        bcc = BCCHIL()
        with self.assertRaises(ValueError):
            bcc.score("electronics", -0.1)
        with self.assertRaises(ValueError):
            bcc.score("electronics", 10.1)

    def test_phase1_categories_constant_has_13_entries(self):
        self.assertEqual(len(PHASE1_CATEGORIES), 13)
        self.assertEqual(len(set(PHASE1_CATEGORIES)), 13)


if __name__ == "__main__":
    unittest.main(verbosity=2)
