from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.canonical.factors import build_fundamentals_only_snapshot


class FundamentalsOnlyRankingTests(unittest.TestCase):
    def test_build_fundamentals_only_snapshot(self) -> None:
        companies = [{"company_id": "cmp1", "legal_name": "Acme"}]
        securities = [{"security_id": "sec1", "company_id": "cmp1"}]
        listings = [{"listing_id": "lst1", "security_id": "sec1", "ticker": "ACME", "exchange_code": "US", "country": "USA", "currency": "USD"}]
        fundamentals = [
            {"security_id": "sec1", "fiscal_period_end_date": "2024-03-31", "fiscal_period": "2024-03-31", "filing_date": "2024-05-01", "report_date": "2024-03-31", "revenue": 100.0, "gross_profit": 50.0, "operating_income": 20.0, "net_income": 10.0, "free_cash_flow": 8.0, "total_assets": 200.0, "total_equity": 100.0, "total_debt": 20.0, "cash_and_equivalents": 30.0},
            {"security_id": "sec1", "fiscal_period_end_date": "2024-06-30", "fiscal_period": "2024-06-30", "filing_date": "2024-08-01", "report_date": "2024-06-30", "revenue": 110.0, "gross_profit": 55.0, "operating_income": 22.0, "net_income": 11.0, "free_cash_flow": 9.0, "total_assets": 205.0, "total_equity": 101.0, "total_debt": 19.0, "cash_and_equivalents": 31.0},
            {"security_id": "sec1", "fiscal_period_end_date": "2024-09-30", "fiscal_period": "2024-09-30", "filing_date": "2024-11-01", "report_date": "2024-09-30", "revenue": 120.0, "gross_profit": 60.0, "operating_income": 24.0, "net_income": 12.0, "free_cash_flow": 10.0, "total_assets": 210.0, "total_equity": 102.0, "total_debt": 18.0, "cash_and_equivalents": 32.0},
            {"security_id": "sec1", "fiscal_period_end_date": "2024-12-31", "fiscal_period": "2024-12-31", "filing_date": "2025-02-01", "report_date": "2024-12-31", "revenue": 130.0, "gross_profit": 65.0, "operating_income": 26.0, "net_income": 13.0, "free_cash_flow": 11.0, "total_assets": 215.0, "total_equity": 103.0, "total_debt": 17.0, "cash_and_equivalents": 33.0},
        ]
        rows = build_fundamentals_only_snapshot("2025-03-01", companies, securities, listings, fundamentals, sectors={"sec1": "Tech"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ranking_mode"], "fundamentals_only")
        self.assertEqual(rows[0]["price_data_status"], "missing")
