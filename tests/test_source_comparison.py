from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.io_utils import read_jsonl
from equity_sorter.source_comparison import compare_sec_to_normalized


class SourceComparisonTests(unittest.TestCase):
    def test_compare_sec_to_normalized(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        raw_rows = [{"security_id": "sec_1", "fiscal_period": "2024-12-31", "revenue": 100.0, "net_income": 10.0, "report_date": "2024-12-31", "filing_date": "2025-02-01"}]
        normalized_rows = [{"security_id": "sec_1", "fiscal_period": "2024-12-31", "revenue": 100.0, "net_income": 11.0, "report_date": "2024-12-31", "filing_date": "2025-02-01"}]
        paths = compare_sec_to_normalized(raw_rows, normalized_rows, tmpdir)
        rows = read_jsonl(paths["jsonl"])
        self.assertTrue(any(row["status"] == "exact_match" for row in rows))
        self.assertTrue(any(row["status"] == "material_difference" for row in rows))


if __name__ == "__main__":
    unittest.main()
