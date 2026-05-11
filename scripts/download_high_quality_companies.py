#!/usr/bin/env python3

"""
Download High-Quality Companies with Complete Financial Data
Filters for companies with complete fundamental data before analysis.
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_jsonl, write_json
from equity_sorter.providers.eodhd.client import EODHDClient

def check_data_quality(company_data: Dict[str, Any]) -> Dict[str, Any]:
    """Check if company has sufficient data for comprehensive analysis."""
    
    symbol = company_data.get("symbol", "Unknown")
    fundamentals = company_data.get("fundamentals", {})
    
    quality_score = 0
    max_score = 10
    issues = []
    
    # Check 1: General company info
    general = fundamentals.get("general", {})
    if general.get("CompanyName") and general.get("Sector"):
        quality_score += 1
    else:
        issues.append("Missing basic company info")
    
    # Check 2: Financial highlights
    highlights = fundamentals.get("highlights", {})
    required_highlights = ["MarketCapitalization", "EBITDA", "PERatio", "EPS"]
    highlights_count = sum(1 for field in required_highlights if highlights.get(field) is not None)
    if highlights_count >= 3:
        quality_score += 2
    else:
        issues.append(f"Insufficient financial highlights ({highlights_count}/4)")
    
    # Check 3: Quarterly financial data (at least 4 quarters)
    quarterly = fundamentals.get("quarterly_financials", {})
    income_statement = quarterly.get("income_statement", [])
    if len(income_statement) >= 4:
        quality_score += 2
        # Check data quality in recent quarters
        latest_quarter = income_statement[0]
        if latest_quarter.get("totalRevenue") and latest_quarter.get("netIncome"):
            quality_score += 1
        else:
            issues.append("Recent quarter missing revenue or income")
    else:
        issues.append(f"Insufficient quarterly data ({len(income_statement)} quarters)")
    
    # Check 4: Annual financial data (at least 3 years)
    annual = fundamentals.get("annual_financials", {})
    annual_income = annual.get("income_statement", [])
    if len(annual_income) >= 3:
        quality_score += 2
    else:
        issues.append(f"Insufficient annual data ({len(annual_income)} years)")
    
    # Check 5: Balance sheet data
    balance_sheet = quarterly.get("balance_sheet", [])
    if len(balance_sheet) >= 4:
        latest_bs = balance_sheet[0]
        if latest_bs.get("totalAssets") and latest_bs.get("totalStockholderEquity"):
            quality_score += 1
        else:
            issues.append("Balance sheet missing key fields")
    else:
        issues.append("Insufficient balance sheet data")
    
    # Check 6: Cash flow data
    cash_flow = quarterly.get("cash_flow", [])
    if len(cash_flow) >= 4:
        latest_cf = cash_flow[0]
        if latest_cf.get("operatingCashFlow"):
            quality_score += 1
        else:
            issues.append("Cash flow data incomplete")
    else:
        issues.append("Insufficient cash flow data")
    
    # Calculate quality percentage
    quality_percentage = (quality_score / max_score) * 100
    
    return {
        "symbol": symbol,
        "quality_score": quality_score,
        "max_score": max_score,
        "quality_percentage": quality_percentage,
        "data_quality": "EXCELLENT" if quality_percentage >= 80 else "GOOD" if quality_percentage >= 60 else "FAIR" if quality_percentage >= 40 else "POOR",
        "issues": issues,
        "data_points": {
            "quarters_available": len(income_statement),
            "years_available": len(annual_income),
            "has_balance_sheet": len(balance_sheet) > 0,
            "has_cash_flow": len(cash_flow) > 0,
            "highlights_count": highlights_count
        }
    }

def download_and_filter_companies(max_companies: int = 50, min_quality_score: int = 6) -> List[Dict[str, Any]]:
    """Download companies and filter for data quality."""
    
    print(f"🔍 Downloading and filtering high-quality companies...")
    print(f"📊 Target: {max_companies} companies with minimum quality score: {min_quality_score}")
    
    settings = load_settings()
    client = EODHDClient(api_key=settings.eodhd_api_key)
    
    # Get US exchange symbols
    print("📋 Getting US exchange symbols...")
    try:
        symbols_response = client.get_exchange_symbols("US")
        symbols = symbols_response if isinstance(symbols_response, list) else []
        
        # Filter for common stocks only
        common_stocks = [s for s in symbols if s.get("Type") == "Common Stock" and s.get("Exchange") in ["NASDAQ", "NYSE"]]
        print(f"📊 Found {len(common_stocks)} common stocks")
        
        # Prioritize large, well-known companies
        # Sort by trading volume or market cap if available, otherwise use a curated list
        priority_symbols = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "BRK.B", "JPM", "JNJ",
            "V", "PG", "UNH", "HD", "MA", "BAC", "XOM", "PFE", "CSCO", "KO", "PEP", "TMO", "ABT", "CRM",
            "ACN", "ADBE", "NFLX", "CMCSA", "INTC", "WFC", "VZ", "ORCL", "LIN", "TXN", "NKE", "DIS", "MDT",
            "PYPL", "ABNB", "QCOM", "NOW", "DHR", "AMGN", "HON", "UPS", "IBM", "BA", "CAT", "GE", "MMM"
        ]
        
        # Create priority list
        priority_list = []
        other_symbols = []
        
        for symbol in priority_symbols:
            matching = [s for s in common_stocks if s.get("Code") == symbol]
            if matching:
                priority_list.append(matching[0])
        
        for symbol in common_stocks:
            if symbol.get("Code") not in priority_symbols and symbol not in priority_list:
                other_symbols.append(symbol)
        
        # Combine: priority symbols first, then others
        sorted_symbols = priority_list + other_symbols[:max_companies - len(priority_list)]
        sorted_symbols = sorted_symbols[:max_companies]
        
        print(f"🎯 Selected {len(sorted_symbols)} companies for quality assessment")
        
    except Exception as e:
        print(f"❌ Error getting symbols: {e}")
        return []
    
    high_quality_companies = []
    assessed_count = 0
    
    for i, symbol_info in enumerate(sorted_symbols, 1):
        symbol = symbol_info.get("Code")
        print(f"🔍 [{i}/{len(sorted_symbols)}] Assessing {symbol}...")
        
        try:
            # Get fundamental data
            fundamentals = client.get_fundamentals(symbol)
            
            if fundamentals and isinstance(fundamentals, dict):
                company_data = {
                    "symbol": symbol,
                    "name": symbol_info.get("Name", symbol),
                    "exchange": symbol_info.get("Exchange", "US"),
                    "sector": symbol_info.get("Sector", "Unknown"),
                    "fundamentals": fundamentals
                }
                
                # Check data quality
                quality_assessment = check_data_quality(company_data)
                
                print(f"    Quality Score: {quality_assessment['quality_score']}/{quality_assessment['max_score']} ({quality_assessment['quality_percentage']:.0f}%) - {quality_assessment['data_quality']}")
                
                if quality_assessment["quality_score"] >= min_quality_score:
                    company_data["quality_assessment"] = quality_assessment
                    high_quality_companies.append(company_data)
                    print(f"    ✅ Added to high-quality list")
                else:
                    print(f"    ❌ Below quality threshold")
                    if quality_assessment["issues"]:
                        print(f"    Issues: {', '.join(quality_assessment['issues'][:2])}")
                
                assessed_count += 1
                
                # Stop if we have enough high-quality companies
                if len(high_quality_companies) >= max_companies:
                    print(f"🎯 Reached target of {max_companies} high-quality companies")
                    break
                    
        except Exception as e:
            print(f"    ❌ Error: {e}")
            continue
    
    print(f"\n🎉 Quality Assessment Complete!")
    print(f"📊 Companies Assessed: {assessed_count}")
    print(f"✅ High-Quality Companies: {len(high_quality_companies)}")
    print(f"📈 Success Rate: {len(high_quality_companies)/assessed_count*100:.1f}%")
    
    return high_quality_companies

def analyze_high_quality_companies(companies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run comprehensive analysis on high-quality companies."""
    
    print(f"\n🚀 Running comprehensive analysis on {len(companies)} high-quality companies...")
    
    from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics
    
    analyzed_companies = []
    
    for i, company in enumerate(companies, 1):
        symbol = company["symbol"]
        print(f"📊 [{i}/{len(companies)}] Analyzing {symbol}...")
        
        try:
            # Extract financial data
            fundamentals = company["fundamentals"]
            financials = {
                "income_statement": fundamentals.get("quarterly_financials", {}).get("income_statement", [])[:4],
                "balance_sheet": fundamentals.get("quarterly_financials", {}).get("balance_sheet", [])[:4],
                "cash_flow": fundamentals.get("quarterly_financials", {}).get("cash_flow", [])[:4]
            }
            
            # Create sample price data (since we don't have real-time prices)
            # In production, this would come from price API
            market_cap = fundamentals.get("highlights", {}).get("MarketCapitalization", 1000000000)
            sample_price = market_cap / 1000000000  # Assume 1B shares
            
            price_data = [{
                "date": "2024-12-31",
                "close": sample_price,
                "market_cap": market_cap,
                "enterprise_value": market_cap * 1.2
            }]
            
            # Calculate comprehensive metrics
            metrics = calculate_comprehensive_metrics(financials, price_data)
            
            if "error" not in metrics:
                analysis = {
                    "symbol": symbol,
                    "name": company["name"],
                    "exchange": company["exchange"],
                    "sector": company["sector"],
                    "quality_assessment": company["quality_assessment"],
                    "financial_metrics": metrics,
                    "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))])
                }
                
                # Calculate investment scores
                analysis["investment_scores"] = calculate_investment_scores(metrics)
                analyzed_companies.append(analysis)
                
                print(f"    ✅ Analysis complete: {analysis['metrics_count']} metrics calculated")
                print(f"    📊 Overall Score: {analysis['investment_scores']['overall_score']}/20 ({analysis['investment_scores']['investment_category']})")
                
            else:
                print(f"    ❌ Metrics calculation failed: {metrics['error']}")
                
        except Exception as e:
            print(f"    ❌ Analysis failed: {e}")
            continue
    
    # Sort by overall score
    analyzed_companies.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)
    
    return analyzed_companies

