from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import Settings
from equity_sorter.free_pipeline import build_free_us_quality_report, normalize_free_us_reference, normalize_free_us_security_payloads
from equity_sorter.free_us_demo_data import build_free_us_demo_fixture
from equity_sorter.io_utils import read_jsonl, write_json
from equity_sorter.pipeline import build_sample_snapshot


class FreeUSPipelineTests(unittest.TestCase):
    def test_free_us_demo_pipeline_builds_rankings(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        settings = Settings(project_root=tmpdir, data_dir=tmpdir / "data", output_dir=tmpdir / "outputs")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        fixture = build_free_us_demo_fixture()
        bronze_date = "2026-05-09"

        nasdaq_path = settings.data_dir / "bronze" / "provider=free_us" / "dataset=nasdaq_trader_symbols" / f"date={bronze_date}" / "symbols.txt"
        nasdaq_path.parent.mkdir(parents=True, exist_ok=True)
        nasdaq_path.write_text(fixture["nasdaq_trader_symbols"], encoding="utf-8")
        for cik, payload in fixture["sec_submissions"].items():
            write_json(settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=submissions" / f"date={bronze_date}" / f"{cik}.json", payload)
        for cik, payload in fixture["sec_companyfacts"].items():
            write_json(settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=companyfacts" / f"date={bronze_date}" / f"{cik}.json", payload)
        for symbol, csv_text in fixture["stooq_prices"].items():
            path = settings.data_dir / "bronze" / "provider=stooq" / "dataset=prices_daily" / f"date={bronze_date}" / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(csv_text, encoding="utf-8")

        normalize_free_us_reference(settings, bronze_date)
        normalize_free_us_security_payloads(settings, bronze_date)
        build_free_us_quality_report(settings, bronze_date)

        outputs = build_sample_snapshot(settings, "2025-05-30", snapshot_name="free_us_demo", exchange_codes=["US"])
        rankings = read_jsonl(outputs["jsonl"])
        candidates = read_jsonl(settings.data_dir / "silver" / "source_candidates" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
        self.assertGreaterEqual(len(rankings), 3)
        self.assertIn("confidence_score", rankings[0])
        self.assertTrue(any(row["source"] == "sec_edgar" for row in candidates))
        self.assertTrue(any(row["source"] == "stooq" for row in candidates))


if __name__ == "__main__":
    unittest.main()
