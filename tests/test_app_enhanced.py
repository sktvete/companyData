"""Tests for web/app_enhanced.py (company + history APIs)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_history_drops_estimate_for_reported_fy(self) -> None:
        from datetime import datetime, timedelta

        end = datetime.now().date()
        mock_prices = [
            {
                "date": (end - timedelta(days=400 - i)).strftime("%Y-%m-%d"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000,
            }
            for i in range(400)
        ]
        with patch.object(ae, "_fetch_full_price_history", return_value=mock_prices):
            r = self.client.get("/api/company/AAPL/history")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        hist_years = {h["year"] for h in body.get("history", [])}
        for est in body.get("estimates", []):
            fy = str(est.get("fiscal_year", ""))
            self.assertNotIn(
                fy,
                hist_years,
                msg=f"estimate {est.get('year')} overlaps reported FY{fy}",
            )

    def test_history_includes_price_chart_1y(self) -> None:
        from datetime import datetime, timedelta

        end = datetime.now().date()
        mock_prices = [
            {
                "date": (end - timedelta(days=400 - i)).strftime("%Y-%m-%d"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + i * 0.05,
                "volume": 1_000_000,
            }
            for i in range(400)
        ]
        with patch.object(ae, "_fetch_full_price_history", return_value=mock_prices):
            r = self.client.get("/api/company/AAPL/history")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        chart = body.get("price_chart_1y")
        self.assertIsInstance(chart, list)
        self.assertGreater(len(chart), 0)
        self.assertLessEqual(len(chart), ae._MAX_CHART_POINTS)
        self.assertIn("close", chart[0])

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

    def test_history_graceful_when_no_fundamentals(self) -> None:
        ae._get_fundamentals = lambda s: None
        r = self.client.get("/api/company/AAPL/history")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body.get("partial"))
        self.assertEqual(body.get("history"), [])
        self.assertNotIn("error", body)

    def test_invalid_symbol_returns_400(self) -> None:
        r = self.client.get("/api/company/%20/history")
        self.assertEqual(r.status_code, 400)

    def test_chat_requires_chatgpt_sign_in(self) -> None:
        with patch("app_enhanced.codex_chat.auth_status", return_value={"authenticated": False}):
            r = self.client.post(
                "/api/company/AAPL/chat",
                json={"message": "What is revenue?"},
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 503)
        self.assertIn("Sign in with ChatGPT", r.get_json().get("error", ""))

    def test_chat_requires_message(self) -> None:
        with patch("app_enhanced.codex_chat.auth_status", return_value={"authenticated": True}):
            r = self.client.post(
                "/api/company/AAPL/chat",
                json={},
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)

    def test_chat_success_with_mock_codex(self) -> None:
        def _fake_stream(*_a, **_k):
            yield {"token": "Revenue is in the context."}
            yield {"done": True}

        with patch("app_enhanced.codex_chat.auth_status", return_value={"authenticated": True}):
            with patch("app_enhanced.codex_chat.stream_codex_chat", side_effect=_fake_stream):
                r = self.client.post(
                    "/api/company/AAPL/chat",
                    json={"message": "Summarize revenue."},
                    content_type="application/json",
                )
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        body = r.get_json()
        self.assertEqual(body.get("reply"), "Revenue is in the context.")
        self.assertEqual(body.get("provider"), "chatgpt")

    def test_chat_stream_ndjson(self) -> None:
        def _fake_stream(*_a, **_k):
            yield {"token": "Hi "}
            yield {"token": "stream."}
            yield {"done": True}

        with patch("app_enhanced.codex_chat.auth_status", return_value={"authenticated": True}):
            with patch("app_enhanced.codex_chat.stream_codex_chat", side_effect=_fake_stream):
                r = self.client.post(
                    "/api/company/AAPL/chat/stream",
                    json={"message": "ping"},
                    content_type="application/json",
                )
                raw = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200, raw)
        self.assertEqual(r.mimetype, "application/x-ndjson")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        objs = [json.loads(ln) for ln in lines]
        tokens = "".join(o.get("token", "") for o in objs if "token" in o)
        self.assertIn("Hi stream.", tokens)
        self.assertTrue(any(o.get("done") for o in objs))


class ApiSummaryJsonTests(unittest.TestCase):
    def test_summary_json_serializable_with_null_sector(self) -> None:
        """Regression: None sector/category must not break jsonify."""
        ae.companies = [
            {
                "symbol": "ZNULL",
                "name": "Z",
                "sector": None,
                "exchange": "US",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e8},
                "investment_scores": {
                    "overall_score": 1.0,
                    "investment_category": None,
                    "growth_score": 0,
                },
            }
        ]
        ae.company_lookup = {"ZNULL": ae.companies[0]}
        r = ae.app.test_client().get("/api/summary")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertIn("sectors", body)
        self.assertIn("Unknown", body["sectors"])


class FilterSortApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_c = ae.companies
        self._orig_l = ae.company_lookup
        self._orig_ranks = ae.screener_rank_by_symbol
        self._orig_listing_sorted = ae._companies_listing_sorted
        ae._companies_listing_sorted = False
        ae.companies = [
            {
                "symbol": "ACC1",
                "name": "Café Démo North America",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9},
                "investment_scores": {
                    "overall_score": 10.0,
                    "quality_score": 3.0,
                    "value_score": 3.0,
                    "growth_score": 3.0,
                    "safety_score": 3.0,
                    "tenx_score": 50.0,
                },
                "analyst_ratings": {"Rating": 4.5},
            },
            {
                "symbol": "ZZZ",
                "name": "Other Corp",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9},
                "investment_scores": {
                    "overall_score": 12.0,
                    "quality_score": 1.0,
                    "value_score": 1.0,
                    "growth_score": 1.0,
                    "safety_score": 1.0,
                    "tenx_score": 10.0,
                },
                "analyst_ratings": {"Rating": 2.5},
            },
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}

    def tearDown(self) -> None:
        ae.companies = self._orig_c
        ae.company_lookup = self._orig_l
        ae.screener_rank_by_symbol = self._orig_ranks
        ae._companies_listing_sorted = self._orig_listing_sorted

    def test_search_matches_accented_name(self) -> None:
        c = ae.app.test_client()
        r = c.get("/api/companies?search=cafe+demo&limit=50")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        syms = {x["symbol"] for x in d["companies"]}
        self.assertIn("ACC1", syms)

    def test_sort_analyst_column(self) -> None:
        c = ae.app.test_client()
        r = c.get("/api/companies?sort_by=analyst&sort_order=desc&limit=50")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertGreaterEqual(len(d["companies"]), 2)
        self.assertEqual(d["companies"][0]["symbol"], "ACC1")

    def test_api_companies_effective_sort_and_score_fields(self) -> None:
        c = ae.app.test_client()
        d = c.get("/api/companies?sort_by=listing_score&limit=10").get_json()
        self.assertEqual(d.get("effective_sort"), "listing_score")
        self.assertFalse(d.get("use_custom_weights"))
        self.assertEqual(d.get("sort_by"), "listing_score")
        row = d["companies"][0]
        self.assertIn("listing_score", row)
        self.assertIn("custom_score", row)

        du = c.get(
            "/api/companies?sort_by=listing_score&wc=1&wq=10&wv=0&wg=0&ws=0&limit=10",
        ).get_json()
        self.assertEqual(du.get("effective_sort"), "custom_score")
        self.assertTrue(du.get("use_custom_weights"))

    def test_api_companies_rank_matches_filtered_order(self) -> None:
        c = ae.app.test_client()
        d = c.get("/api/companies?sort_by=symbol&sort_order=asc&limit=1&offset=0").get_json()
        self.assertEqual(d["companies"][0]["rank"], 1)
        d2 = c.get("/api/companies?sort_by=symbol&sort_order=asc&limit=1&offset=1").get_json()
        self.assertEqual(d2["companies"][0]["rank"], 2)
        d3 = c.get("/api/companies?search=cafe+demo&sort_by=symbol&sort_order=asc&limit=50").get_json()
        for i, row in enumerate(d3["companies"]):
            self.assertEqual(row["rank"], i + 1)

    def test_api_companies_screener_rank_is_universe_position(self) -> None:
        ae.companies = [
            {
                "symbol": "HIGH",
                "name": "High",
                "sector": "Technology",
                "company_info": {"market_cap": 50e9},
                "financial_metrics": {
                    "revenue": 10e9,
                    "roe": 0.2,
                    "roic": 0.2,
                    "gross_margin": 0.5,
                    "revenue_growth_consistency": 0.8,
                },
                "investment_scores": {
                    "overall_score": 18,
                    "quality_score": 4,
                    "value_score": 4,
                    "growth_score": 4,
                    "safety_score": 4,
                    "peg_ratio": 0.5,
                },
            },
            {
                "symbol": "LOW",
                "name": "Low",
                "sector": "Technology",
                "company_info": {"market_cap": 5e9},
                "financial_metrics": {
                    "revenue": 1e9,
                    "roe": 0.05,
                    "roic": 0.05,
                    "gross_margin": 0.2,
                    "revenue_growth_consistency": 0.3,
                },
                "investment_scores": {
                    "overall_score": 6,
                    "quality_score": 1,
                    "value_score": 1,
                    "growth_score": 1,
                    "safety_score": 1,
                    "peg_ratio": 3.0,
                },
            },
        ]
        ae.companies = sorted(
            ae.companies,
            key=lambda c: (-ae._compounder_list_score(c), c.get("symbol") or ""),
        )
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        ae._rebuild_screener_ranks()
        c = ae.app.test_client()
        d = c.get("/api/companies?search=LOW&limit=1").get_json()
        row = d["companies"][0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["screener_rank"], 2)
        d2 = c.get("/api/company/LOW").get_json()
        self.assertEqual(d2["screener_rank"], 2)
        self.assertGreater(d2["listing_score"], 0)

    def test_companies_list_monotonic_listing_score(self) -> None:
        if len(ae.companies) < 2:
            self.skipTest("universe not loaded")
        for i in range(len(ae.companies) - 1):
            a = ae._compounder_list_score(ae.companies[i])
            b = ae._compounder_list_score(ae.companies[i + 1])
            self.assertGreaterEqual(
                a, b,
                msg=f"{ae.companies[i]['symbol']} ({a}) before {ae.companies[i+1]['symbol']} ({b})",
            )

    def test_momentum_score_ranks_high_growth_first(self) -> None:
        ae.companies = [
            {
                "symbol": "FAST",
                "name": "Fast",
                "sector": "Technology",
                "data_quality": {"min_quarters": 12},
                "financial_metrics": {
                    "revenue_growth_1y": 0.45,
                    "latest_quarter_revenue_growth": 0.50,
                    "revenue_acceleration": 0.12,
                    "eps_growth": 0.40,
                },
                "investment_scores": {"overall_score": 10},
            },
            {
                "symbol": "SLOW",
                "name": "Slow",
                "sector": "Technology",
                "data_quality": {"min_quarters": 12},
                "financial_metrics": {
                    "revenue_growth_1y": 0.03,
                    "revenue_acceleration": -0.02,
                    "eps_growth": 0.02,
                },
                "investment_scores": {"overall_score": 14},
            },
        ]
        ae._rebuild_momentum_ranks()
        self.assertGreater(
            ae._cached_momentum_score(ae.companies[0]),
            ae._cached_momentum_score(ae.companies[1]),
        )
        c = ae.app.test_client()
        d = c.get("/api/companies?sort_by=momentum_score&limit=2").get_json()
        self.assertEqual(d["companies"][0]["symbol"], "FAST")
        self.assertEqual(d["companies"][0]["momentum_rank"], 1)
        short = c.get("/api/screener/high-growth-shortlist?limit=10&min_rev_growth_pct=10").get_json()
        self.assertGreaterEqual(short["total_qualified"], 1)
        self.assertEqual(short["candidates"][0]["symbol"], "FAST")

    def test_weight_custom_flag_with_default_sliders_changes_blend(self) -> None:
        c = ae.app.test_client()
        r = c.get(
            "/api/companies?sort_by=overall_score&wc=1"
            "&wq=10&wv=0&wg=0&ws=0&wa=0&limit=50",
        )
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["companies"][0]["symbol"], "ACC1")

    def test_growth_sort_tiebreaks_headline_pct(self) -> None:
        oc, ol = ae.companies, ae.company_lookup
        ae.companies = [
            {
                "symbol": "LOWR",
                "name": "Low tail",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9, "roic": 0.1},
                "investment_scores": {
                    "growth_score": 3.0,
                    "roic_pct": 5.0,
                    "revenue_cagr_3y_pct": 2.0,
                    "oeps_cagr_pct": 1.0,
                },
            },
            {
                "symbol": "HIGHR",
                "name": "High tail",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9, "roic": 0.5},
                "investment_scores": {
                    "growth_score": 3.0,
                    "roic_pct": 40.0,
                    "revenue_cagr_3y_pct": 2.0,
                    "oeps_cagr_pct": 1.0,
                },
            },
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        try:
            cl = ae.app.test_client()
            d = cl.get("/api/companies?sort_by=growth_score&sort_order=desc&limit=10").get_json()
            self.assertEqual(d["companies"][0]["symbol"], "HIGHR")
            d2 = cl.get("/api/companies?sort_by=growth_score&sort_order=DESC&limit=10").get_json()
            self.assertEqual(d2["companies"][0]["symbol"], "HIGHR")
        finally:
            ae.companies, ae.company_lookup = oc, ol

    def test_sort_value_score_desc(self) -> None:
        oc, ol = ae.companies, ae.company_lookup
        ae.companies = [
            {
                "symbol": "HIVAL",
                "name": "Cheap",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9},
                "investment_scores": {"value_score": 4.9, "overall_score": 10.0},
            },
            {
                "symbol": "LOVAL",
                "name": "Rich",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9},
                "investment_scores": {"value_score": 2.1, "overall_score": 12.0},
            },
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        try:
            cl = ae.app.test_client()
            d = cl.get("/api/companies?sort_by=value_score&sort_order=desc&limit=10").get_json()
            self.assertEqual(d["companies"][0]["symbol"], "HIVAL")
        finally:
            ae.companies, ae.company_lookup = oc, ol

    def test_sort_listing_score_desc(self) -> None:
        """Default compounder sort: higher listing_score first."""
        oc, ol = ae.companies, ae.company_lookup
        ae.companies = [
            {
                "symbol": "LOWLIST",
                "name": "Low compounder",
                "sector": "Technology",
                "industry": "Software",
                "company_info": {"market_cap": 1e9, "pe_ratio": 20.0},
                "financial_metrics": {
                    "revenue": 5e6,
                    "net_income": 1e6,
                    "free_cash_flow": 8e5,
                    "gross_margin": 0.5,
                    "roic": 0.12,
                    "roe": 0.14,
                    "red_flag_count": 0,
                },
                "data_quality": {"min_quarters": 40},
                "investment_scores": {
                    "overall_score": 18.0,
                    "quality_score": 5.0,
                    "growth_score": 4.0,
                    "value_score": 4.0,
                    "safety_score": 5.0,
                },
            },
            {
                "symbol": "HILIST",
                "name": "High compounder",
                "sector": "Technology",
                "industry": "Software",
                "company_info": {"market_cap": 80e9, "pe_ratio": 22.0},
                "financial_metrics": {
                    "revenue": 40e9,
                    "net_income": 5e9,
                    "free_cash_flow": 4e9,
                    "gross_margin": 0.45,
                    "roic": 0.20,
                    "roe": 0.22,
                    "red_flag_count": 0,
                },
                "data_quality": {"min_quarters": 60},
                "investment_scores": {
                    "overall_score": 14.0,
                    "quality_score": 4.0,
                    "growth_score": 3.5,
                    "value_score": 3.5,
                    "safety_score": 4.5,
                },
            },
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        try:
            low_ls = ae._compounder_list_score(ae.companies[0])
            high_ls = ae._compounder_list_score(ae.companies[1])
            self.assertGreater(high_ls, low_ls, "fixture should rank HILIST above LOWLIST")
            cl = ae.app.test_client()
            d = cl.get("/api/companies?sort_by=listing_score&sort_order=desc&limit=10").get_json()
            self.assertEqual(d["companies"][0]["symbol"], "HILIST")
            d2 = cl.get("/api/companies?sort_by=overall_score&sort_order=desc&limit=10").get_json()
            self.assertEqual(d2["companies"][0]["symbol"], "LOWLIST")
        finally:
            ae.companies, ae.company_lookup = oc, ol

    def test_growth_sort_recovers_from_bad_roic_pct(self) -> None:
        """Tiebreak must not treat roic_pct*100 applied to an already-percent roic field."""
        oc, ol = ae.companies, ae.company_lookup
        ae.companies = [
            {
                "symbol": "BADTB",
                "name": "Bad tiebreak",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9, "roic": 0.25},
                "investment_scores": {
                    "growth_score": 2.0,
                    "roic_pct": 5000.0,
                    "revenue_cagr_3y_pct": 1.0,
                    "oeps_cagr_pct": 1.0,
                },
            },
            {
                "symbol": "GOODTB",
                "name": "Good tiebreak",
                "sector": "Technology",
                "company_info": {"market_cap": 1e9},
                "financial_metrics": {"revenue": 1e9, "roic": 0.40},
                "investment_scores": {
                    "growth_score": 2.0,
                    "roic_pct": 10.0,
                    "revenue_cagr_3y_pct": 1.0,
                    "oeps_cagr_pct": 1.0,
                },
            },
        ]
        ae.company_lookup = {c["symbol"]: c for c in ae.companies}
        try:
            cl = ae.app.test_client()
            d = cl.get("/api/companies?sort_by=growth_score&sort_order=desc&limit=10").get_json()
            self.assertEqual(d["companies"][0]["symbol"], "GOODTB")
        finally:
            ae.companies, ae.company_lookup = oc, ol


class ChatHistoryNormalizeTests(unittest.TestCase):
    def test_drops_leading_assistant(self) -> None:
        h = [
            {"role": "assistant", "content": "orphan"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ]
        out = ae._normalize_chat_history(h, 99)
        self.assertEqual([x["role"] for x in out], ["user", "assistant"])

    def test_trim_keeps_user_first(self) -> None:
        h = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "A"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "B"},
            {"role": "user", "content": "c"},
        ]
        out = ae._normalize_chat_history(h, 3)
        self.assertEqual(out[0]["role"], "user")
        self.assertLessEqual(len(out), 3)


class CompounderRankTests(unittest.TestCase):
    def test_compounder_prefers_scale_at_same_raw_score(self) -> None:
        def row(sym: str, overall: float, rev: float, mcap: float, gm: float) -> dict:
            return {
                "symbol": sym,
                "investment_scores": {"overall_score": overall},
                "financial_metrics": {"revenue": rev, "gross_margin": gm},
                "company_info": {"market_cap": mcap},
            }

        big = row("BIG", 15.0, 5e9, 50e9, 0.40)
        sml = row("SML", 15.0, 100e6, 400e6, 1.05)
        self.assertGreater(ae._compounder_list_score(big), ae._compounder_list_score(sml))

    def test_per_share_distortion_factor(self) -> None:
        """High OEPS with modest revenue CAGR should not get full screener credit."""
        distorted = {
            "revenue_cagr_4y": 0.10,
            "revenue_cagr_3y": 0.09,
            "oeps_cagr": 0.41,
            "eps_growth": 0.0,
        }
        aligned = {
            "revenue_cagr_4y": 0.22,
            "revenue_cagr_3y": 0.22,
            "oeps_cagr": 0.40,
        }
        self.assertLess(ae._per_share_growth_distortion_factor(distorted), 0.9)
        self.assertEqual(ae._per_share_growth_distortion_factor(aligned), 1.0)

    def test_long_term_growth_factor_weights_revenue(self) -> None:
        m = {"revenue_cagr_4y": 0.20, "revenue_cagr_3y": 0.18, "oeps_cagr": 0.05}
        s = {}
        self.assertGreaterEqual(ae._long_term_growth_factor(m, s), 0.70)


class LoadDataPriorityTests(unittest.TestCase):
    def test_rescored_wins_over_scaled_when_both_exist(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        scaled_dir = tmp / "outputs" / "scaled_analysis"
        rescored_dir = tmp / "outputs" / "rescored_analysis"
        scaled_dir.mkdir(parents=True)
        rescored_dir.mkdir(parents=True)

        def _rich_metrics() -> dict:
            return {
                "roe": 0.35,
                "roic": 0.30,
                "roa": 0.20,
                "pe_ratio": 14.0,
                "peg_ratio": 0.55,
                "fcf_yield": 0.06,
                "ev_ebitda": 12.0,
                "oeps_cagr": 0.25,
                "revenue_cagr_3y": 0.20,
                "revenue_growth_1y": 0.15,
                "gross_margin": 0.45,
                "net_margin": 0.22,
                "altman_z_score": 5.0,
                "current_ratio": 2.0,
                "debt_to_equity": 0.4,
                "piotroski_score": 8,
                "fcf_conversion": 0.9,
                "red_flag_count": 0,
            }

        def line(sym: str, metrics: dict, name: str | None = None) -> str:
            rec = {
                "symbol": sym,
                "name": name or sym,
                "sector": "Technology",
                "industry": "Software",
                "exchange": "US",
                "company_info": {"market_cap": 50e9},
                "financial_metrics": metrics,
                "investment_scores": {"overall_score": 1.0, "value_score": 0},
            }
            return json.dumps(rec) + "\n"

        poor = {
            "roe": 0.05,
            "pe_ratio": 80.0,
            "peg_ratio": 4.0,
            "oeps_cagr": 0.02,
            "altman_z_score": 2.0,
            "current_ratio": 1.0,
            "debt_to_equity": 2.0,
            "piotroski_score": 3,
            "red_flag_count": 2,
        }
        scaled_path = scaled_dir / "scaled_analysis_x.jsonl"
        rescored_path = rescored_dir / "rescored_x.jsonl"
        scaled_path.write_text(
            line("ZZSCALED", poor) + line("ZZRESCORED", poor, name="Old"),
            encoding="utf-8",
        )
        rescored_path.write_text(
            line("ZZRESCORED", _rich_metrics(), name="Rescored Inc"),
            encoding="utf-8",
        )
        # Rescored overlay must be newer than scaled base.
        time.sleep(0.05)
        import os

        os.utime(rescored_path, (time.time() + 10, time.time() + 10))

        orig_root = ae.PROJECT_ROOT
        ae.PROJECT_ROOT = tmp
        self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig_root))
        ok = ae.load_data()
        self.assertTrue(ok)
        self.assertEqual(ae.DATA_SOURCE, "scaled+rescored_scores")
        self.assertEqual(len(ae.companies), 2)
        self.assertEqual(ae.companies[0]["symbol"], "ZZRESCORED")
        self.assertEqual(ae.companies[0]["name"], "Rescored Inc")
        self.assertGreater(
            ae.companies[0]["investment_scores"]["value_score"],
            ae.companies[1]["investment_scores"]["value_score"],
        )
        self.assertGreater(
            ae._compounder_list_score(ae.companies[0]),
            ae._compounder_list_score(ae.companies[1]),
        )

    def test_refresh_nvda_value_score_uses_peg(self) -> None:
        """Stale value_score=0 in jsonl must not survive load when PEG is strong."""
        nvda_path = PROJECT_ROOT / "outputs" / "scaled_analysis" / "scaled_analysis_20260513_225040.jsonl"
        if not nvda_path.is_file():
            self.skipTest("NVDA universe file missing")
        row = None
        for line in nvda_path.open(encoding="utf-8"):
            rec = json.loads(line)
            if rec.get("symbol") == "NVDA":
                row = rec
                break
        self.assertIsNotNone(row)
        row = dict(row)
        row["investment_scores"] = dict(row.get("investment_scores") or {})
        row["investment_scores"]["value_score"] = 0
        ae._refresh_investment_scores(row)
        peg = float(row["investment_scores"].get("peg_ratio") or 0)
        val = float(row["investment_scores"].get("value_score") or 0)
        if peg > 0 and peg <= 0.8:
            self.assertGreaterEqual(val, 2.0)


class SafeOutputsPathTests(unittest.TestCase):
    def test_rejects_parent_segments(self):
        self.assertIsNone(ae._safe_outputs_path("scaled_analysis/../../.env"))

    def test_rejects_absolute(self):
        self.assertIsNone(ae._safe_outputs_path("/etc/passwd"))

    def test_resolves_under_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs" / "a").mkdir(parents=True)
            (root / "outputs" / "a" / "b.txt").write_text("x", encoding="utf-8")
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))
            p = ae._safe_outputs_path("a/b.txt")
            self.assertIsNotNone(p)
            assert p is not None
            self.assertTrue(p.is_file())


class AnalysisRunApiTests(unittest.TestCase):
    def tearDown(self) -> None:
        if ae._analysis_lock.locked():
            ae._analysis_lock.release()

    def test_run_rejects_bad_symbols_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs").mkdir(parents=True)
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))
            client = ae.app.test_client()
            r = client.post("/api/analysis/run", json={"symbols_file": "foo/../../../x"})
            self.assertEqual(r.status_code, 400)
            self.assertIn("Invalid", r.get_json().get("error", ""))

    def test_run_rejects_missing_merge_into(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs" / "scaled_analysis").mkdir(parents=True)
            sym = root / "outputs" / "scaled_analysis" / "s.txt"
            sym.write_text("AAPL\n", encoding="utf-8")
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))
            client = ae.app.test_client()
            r = client.post(
                "/api/analysis/run",
                json={
                    "symbols_file": "scaled_analysis/s.txt",
                    "merge_into": "scaled_analysis/nope.jsonl",
                },
            )
            self.assertEqual(r.status_code, 404)

    def test_run_rejects_empty_symbols_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs" / "scaled_analysis").mkdir(parents=True)
            sym = root / "outputs" / "scaled_analysis" / "empty.txt"
            sym.write_text("# only comments\n\n", encoding="utf-8")
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))
            client = ae.app.test_client()
            r = client.post(
                "/api/analysis/run",
                json={"symbols_file": "scaled_analysis/empty.txt"},
            )
            self.assertEqual(r.status_code, 400)
            self.assertIn("empty", r.get_json().get("error", "").lower())

    @patch("app_enhanced.load_data")
    @patch("app_enhanced.subprocess.run", return_value=MagicMock(returncode=0))
    def test_run_passes_merge_and_symbols(self, mock_run, mock_load):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs" / "scaled_analysis").mkdir(parents=True)
            sym = root / "outputs" / "scaled_analysis" / "s.txt"
            sym.write_text("AAPL\n", encoding="utf-8")
            base = root / "outputs" / "scaled_analysis" / "base.jsonl"
            base.write_text("{}\n", encoding="utf-8")
            script = root / "scripts" / "scale_analysis_1000.py"
            script.parent.mkdir(parents=True)
            script.write_text("# stub\n", encoding="utf-8")
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))

            def run_target(**kw):
                kw["target"]()
                return MagicMock(start=lambda: None)

            with patch("app_enhanced.threading.Thread", side_effect=run_target):
                client = ae.app.test_client()
                r = client.post(
                    "/api/analysis/run",
                    json={
                        "target": 50,
                        "workers": 3,
                        "symbols_file": "scaled_analysis/s.txt",
                        "merge_into": "scaled_analysis/base.jsonl",
                    },
                )
            self.assertEqual(r.status_code, 200)
            body = r.get_json()
            self.assertTrue(body.get("started"))
            self.assertEqual(body.get("symbols_file"), "scaled_analysis/s.txt")
            self.assertEqual(body.get("merge_into"), "scaled_analysis/base.jsonl")
            cmd = mock_run.call_args[0][0]
            self.assertEqual(cmd[0], sys.executable)
            self.assertIn("scale_analysis_1000.py", str(cmd[1]))
            self.assertIn("--symbols-file", cmd)
            self.assertIn("--merge-into", cmd)
            self.assertIn(str(sym.resolve()), cmd)
            self.assertIn(str(base.resolve()), cmd)

    @patch("app_enhanced.load_data")
    @patch("app_enhanced.subprocess.run")
    def test_run_primes_progress_before_worker(self, mock_run, mock_load):
        """Regression: progress must show running before first poll (no stale running:false)."""
        import time as _time

        def slow_run(*_a, **_k):
            _time.sleep(2.0)
            return MagicMock(returncode=0)

        mock_run.side_effect = slow_run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outputs" / "scaled_analysis").mkdir(parents=True)
            sym = root / "outputs" / "scaled_analysis" / "s.txt"
            sym.write_text("AAPL\n", encoding="utf-8")
            script = root / "scripts" / "scale_analysis_1000.py"
            script.parent.mkdir(parents=True)
            script.write_text("# stub\n", encoding="utf-8")
            orig = ae.PROJECT_ROOT
            ae.PROJECT_ROOT = root
            self.addCleanup(lambda: setattr(ae, "PROJECT_ROOT", orig))

            client = ae.app.test_client()
            r = client.post(
                "/api/analysis/run",
                json={"target": 50, "workers": 2, "symbols_file": "scaled_analysis/s.txt"},
            )
            self.assertEqual(r.status_code, 200)
            pf = root / "outputs" / "analysis_progress.json"
            self.assertTrue(pf.exists(), "progress file should exist immediately after POST")
            data = json.loads(pf.read_text(encoding="utf-8"))
            self.assertTrue(data.get("running"), data)
            self.assertGreaterEqual(data.get("total", 0), 1)
            _time.sleep(2.3)


class PriceHistorySliceTests(unittest.TestCase):
    def _daily(self, n: int) -> list:
        from datetime import datetime, timedelta
        end = datetime.now().date()
        return [
            {
                "date": (end - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d"),
                "close": 100.0 + i * 0.1,
            }
            for i in range(n)
        ]

    def test_short_range_expands_to_min_200_points(self) -> None:
        prices = self._daily(400)
        out = ae._slice_and_downsample(prices, "1w")
        self.assertGreaterEqual(len(out), ae._MIN_CHART_POINTS)
        self.assertLessEqual(len(out), ae._MAX_CHART_POINTS)

    def test_long_range_caps_at_400(self) -> None:
        prices = self._daily(800)
        out = ae._slice_and_downsample(prices, "max")
        self.assertEqual(len(out), ae._MAX_CHART_POINTS)
        self.assertEqual(out[-1]["date"], prices[-1]["date"])

    def test_one_year_keeps_natural_density(self) -> None:
        prices = self._daily(300)
        out = ae._slice_and_downsample(prices, "1y")
        self.assertGreaterEqual(len(out), 200)
        self.assertLessEqual(len(out), 400)

    def test_1d_stays_short_without_200_expansion(self) -> None:
        prices = self._daily(400)
        out = ae._slice_and_downsample(prices, "1d")
        self.assertLessEqual(len(out), 12)
        self.assertGreaterEqual(len(out), 1)

    def test_apply_price_density_quarter(self) -> None:
        prices = self._daily(400)
        full = ae._slice_and_downsample(prices, "1y")
        preview = ae._apply_price_density(full, 0.25)
        self.assertLess(len(preview), len(full))
        self.assertGreaterEqual(len(preview), 50)

    def test_chart_prices_for_range_matches_slice(self) -> None:
        prices = self._daily(400)
        self.assertEqual(
            ae._chart_prices_for_range(prices, "1y"),
            ae._slice_and_downsample(prices, "1y"),
        )

    def test_drop_estimates_when_annual_reported(self) -> None:
        hist = [{"year": "2026", "revenue_usd": 100e9}]
        ests = [
            {"year": "FY2026E", "fiscal_year": 2026, "revenue_usd": 99e9},
            {"year": "FY2027E", "fiscal_year": 2027, "revenue_usd": 120e9},
        ]
        out = ae._drop_estimates_for_reported_years(hist, ests)
        self.assertEqual([e["year"] for e in out], ["FY2027E"])


class LiveQuoteTests(unittest.TestCase):
    def test_us_market_session_regular_hours(self) -> None:
        from datetime import datetime

        noon = datetime(2026, 5, 20, 12, 0, tzinfo=ae._ET)
        self.assertEqual(ae._us_market_session_now(noon), "regular")

    def test_us_market_session_after_hours(self) -> None:
        from datetime import datetime

        evening = datetime(2026, 5, 20, 17, 30, tzinfo=ae._ET)
        self.assertEqual(ae._us_market_session_now(evening), "after_hours")

    def test_parse_us_quote_delayed_extended(self) -> None:
        row = {
            "lastTradePrice": 220.0,
            "lastTradeTime": 1000,
            "previousClosePrice": 215.0,
            "ethPrice": 222.5,
            "ethTime": 2000,
            "change": 5.0,
            "changePercent": 2.3,
        }
        q = ae._parse_us_quote_delayed(row, "after_hours")
        self.assertIsNotNone(q)
        self.assertEqual(q["price"], 222.5)
        self.assertEqual(q["session"], "after_hours")
        self.assertAlmostEqual(q["change"], 2.5, places=2)

    def test_parse_us_quote_delayed_regular(self) -> None:
        row = {
            "lastTradePrice": 225.0,
            "lastTradeTime": 3000,
            "previousClosePrice": 220.0,
            "ethPrice": 222.0,
            "ethTime": 1000,
            "change": 5.0,
            "changePercent": 2.27,
        }
        q = ae._parse_us_quote_delayed(row, "regular")
        self.assertEqual(q["price"], 225.0)
        self.assertEqual(q["session"], "regular")

    def test_parse_eodhd_realtime_quote(self) -> None:
        raw = {
            "code": "AAPL.US",
            "close": 227.72,
            "previousClose": 226.4,
            "change": 1.32,
            "change_p": 0.5829,
            "timestamp": 1690381773,
        }
        q = ae._parse_eodhd_realtime_quote(raw)
        self.assertIsNotNone(q)
        self.assertEqual(q["price"], 227.72)
        self.assertEqual(q["previous_close"], 226.4)

    def test_api_company_quote(self) -> None:
        fake = {
            "price": 100.0,
            "previous_close": 98.0,
            "change": 2.0,
            "change_pct": 2.04,
            "as_of": "2026-05-16T15:30:00",
            "session": "regular",
            "session_label": "Live",
            "market_open": True,
        }
        with unittest.mock.patch.object(ae, "_get_live_quote", return_value=fake):
            c = ae.app.test_client()
            r = c.get("/api/company/TEST/quote")
            self.assertEqual(r.status_code, 200)
            d = r.get_json()
            self.assertEqual(d["price"], 100.0)


class EodhdFundamentalsHelpersTests(unittest.TestCase):
    def test_merged_highlights_from_top_level(self) -> None:
        d = {"Highlights": {}, "PERatio": 12.5, "EarningsShare": 8.74, "MarketCapitalization": 5e9}
        h = ae._merged_highlights(d)
        self.assertEqual(h.get("EarningsShare"), 8.74)
        self.assertEqual(h.get("PERatio"), 12.5)
        self.assertEqual(h.get("MarketCapitalization"), 5e9)

    def test_merged_highlights_keeps_nested_when_present(self) -> None:
        d = {"Highlights": {"PERatio": 10}, "PERatio": 12.0}
        h = ae._merged_highlights(d)
        self.assertEqual(h.get("PERatio"), 10)

    def test_eodhd_adjust_gross_profit(self) -> None:
        self.assertAlmostEqual(ae._eodhd_adjust_gross_profit(100.0, 100.0, 30.0), 70.0)
        self.assertAlmostEqual(ae._eodhd_adjust_gross_profit(100.0, 50.0, 30.0), 50.0)

    def test_sanitize_revenue_estimate_zar_scale(self) -> None:
        ref = 8.75e9
        bad = 213.576751540e9
        fixed = ae._sanitize_revenue_estimate(bad, ref)
        self.assertIsNotNone(fixed)
        self.assertAlmostEqual(fixed / ref, 1.35, delta=0.15)
        self.assertAlmostEqual(ae._sanitize_revenue_estimate(9e9, ref), 9e9)

    def test_build_ttm_uses_highlights_when_quarterly_eps_incomplete(self) -> None:
        dates = ["2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"]
        q_inc = {}
        q_cf = {}
        for i, dt in enumerate(dates):
            q_inc[dt] = {
                "totalRevenue": 100.0,
                "netIncome": 10.0,
                "grossProfit": 40.0,
                "costOfRevenue": 20.0,
            }
            if i < 2:
                q_inc[dt]["dilutedEPS"] = 0.25
            q_cf[dt] = {
                "totalCashFromOperatingActivities": 25.0,
                "capitalExpenditures": -2.0,
                "stockBasedCompensation": 1.0,
            }
        out = ae._build_ttm_window(
            q_inc,
            q_cf,
            {"SharesOutstanding": 10.0},
            10.0,
            [{"close": 100.0}],
            trailing_years=1,
            highlights={"EarningsShare": 4.5},
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertAlmostEqual(out["eps"], 4.5, places=3)

    def test_sec_edgar_document_url(self) -> None:
        u = ae._sec_edgar_document_url(
            "0000820313", "0001104659-26-054128", "aph-20260331x10q.htm",
        )
        self.assertIn("/Archives/edgar/data/820313/", u)
        self.assertTrue(u.endswith("aph-20260331x10q.htm"))

    def test_match_sec_filing_exact_date(self) -> None:
        sub = {
            "filings": {
                "recent": {
                    "form": ["10-Q", "10-K"],
                    "filingDate": ["2026-05-01", "2026-02-10"],
                    "accessionNumber": ["0001104659-26-054128", "0001104659-26-010000"],
                    "primaryDocument": ["aph-20260331x10q.htm", "aph-20251231x10k.htm"],
                }
            }
        }
        hit = ae._match_sec_filing(sub, "10-Q", "2026-05-01")
        self.assertEqual(hit, ("0001104659-26-054128", "aph-20260331x10q.htm"))

    def test_sec_edgar_filing_url_uses_document_when_matched(self) -> None:
        sub = {
            "filings": {
                "recent": {
                    "form": ["10-Q"],
                    "filingDate": ["2026-05-01"],
                    "accessionNumber": ["0001104659-26-054128"],
                    "primaryDocument": ["aph-20260331x10q.htm"],
                }
            }
        }
        u = ae._sec_edgar_filing_url("0000820313", "10-Q", "2026-05-01", sub)
        self.assertIn("/Archives/edgar/data/", u)
        self.assertNotIn("browse-edgar", u)

    def test_build_quarterly_report_events(self) -> None:
        d = {
            "General": {"CIK": "0001562088", "FiscalYearEnd": "December"},
            "Financials": {
                "Income_Statement": {
                    "quarterly": {
                        "2025-12-31": {
                            "date": "2025-12-31",
                            "filing_date": "2026-02-15",
                            "totalRevenue": 100,
                        },
                        "2025-09-30": {
                            "date": "2025-09-30",
                            "filing_date": "2025-11-05",
                            "totalRevenue": 90,
                        },
                    }
                }
            },
            "Earnings": {
                "History": {
                    "2025-12-31": {"date": "2025-12-31", "reportDate": "2026-02-20"},
                }
            },
        }
        with patch.object(ae, "_fetch_sec_submissions", return_value=None):
            events = ae._build_quarterly_report_events(d)
        self.assertEqual(len(events), 2)
        q4 = next(e for e in events if e["period_end"] == "2025-12-31")
        self.assertEqual(q4["form"], "10-K")
        self.assertEqual(q4["marker_date"], "2026-02-15")
        self.assertIn("browse-edgar", q4["sec_url"])
        self.assertIn("type=10-K", q4["sec_url"])
        q3 = next(e for e in events if e["period_end"] == "2025-09-30")
        self.assertEqual(q3["form"], "10-Q")


if __name__ == "__main__":
    unittest.main()