def calculate_investment_scores(metrics: Dict[str, Any]) -> Dict[str, Any]:
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
    if metrics.get("pe_ratio", 999) < 15:
        scores["value_score"] += 2
    elif metrics.get("pe_ratio", 999) < 25:
        scores["value_score"] += 1
    
    if metrics.get("pb_ratio", 999) < 2:
        scores["value_score"] += 2
    elif metrics.get("pb_ratio", 999) < 4:
        scores["value_score"] += 1
    
    if metrics.get("ps_ratio", 999) < 3:
        scores["value_score"] += 1
    
    # Quality Score (0-5)
    if metrics.get("roe", 0) > 0.20:
        scores["quality_score"] += 2
    elif metrics.get("roe", 0) > 0.15:
        scores["quality_score"] += 1
    
    if metrics.get("debt_to_equity", 999) < 0.5:
        scores["quality_score"] += 2
    elif metrics.get("debt_to_equity", 999) < 1.0:
        scores["quality_score"] += 1
    
    if metrics.get("piotroski_score", 0) >= 7:
        scores["quality_score"] += 1
    
    # Growth Score (0-5)
    if metrics.get("revenue_growth_1y", 0) > 0.20:
        scores["growth_score"] += 2
    elif metrics.get("revenue_growth_1y", 0) > 0.10:
        scores["growth_score"] += 1
    
    if metrics.get("eps_growth", 0) > 0.20:
        scores["growth_score"] += 2
    elif metrics.get("eps_growth", 0) > 0.10:
        scores["growth_score"] += 1
    
    if metrics.get("roic", 0) > 0.15:
        scores["growth_score"] += 1
    
    # Safety Score (0-5)
    if metrics.get("altman_z_score", 0) < 1.8:
        scores["safety_score"] -= 3
    elif metrics.get("altman_z_score", 0) < 3.0:
        scores["safety_score"] -= 1
    
    if metrics.get("current_ratio", 999) < 1.0:
        scores["safety_score"] -= 2
    elif metrics.get("current_ratio", 999) < 1.5:
        scores["safety_score"] -= 1
    
    if metrics.get("red_flag_count", 0) > 2:
        scores["safety_score"] -= 2
    elif metrics.get("red_flag_count", 0) > 0:
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

