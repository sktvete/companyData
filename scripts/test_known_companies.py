#!/usr/bin/env python3

"""
Test Known High-Quality Companies
Tests comprehensive analysis on companies known to have complete financial data.
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_jsonl, write_json
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics
from equity_sorter.providers.eodhd.client import EODHDClient

def test_known_companies():
    """Test comprehensive analysis on known high-quality companies."""
    
    # List of companies known to have complete financial data
    known_companies = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "JNJ", "V",
        "PG", "UNH", "HD", "MA", "BAC", "XOM", "PFE", "CSCO", "KO", "PEP"
    ]
    
    print("🚀 Testing Known High-Quality Companies")
    print("=" * 60)
    print(f"📊 Testing {len(known_companies)} companies known to have complete data")
    
    settings = load_settings()
    client = EODHDClient(api_key=settings.eodhd_api_key)
    
    successful_analyses = []
    failed_companies = []
    
    for i, symbol in enumerate(known_companies, 1):
        print(f"\n🔍 [{i}/{len(known_companies)}] Testing {symbol}...")
        
        try:
            # Get fundamental data
            fundamentals = client.get_json(EODHDRequest(
                endpoint=f"fundamentals/{symbol}.US",
                params={}
            ))
            
            if not fundamentals or not isinstance(fundamentals, dict):
                print(f"    ❌ No fundamental data available")
                failed_companies.append({"symbol": symbol, "reason": "No fundamental data"})
                continue
            
            # Check data quality
            quarterly = fundamentals.get("quarterly_financials", {})
            income_statement = quarterly.get("income_statement", [])
            balance_sheet = quarterly.get("balance_sheet", [])
            cash_flow = quarterly.get("cash_flow", [])
            
            print(f"    📊 Data Quality Check:")
            print(f"      Quarters: {len(income_statement)}")
            print(f"      Balance Sheet: {len(balance_sheet)}")
            print(f"      Cash Flow: {len(cash_flow)}")
            
            # Require at least 4 quarters of each data type
            if len(income_statement) < 4 or len(balance_sheet) < 4 or len(cash_flow) < 4:
                print(f"    ❌ Insufficient data for comprehensive analysis")
                failed_companies.append({"symbol": symbol, "reason": "Insufficient historical data"})
                continue
            
            # Extract financial data for analysis
            financials = {
                "income_statement": income_statement[:4],
                "balance_sheet": balance_sheet[:4],
                "cash_flow": cash_flow[:4]
            }
            
            # Create price data from market cap
            highlights = fundamentals.get("highlights", {})
            market_cap = highlights.get("MarketCapitalization", 1000000000000)  # Default to $1T
            
            # Estimate price (assume 1B shares for simplicity)
            estimated_price = market_cap / 1000000000
            price_data = [{
                "date": "2024-12-31",
                "close": estimated_price,
                "market_cap": market_cap,
                "enterprise_value": market_cap * 1.2
            }]
            
            # Calculate comprehensive metrics
            metrics = calculate_comprehensive_metrics(financials, price_data)
            
            if "error" in metrics:
                print(f"    ❌ Metrics calculation failed: {metrics['error']}")
                failed_companies.append({"symbol": symbol, "reason": "Metrics calculation failed"})
                continue
            
            # Create company analysis
            analysis = {
                "symbol": symbol,
                "name": fundamentals.get("general", {}).get("CompanyName", symbol),
                "sector": fundamentals.get("general", {}).get("Sector", "Unknown"),
                "exchange": "US",
                "data_quality": {
                    "quarters": len(income_statement),
                    "balance_sheet": len(balance_sheet),
                    "cash_flow": len(cash_flow),
                    "completeness": "COMPLETE"
                },
                "financial_metrics": metrics,
                "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))])
            }
            
            # Calculate investment scores
            analysis["investment_scores"] = calculate_investment_scores(metrics)
            
            successful_analyses.append(analysis)
            
            # Show key results
            print(f"    ✅ Analysis successful!")
            print(f"    📊 Metrics: {analysis['metrics_count']}")
            print(f"    🎯 Overall Score: {analysis['investment_scores']['overall_score']}/20 ({analysis['investment_scores']['investment_category']})")
            print(f"    💰 Revenue: ${metrics.get('revenue', 0)/1e9:.1f}B")
            print(f"    📈 ROE: {metrics.get('roe', 0)*100:.1f}%")
            print(f"    💎 P/E: {metrics.get('pe_ratio', 0):.1f}")
            
        except Exception as e:
            print(f"    ❌ Error: {e}")
            failed_companies.append({"symbol": symbol, "reason": str(e)})
            continue
    
    # Sort by overall score
    successful_analyses.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)
    
    # Create summary
    summary = {
        "test_timestamp": datetime.now().isoformat(),
        "total_companies_tested": len(known_companies),
        "successful_analyses": len(successful_analyses),
        "failed_companies": len(failed_companies),
        "success_rate": len(successful_analyses) / len(known_companies) * 100,
        "average_metrics_count": sum(a["metrics_count"] for a in successful_analyses) / len(successful_analyses) if successful_analyses else 0,
        "top_performers": [
            {
                "rank": i + 1,
                "symbol": a["symbol"],
                "name": a["name"],
                "overall_score": a["investment_scores"]["overall_score"],
                "category": a["investment_scores"]["investment_category"],
                "metrics_count": a["metrics_count"],
                "revenue_b": a["financial_metrics"]["revenue"] / 1e9,
                "roe_pct": a["financial_metrics"]["roe"] * 100,
                "pe_ratio": a["financial_metrics"]["pe_ratio"]
            }
            for i, a in enumerate(successful_analyses[:10])
        ],
        "failed_companies": failed_companies
    }
    
    # Save results
    settings = load_settings()
    output_dir = settings.output_dir / "known_companies_test"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_file = output_dir / f"known_companies_analysis_{timestamp}.jsonl"
    summary_file = output_dir / f"test_summary_{timestamp}.json"
    
    write_jsonl(analysis_file, successful_analyses)
    write_json(summary_file, summary)
    
    # Display results
    print(f"\n🎉 Known Companies Test Complete!")
    print("=" * 60)
    print(f"📊 Companies Tested: {summary['total_companies_tested']}")
    print(f"✅ Successful Analyses: {summary['successful_analyses']}")
    print(f"❌ Failed Companies: {summary['failed_companies']}")
    print(f"📈 Success Rate: {summary['success_rate']:.1f}%")
    print(f"📊 Average Metrics: {summary['average_metrics_count']:.0f} per company")
    
    if summary["top_performers"]:
        print(f"\n🏆 Top 10 Performers:")
        for performer in summary["top_performers"]:
            print(f"  {performer['rank']:2d}. {performer['symbol']} - Score: {performer['overall_score']}/20 ({performer['category']})")
            print(f"      Revenue: ${performer['revenue_b']:.1f}B, ROE: {performer['roe_pct']:.1f}%, P/E: {performer['pe_ratio']:.1f}")
    
    if failed_companies:
        print(f"\n❌ Failed Companies:")
        for failure in failed_companies:
            print(f"  {failure['symbol']}: {failure['reason']}")
    
    print(f"\n📁 Results saved to: {output_dir}")
    print(f"📊 Analysis: {analysis_file}")
    print(f"📋 Summary: {summary_file}")
    
    return successful_analyses, summary

def calculate_investment_scores(metrics):
    """Calculate investment scores from financial metrics."""
    
    scores = {
        "value_score": 0,
        "quality_score": 0,
        "growth_score": 0,
        "safety_score": 0,
        "overall_score": 0,
        "investment_category": "UNKNOWN"
    }
    
    # Value Score (0-5)
    pe = metrics.get("pe_ratio", 999)
    pb = metrics.get("pb_ratio", 999)
    ps = metrics.get("ps_ratio", 999)
    
    if pe < 15:
        scores["value_score"] += 2
    elif pe < 25:
        scores["value_score"] += 1
    
    if pb < 2:
        scores["value_score"] += 2
    elif pb < 4:
        scores["value_score"] += 1
    
    if ps < 3:
        scores["value_score"] += 1
    
    # Quality Score (0-5)
    roe = metrics.get("roe", 0)
    debt_to_equity = metrics.get("debt_to_equity", 999)
    piotroski = metrics.get("piotroski_score", 0)
    
    if roe > 0.20:
        scores["quality_score"] += 2
    elif roe > 0.15:
        scores["quality_score"] += 1
    
    if debt_to_equity < 0.5:
        scores["quality_score"] += 2
    elif debt_to_equity < 1.0:
        scores["quality_score"] += 1
    
    if piotroski >= 7:
        scores["quality_score"] += 1
    
    # Growth Score (0-5)
    revenue_growth = metrics.get("revenue_growth_1y", 0)
    eps_growth = metrics.get("eps_growth", 0)
    roic = metrics.get("roic", 0)
    
    if revenue_growth > 0.20:
        scores["growth_score"] += 2
    elif revenue_growth > 0.10:
        scores["growth_score"] += 1
    
    if eps_growth > 0.20:
        scores["growth_score"] += 2
    elif eps_growth > 0.10:
        scores["growth_score"] += 1
    
    if roic > 0.15:
        scores["growth_score"] += 1
    
    # Safety Score (0-5)
    altman_z = metrics.get("altman_z_score", 0)
    current_ratio = metrics.get("current_ratio", 999)
    red_flags = metrics.get("red_flag_count", 0)
    
    if altman_z < 1.8:
        scores["safety_score"] -= 3
    elif altman_z < 3.0:
        scores["safety_score"] -= 1
    
    if current_ratio < 1.0:
        scores["safety_score"] -= 2
    elif current_ratio < 1.5:
        scores["safety_score"] -= 1
    
    if red_flags > 2:
        scores["safety_score"] -= 2
    elif red_flags > 0:
        scores["safety_score"] -= 1
    
    scores["safety_score"] = max(0, scores["safety_score"])
    
    # Overall Score
    scores["overall_score"] = scores["value_score"] + scores["quality_score"] + scores["growth_score"] + scores["safety_score"]
    
    # Investment Category
    overall = scores["overall_score"]
    if overall >= 16:
        scores["investment_category"] = "EXCELLENT"
    elif overall >= 12:
        scores["investment_category"] = "GOOD"
    elif overall >= 8:
        scores["investment_category"] = "FAIR"
    elif overall >= 4:
        scores["investment_category"] = "POOR"
    else:
        scores["investment_category"] = "RISKY"
    
    return scores

# Import EODHDRequest
from equity_sorter.providers.eodhd.client import EODHDRequest

if __name__ == "__main__":
    test_known_companies()
