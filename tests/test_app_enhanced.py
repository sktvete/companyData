"""Tests for web/app_enhanced.py (company + history APIs)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app_enhanced as ae  # noqa: E402


class AppEnhancedHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_get = ae._get_fundamentals
        cache = PROJECT_ROOT / "outputs" / "fundamentals_cache" / "AAPL.json"
        if not cache.exists():
            self.skipTest("AAPL fundamentals cache missing")
        self._aapl = json.loads(cache.read_text(encoding="utf-8"))

        def _patched(sym: str):
            if sym.upper() == "AAPL":
                return self._aapl
            return None

        ae._get_fundamentals = _patched
        ae.companies = [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "exchange": "US",
                "company_info": {"description": "x", "market_cap": 1e12, "pe_ratio": 30},
                "financial_metrics": {"revenue": 100e9},
                "investment_scores": {"overall_score": 10},
            }
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        self.client = ae.app.test_client()

    def tearDown(self) -> None:
        ae._get_fundamentals = self._orig_get

    def test_history_includes_oeps_per_share(self) -> None:
        r = self.client.get("/api/company/AAPL/history")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertNotIn("error", body)
        hist = body["history"]
        self.assertGreater(len(hist), 0)
        row = next(h for h in hist if h["year"] == "2024")
        self.assertIn("oeps", row)
        self.assertGreater(row["oeps"], 0)
        # OEPS should be same order of magnitude as EPS for a profitable year
        self.assertLess(abs(row["oeps"] - row["eps"]), max(row["eps"], 0.01) * 2)

    def test_api_company_symbol_case_insensitive(self) -> None:
        r = self.client.get("/api/company/aapl")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["symbol"], "AAPL")


class LoadDataPriorityTests(unittest.TestCase):
    def test_rescored_wins_over_scaled_when_both_exist(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        scaled_dir = tmp / "outputs" / "scaled_analysis"
        rescored_dir = tmp / "outputs" / "rescored_analysis"
        scaled_dir.mkdir(parents=True)
        rescored_dir.mkdir(parents=True)

        def line(sym: str, score: float) -> str:
            rec = {
                "symbol": sym,
                "name": sym,
                "sector": "X",
                "industry": "",
                "exchange": "US",
                "company_info": {},
                "financial_metrics": {},
                "investment_scores": {"overall_score": score},
            }
            return json.dumps(rec) + "\n"

        (scaled_dir / "scaled_analysis_x.jsonl").write_text(
            line("ZZSCALED", 5.0), encoding="utf-8"
        )
        (rescored_dir / "rescored_x.jsonl").write_text(
            line("ZZRESCORED", 19.0), encoding="utf-8"
        )

        orig_root = ae.PROJECT_ROOT
        ae.PROJECT_ROOT = tmp
        self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig_root))
        ok = ae.load_data()
        self.assertTrue(ok)
        self.assertEqual(ae.DATA_SOURCE, "rescored")
        self.assertEqual(ae.companies[0]["symbol"], "ZZRESCORED")


if __name__ == "__main__":
    unittest.main()