def main():
    """Main execution function."""
    
    print("🚀 High-Quality Company Analysis")
    print("=" * 60)
    
    # Step 1: Download and filter for data quality
    high_quality_companies = download_and_filter_companies(max_companies=30, min_quality_score=6)
    
    if not high_quality_companies:
        print("❌ No high-quality companies found")
        return
    
    # Step 2: Run comprehensive analysis
    analyzed_companies = analyze_high_quality_companies(high_quality_companies)
    
    if not analyzed_companies:
        print("❌ Analysis failed for all companies")
        return
    
    # Save results
    settings = load_settings()
    output_dir = settings.output_dir / "high_quality_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save analyzed companies
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    analysis_file = output_dir / f"high_quality_analysis_{timestamp}.jsonl"
    write_jsonl(analysis_file, analyzed_companies)
    
    # Create summary
    summary = {
        "analysis_timestamp": datetime.now().isoformat(),
        "total_companies_assessed": len(high_quality_companies),
        "successful_analyses": len(analyzed_companies),
        "average_quality_score": sum(c["quality_assessment"]["quality_score"] for c in analyzed_companies) / len(analyzed_companies),
        "average_metrics_count": sum(c["metrics_count"] for c in analyzed_companies) / len(analyzed_companies),
        "top_performers": [
            {
                "rank": i + 1,
                "symbol": c["symbol"],
                "name": c["name"],
                "overall_score": c["investment_scores"]["overall_score"],
                "category": c["investment_scores"]["investment_category"],
                "quality_score": c["quality_assessment"]["quality_score"],
                "metrics_count": c["metrics_count"]
            }
            for i, c in enumerate(analyzed_companies[:10])
        ]
    }
    
    summary_file = output_dir / f"analysis_summary_{timestamp}.json"
    write_json(summary_file, summary)
    
    # Display results
    print(f"\n🎉 High-Quality Analysis Complete!")
    print("=" * 60)
    print(f"📊 Companies Analyzed: {len(analyzed_companies)}")
    print(f"📈 Average Quality Score: {summary['average_quality_score']:.1f}/10")
    print(f"📊 Average Metrics: {summary['average_metrics_count']:.0f} per company")
    
    print(f"\n🏆 Top 10 Performers:")
    for performer in summary["top_performers"]:
        print(f"  {performer['rank']:2d}. {performer['symbol']} - Score: {performer['overall_score']}/20 ({performer['category']})")
        print(f"      Quality: {performer['quality_score']}/10, Metrics: {performer['metrics_count']}")
    
    print(f"\n📁 Results saved to: {output_dir}")
    print(f"📊 Analysis: {analysis_file}")
    print(f"📋 Summary: {summary_file}")

if __name__ == "__main__":
    main()
