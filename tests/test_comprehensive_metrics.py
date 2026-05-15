"""Unit tests for canonical metric helpers and growth scoring."""

import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from equity_sorter.canonical.comprehensive_metrics import (  # noqa: E402
    _calculate_growth_score,
    rate_as_decimal,
)


class RateAsDecimalTests(unittest.TestCase):
    def test_leaves_decimal_rates(self) -> None:
        self.assertAlmostEqual(rate_as_decimal(0.183), 0.183, places=4)
        self.assertAlmostEqual(rate_as_decimal(-0.05), -0.05, places=4)

    def test_converts_percent_style(self) -> None:
        self.assertAlmostEqual(rate_as_decimal(18.3), 0.183, places=4)
        self.assertAlmostEqual(rate_as_decimal(43.83), 0.4383, places=4)


class GrowthScoreCompositeTests(unittest.TestCase):
    def test_tapers_extreme_oeps_when_revenue_trough(self) -> None:
        """Weak 4y revenue + strong OEPS should not score like pure hypergrowth."""
        m = {
            "oeps_cagr": 0.56,
            "roic": 0.44,
            "revenue_cagr_4y": 0.01,
            "revenue_cagr_3y": 0.05,
            "revenue_growth_1y": 0.02,
            "gross_margin": 0.42,
            "gross_margin_expansion": 0.0,
            "revenue_acceleration": 0.0,
            "net_debt_to_ebitda": 0.5,
        }
        with_dampen = _calculate_growth_score(m)
        m2 = dict(m)
        m2["revenue_cagr_4y"] = 0.12
        m2["revenue_cagr_3y"] = 0.12
        higher = _calculate_growth_score(m2)
        self.assertGreater(higher, with_dampen)

    def test_boosts_stable_mid_band_revenue_with_roic(self) -> None:
        base = {
            "oeps_cagr": 0.12,
            "roic": 0.18,
            "revenue_cagr_4y": 0.10,
            "revenue_cagr_3y": 0.10,
            "revenue_growth_1y": 0.08,
            "gross_margin": 0.45,
            "gross_margin_expansion": 0.0,
            "revenue_acceleration": 0.0,
            "net_debt_to_ebitda": 0.4,
        }
        g_stable = _calculate_growth_score(base)
        m2 = dict(base)
        m2["revenue_cagr_4y"] = 0.02
        m2["revenue_cagr_3y"] = 0.02
        m2["revenue_growth_1y"] = 0.02
        g_flat = _calculate_growth_score(m2)
        self.assertGreater(g_stable, g_flat)


if __name__ == "__main__":
    unittest.main()
