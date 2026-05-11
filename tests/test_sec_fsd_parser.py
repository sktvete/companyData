from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.providers.sec_edgar.financial_statement_data_sets import normalize_dataset_quarter


class SECFSDParserTests(unittest.TestCase):
    def test_normalize_dataset_quarter(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        zip_path = tmpdir / "sample.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("sub.txt", "adsh\tcik\tname\tfye\tform\tperiod\tfy\tfp\tfiled\taccepted\n0001\t320193\tApple\t1231\t10-Q\t20240930\t2024\tQ3\t20241031\t2024-10-31 10:00:00.0\n")
            archive.writestr("num.txt", "adsh\ttag\tversion\tddate\tqtrs\tuom\tsegments\tcoreg\tvalue\tfootnote\n0001\tRevenues\tus-gaap/2024\t20240930\t1\tUSD\t\t\t100\t\n0001\tNetIncomeLoss\tus-gaap/2024\t20240930\t1\tUSD\t\t\t10\t\n0001\tAssets\tus-gaap/2024\t20240930\t0\tUSD\t\t\t500\t\n0001\tCashAndCashEquivalentsAtCarryingValue\tus-gaap/2024\t20240930\t0\tUSD\t\t\t50\t\n")
            archive.writestr("pre.txt", "")
            archive.writestr("tag.txt", "")
        rows = normalize_dataset_quarter(zip_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revenue"], 100.0)
        self.assertEqual(rows[0]["net_income"], 10.0)
        self.assertEqual(rows[0]["total_assets"], 500.0)
