from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.canonical.normalization import normalize_symbol_records
from equity_sorter.providers.eodhd.symbols import SymbolRecord


class NormalizationTests(unittest.TestCase):
    def test_symbol_normalization_creates_reference_tables(self) -> None:
        rows = [
            SymbolRecord(code="ABC", exchange="US", name="ABC Corp", country="US", currency="USD", type="Common Stock", isin=None, delisted=False)
        ]
        tables = normalize_symbol_records(rows, provider="eodhd")
        self.assertEqual(len(tables["companies"]), 1)
        self.assertEqual(len(tables["securities"]), 1)
        self.assertEqual(len(tables["listings"]), 1)
        self.assertEqual(len(tables["identifiers"]), 1)


if __name__ == "__main__":
    unittest.main()
