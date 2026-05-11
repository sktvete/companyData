from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.providers.local_csv.prices import parse_local_price_csv


class LocalCSVPriceTests(unittest.TestCase):
    def test_parse_local_price_csv(self) -> None:
        text = "ticker,date,open,high,low,close,volume,currency\nAAPL,2025-01-02,100,110,99,105,1000000,USD\n"
        rows = parse_local_price_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "AAPL")
        self.assertEqual(rows[0]["close"], 105.0)


if __name__ == "__main__":
    unittest.main()
