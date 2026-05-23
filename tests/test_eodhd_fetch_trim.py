"""EODHD prefetch trimming for OpenAI analyzer path."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "moonstocks-ai-analyzer"))

from eodhd_fetch import trim_fundamentals_payload  # noqa: E402


class EodhdFetchTrimTests(unittest.TestCase):
    def test_trim_keeps_highlights_drops_old_quarters(self) -> None:
        raw = {
            "General": {"Code": "DECK"},
            "Highlights": {"MarketCapitalization": 1e10},
            "Financials": {
                "Income_Statement": {
                    "yearly": {"2020": {}, "2021": {}, "2022": {}, "2023": {}, "2024": {}},
                    "quarterly": {f"2024-Q{i}": {} for i in range(1, 9)},
                }
            },
            "Noise": {"big": "x" * 1000},
        }
        out = trim_fundamentals_payload(raw)
        self.assertIn("Highlights", out)
        self.assertNotIn("Noise", out)
        yearly = out["Financials"]["Income_Statement"]["yearly"]
        self.assertEqual(len(yearly), 3)
        quarterly = out["Financials"]["Income_Statement"]["quarterly"]
        self.assertEqual(len(quarterly), 4)


if __name__ == "__main__":
    unittest.main()
