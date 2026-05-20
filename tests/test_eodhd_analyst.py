"""Tests for web/eodhd_analyst.py."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

from eodhd_analyst import extract_analyst_ratings


class EodhdAnalystTests(unittest.TestCase):
    def test_full_consensus(self) -> None:
        d = {
            "AnalystRatings": {
                "Rating": 4.0,
                "StrongBuy": 5,
                "Buy": 10,
                "Hold": 2,
                "Sell": 0,
                "StrongSell": 0,
                "TargetPrice": 100,
            }
        }
        ar = extract_analyst_ratings(d)
        self.assertIsNotNone(ar)
        self.assertEqual(ar["Rating"], 4.0)
        self.assertFalse(ar["partial"])

    def test_estimate_only_trend_returns_none(self) -> None:
        d = {
            "AnalystRatings": {},
            "Earnings": {
                "Trend": {
                    "2026-12-31": {
                        "period": "+1y",
                        "earningsEstimateNumberOfAnalysts": "3",
                        "revenueEstimateNumberOfAnalysts": "2",
                    }
                }
            },
        }
        self.assertIsNone(extract_analyst_ratings(d))


if __name__ == "__main__":
    unittest.main()
