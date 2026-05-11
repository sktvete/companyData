from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.providers.local_csv.prices import parse_local_price_csv


class LocalCSVMappingTests(unittest.TestCase):
    def test_parse_local_price_csv_with_mapping(self) -> None:
        text = "symbol,trading_date,last_px,ccy\nMSFT,2025-01-02,420.5,USD\n"
        mapping = {
            "ticker": ["symbol"],
            "date": ["trading_date"],
            "close": ["last_px"],
            "currency": ["ccy"],
        }
        rows = parse_local_price_csv(text, column_map=mapping)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "MSFT")
        self.assertEqual(rows[0]["close"], 420.5)
