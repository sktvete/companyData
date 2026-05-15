"""Unit tests for dashboard metric tone helpers."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

from metric_tones import (  # noqa: E402
    build_sector_valuation_medians,
    quality_debt_to_equity,
    quality_growth_pct_pct,
    valuation_pe,
    valuation_roe_pct,
    row_tones,
)


class MetricTonesTests(unittest.TestCase):
    def test_quality_growth_sign(self):
        self.assertEqual(quality_growth_pct_pct(5.0), "pos")
        self.assertEqual(quality_growth_pct_pct(-1.0), "neg")
        self.assertEqual(quality_growth_pct_pct(0.0), "neu")

    def test_debt_financials_na(self):
        self.assertEqual(quality_debt_to_equity(5.0, "Financial Services"), "na")
        self.assertEqual(quality_debt_to_equity(3.0, "Technology"), "neg")

    def test_valuation_pe_vs_sector(self):
        self.assertEqual(valuation_pe(12.0, 20.0), "pos")
        self.assertEqual(valuation_pe(30.0, 20.0), "neg")
        self.assertEqual(valuation_pe(21.0, 20.0), "neu")

    def test_valuation_roe_vs_sector(self):
        self.assertEqual(valuation_roe_pct(20.0, 10.0), "pos")
        self.assertEqual(valuation_roe_pct(8.0, 10.0), "neg")

    def test_build_sector_medians(self):
        companies = [
            {
                "symbol": "A",
                "sector": "Technology",
                "financial_metrics": {"pe_ratio": 20, "roe": 0.15, "fcf_yield": 0.03},
                "company_info": {},
                "investment_scores": {},
            },
            {
                "symbol": "B",
                "sector": "Technology",
                "financial_metrics": {"pe_ratio": 22, "roe": 0.18, "fcf_yield": 0.04},
                "company_info": {},
                "investment_scores": {},
            },
            {
                "symbol": "C",
                "sector": "Technology",
                "financial_metrics": {"pe_ratio": 24, "roe": 0.12, "fcf_yield": 0.02},
                "company_info": {},
                "investment_scores": {},
            },
        ]
        med = build_sector_valuation_medians(companies)
        self.assertIn("Technology", med)
        self.assertAlmostEqual(med["Technology"]["pe_ratio"], 22.0)

    def test_row_tones_end_to_end(self):
        raw = {
            "symbol": "X",
            "sector": "Technology",
            "financial_metrics": {
                "revenue_growth_1y": 0.08,
                "eps_growth": -0.02,
                "revenue_cagr_4y": 0.05,
                "roe": 0.20,
                "debt_to_equity": 0.8,
                "free_cash_flow": 1e9,
                "fcf_yield": 0.04,
            },
            "company_info": {"pe_ratio": 15.0},
            "investment_scores": {"peg_ratio": 0.9},
        }
        m = {"Technology": {"pe_ratio": 22.0, "roe_pct": 14.0, "fcf_yield": 0.03}}
        t = row_tones(raw, m)
        self.assertEqual(t["rev_growth_1y"], "pos")
        self.assertEqual(t["eps_growth_1y"], "neg")
        self.assertEqual(t["pe"], "pos")


if __name__ == "__main__":
    unittest.main()
