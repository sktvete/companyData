from pathlib import Path
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import Settings
from equity_sorter.demo_data import build_demo_fixture
from equity_sorter.io_utils import read_json, read_jsonl, write_json
from equity_sorter.pipeline import build_quality_report, build_sample_snapshot, normalize_exchange_symbols, normalize_security_payloads


class DemoPipelineTests(unittest.TestCase):
    def test_demo_fixture_produces_rankings(self) -> None:
        tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmpdir, ignore_errors=True))
        settings = Settings(project_root=tmpdir, data_dir=tmpdir / "data", output_dir=tmpdir / "outputs")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        fixture = build_demo_fixture()
        bronze_date = "2026-05-09"

        for exchange_code in ["US", "OL"]:
            symbol_path = settings.data_dir / "bronze" / "provider=eodhd" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={bronze_date}" / "payload.json"
            write_json(symbol_path, {"request": {"fixture": True}, "payload": fixture["symbols"][exchange_code]})
            normalize_exchange_symbols(settings, exchange_code, bronze_date)
            for dataset_name, dataset_payload in [
                ("fundamentals", fixture["fundamentals"][exchange_code]),
                ("prices_daily", fixture["prices"][exchange_code]),
                ("corporate_actions_splits", fixture["splits"][exchange_code]),
                ("corporate_actions_dividends", fixture["dividends"][exchange_code]),
            ]:
                for symbol, payload in dataset_payload.items():
                    path = settings.data_dir / "bronze" / "provider=eodhd" / f"dataset={dataset_name}" / f"exchange={exchange_code}" / f"date={bronze_date}" / f"{symbol}.json"
                    write_json(path, payload)
            normalize_security_payloads(settings, exchange_code, bronze_date)
            quality_path = build_quality_report(settings, exchange_code, bronze_date)
            self.assertTrue(quality_path.exists())

        outputs = build_sample_snapshot(settings, "2025-05-30", snapshot_name="garp", exchange_codes=["US"])
        ranking_rows = read_jsonl(outputs["jsonl"])
        manifest = read_json(outputs["manifest"])
        self.assertGreaterEqual(len(ranking_rows), 3)
        self.assertEqual(ranking_rows[0]["rank"], 1)
        self.assertIn("source_checksums", manifest)


if __name__ == "__main__":
    unittest.main()
