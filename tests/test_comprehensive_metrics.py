"""Unit tests for canonical metric helpers and growth scoring."""

import unittest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from equity_sorter.canonical.comprehensive_metrics import (  # noqa: E402
    _adjusted_gross_profit,
    _calculate_growth_score,
    calculate_comprehensive_metrics,
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


class CalculateComprehensiveMetricsEodhdTests(unittest.TestCase):
    def _stmt(self, d: str, rev: float, gp: float, cor: float, ni: float, dil: float | None) -> dict:
        row: dict = {
            "date": d,
            "totalRevenue": rev,
            "grossProfit": gp,
            "costOfRevenue": cor,
            "operatingIncome": ni * 0.5,
            "ebit": ni * 0.5,
            "ebitda": ni * 0.55,
            "incomeBeforeTax": ni * 0.52,
            "netIncome": ni,
        }
        if dil is not None:
            row["dilutedEPS"] = dil
        return row

    def _bs(self, d: str) -> dict:
        return {
            "date": d,
            "cash": 1e9,
            "totalAssets": 3e9,
            "totalCurrentAssets": 1e9,
            "inventory": 0.0,
            "netReceivables": 1e8,
            "accountPayables": 5e7,
            "totalCurrentLiabilities": 2e8,
            "totalLiab": 8e8,
            "shortLongTermDebt": 0.0,
            "longTermDebt": 0.0,
            "totalStockholderEquity": 2e9,
            "retainedEarnings": 1e9,
            "commonStockSharesOutstanding": 40e6,
        }

    def _cf(self, d: str) -> dict:
        return {
            "date": d,
            "totalCashFromOperatingActivities": 80e6,
            "capitalExpenditures": -5e6,
            "freeCashFlow": 75e6,
            "stockBasedCompensation": 3e6,
        }

    def test_adjusted_gross_profit_duol_style(self) -> None:
        stmt = {"totalRevenue": 250e6, "grossProfit": 250e6, "costOfRevenue": 69e6}
        self.assertAlmostEqual(_adjusted_gross_profit(stmt), 250e6 - 69e6, places=3)

    def test_partial_quarterly_eps_uses_highlights(self) -> None:
        dates = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
        inc = [
            self._stmt(dates[0], 100e6, 50e6, 30e6, 10e6, 0.25),
            self._stmt(dates[1], 100e6, 50e6, 30e6, 10e6, 0.25),
            self._stmt(dates[2], 100e6, 100e6, 30e6, 10e6, None),
            self._stmt(dates[3], 100e6, 50e6, 30e6, 10e6, None),
        ]
        bs = [self._bs(d) for d in dates]
        cf = [self._cf(d) for d in dates]
        fd = {"income_statement": inc, "balance_sheet": bs, "cash_flow": cf}
        px = [{"close": 120.0, "market_cap": 5e9, "enterprise_value": 5.2e9}]
        hl = {"EarningsShare": 4.9}
        m = calculate_comprehensive_metrics(fd, px, highlights=hl)
        self.assertNotIn("error", m)
        self.assertAlmostEqual(m["eps_diluted"], 4.9, places=3)

    def test_complete_quarterly_eps_prefers_sum(self) -> None:
        dates = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
        inc = [self._stmt(d, 100e6, 50e6, 30e6, 12e6, 0.4) for d in dates]
        bs = [self._bs(d) for d in dates]
        cf = [self._cf(d) for d in dates]
        fd = {"income_statement": inc, "balance_sheet": bs, "cash_flow": cf}
        px = [{"close": 100.0, "market_cap": 4e9, "enterprise_value": 4.1e9}]
        hl = {"EarningsShare": 99.0}
        m = calculate_comprehensive_metrics(fd, px, highlights=hl)
        self.assertNotIn("error", m)
        self.assertAlmostEqual(m["eps_diluted"], 1.6, places=5)


if __name__ == "__main__":
    unittest.main()
