"""Tests for forward revenue estimate pruning."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

import app_enhanced as ae


class RevenueEstimatePruneTests(unittest.TestCase):
    def test_prune_low_forward_revenue(self) -> None:
        est = [{"revenue_usd": 6e9, "revenue_b": 6.0, "eps": 2.0}]
        ttm = {"revenue_usd": 33e9, "revenue_b": 33.0}
        ae._prune_implausible_revenue_estimates(est, ttm, [])
        self.assertIsNone(est[0].get("revenue_usd"))
        self.assertIsNone(est[0].get("revenue_b"))
        self.assertEqual(est[0].get("eps"), 2.0)

    def test_keep_plausible_forward_revenue(self) -> None:
        est = [{"revenue_usd": 50e9, "revenue_b": 50.0}]
        ttm = {"revenue_usd": 40e9}
        ae._prune_implausible_revenue_estimates(est, ttm, [])
        self.assertEqual(est[0]["revenue_usd"], 50e9)


if __name__ == "__main__":
    unittest.main()
