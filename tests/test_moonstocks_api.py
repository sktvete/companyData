"""Moonstocks report API (SQLite + C#-compatible routes)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app_enhanced as ae  # noqa: E402


class MoonstocksApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db = Path(self._tmpdir.name) / "test_moonstocks.db"
        os.environ.pop("MOONSTOCKS_DATABASE_URL", None)
        os.environ.pop("DATABASE_URL", None)
        os.environ["MOONSTOCKS_DB_PATH"] = str(self._db)
        import moonstocks_store as ms_store

        ms_store.init_store(ae.PROJECT_ROOT)
        ae.companies = [
            {
                "symbol": "DECK",
                "name": "Deckers",
                "sector": "Consumer Cyclical",
                "company_info": {"market_cap": 1e10},
                "financial_metrics": {},
                "investment_scores": {"overall_score": 10},
            }
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        self.client = ae.app.test_client()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("MOONSTOCKS_DB_PATH", None)
        os.environ.pop("MOONSTOCKS_DATABASE_URL", None)

    def test_create_and_get_moonstocks_analysis(self) -> None:
        report = {
            "ticker": "DECK",
            "exchange": "US",
            "recommendation": "watchlist",
            "confidence": "medium",
            "overall_score": 62,
            "scores": {"quality_score": 7},
            "decision_summary": {"main_reason_for_recommendation": "Solid brand, rich valuation."},
        }
        r = self.client.post(
            "/api/analysis/DECK.US",
            json={"jsonReport": json.dumps(report)},
        )
        self.assertEqual(r.status_code, 200)

        r2 = self.client.get("/api/moonstocks/DECK.US")
        self.assertEqual(r2.status_code, 200)
        body = r2.get_json()
        self.assertEqual(body["tickerAndExchangeCode"], "DECK.US")
        self.assertEqual(body["report"]["recommendation"], "watchlist")

    def test_get_all_analyses_compat(self) -> None:
        self.client.post(
            "/api/analysis/AAA.US",
            json={"jsonReport": json.dumps({"recommendation": "no_buy", "overall_score": 40})},
        )
        rows = self.client.get("/api/analysis").get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tickerAndExchangeCode"], "AAA.US")

    def test_trigger_forwards_to_analyzer(self) -> None:
        with patch.object(ae, "_req") as mock_req:
            mock_resp = mock_req.post.return_value
            mock_resp.status_code = 202
            mock_resp.content = b'{"status":"accepted"}'
            mock_resp.json.return_value = {"status": "accepted"}

            r = self.client.post("/api/moonstocks/DECK.US/trigger")
            self.assertEqual(r.status_code, 202)
            mock_req.post.assert_called_once()
            url = mock_req.post.call_args[0][0]
            self.assertIn("DECK.US", url)

    def test_health(self) -> None:
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["service"], "equity-os")

    def test_company_page_has_moonstocks_ui(self) -> None:
        r = self.client.get("/company/DECK")
        self.assertEqual(r.status_code, 200)
        html = r.get_data(as_text=True)
        self.assertIn("msSection", html)
        self.assertIn("msTriggerBtn", html)

    def test_ingest_requires_api_key_when_configured(self) -> None:
        os.environ["ANALYZER_API_KEY"] = "test-secret"
        try:
            r = self.client.post(
                "/api/analysis/DECK.US",
                json={"jsonReport": json.dumps({"recommendation": "buy"})},
            )
            self.assertEqual(r.status_code, 401)
            r2 = self.client.post(
                "/api/analysis/DECK.US",
                json={"jsonReport": json.dumps({"recommendation": "buy"})},
                headers={"X-API-Key": "test-secret"},
            )
            self.assertEqual(r2.status_code, 200)
        finally:
            os.environ.pop("ANALYZER_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
