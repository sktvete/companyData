#!/usr/bin/env python3

"""
Comprehensive Analysis Pipeline - Phase 1 Implementation
Processes all available EODHD data and generates comprehensive financial metrics.
"""

import sys
import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_json, read_jsonl, write_jsonl
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics

def load_company_data(settings, symbol: str, exchange: str = "US") -> Dict[str, Any]:
    """Load all available data for a single company."""
    
    bronze_date = date.today().isoformat()
    company_dir = (settings.data_dir / "bronze" / f"provider={settings.provider_name}" 
                  / "dataset=company_data" / f"exchange={exchange}" / f"symbol={symbol}" / f"date={bronze_date}")
    
    company_data = {
        "symbol": symbol,
        "exchange": exchange,
        "data_available": []
    }
    
    # Load fundamentals
    fundamentals_file = company_dir / "fundamentals.json"
    if fundamentals_file.exists():
        fundamentals_data = read_json(fundamentals_file)
        if fundamentals_data and "payload" in fundamentals_data:
            company_data["fundamentals"] = fundamentals_data["payload"]
            company_data["data_available"].append("fundamentals")
    
    # Load prices
    prices_file = company_dir / "prices.json"
    if prices_file.exists():
        prices_data = read_json(prices_file)
        if prices_data and "payload" in prices_data:
            company_data["prices"] = prices_data["payload"]
            company_data["data_available"].append("prices")
    
    # Load news
    news_file = company_dir / "news.json"
    if news_file.exists():
        news_data = read_json(news_file)
        if news_data and "payload" in news_data:
            company_data["news"] = news_data["payload"]
            company_data["data_available"].append("news")
    
    # Load sentiments
    sentiments_file = company_dir / "sentiments.json"
    if sentiments_file.exists():
        sentiments_data = read_json(sentiments_file)
        if sentiments_data and "payload" in sentiments_data:
            company_data["sentiments"] = sentiments_data["payload"]
            company_data["data_available"].append("sentiments")
    
    return company_data

def extract_financial_statements(fundamentals_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract financial statements from EODHD fundamentals data."""
    
    financials = {
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": []
    }
    
    # Extract quarterly data
    quarterly = fundamentals_data.get("quarterly_financials", {})
    if isinstance(quarterly, dict):
        financials["income_statement"].extend(quarterly.get("income_statement", []))
        financials["balance_sheet"].extend(quarterly.get("balance_sheet", []))
        financials["cash_flow"].extend(quarterly.get("cash_flow", []))
    
    # Extract annual data
    annual = fundamentals_data.get("annual_financials", {})
    if isinstance(annual, dict):
        financials["income_statement"].extend(annual.get("income_statement", []))
        financials["balance_sheet"].extend(annual.get("balance_sheet", []))
        financials["cash_flow"].extend(annual.get("cash_flow", []))
    
    return financials

def process_company_analysis(company_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process comprehensive analysis for a single company."""
    
    symbol = company_data["symbol"]
    analysis = {
        "symbol": symbol,
        "exchange": company_data["exchange"],
        "analysis_timestamp": datetime.now().isoformat(),
        "data_sources": company_data["data_available"]
    }
    
    # Calculate comprehensive financial metrics
    if "fundamentals" in company_data:
        financials = extract_financial_statements(company_data["fundamentals"])
        price_data = company_data.get("prices", [])
        
        metrics = calculate_comprehensive_metrics(financials, price_data)
        
        if "error" not in metrics:
            analysis["financial_metrics"] = metrics
            analysis["metrics_count"] = len([k for k, v in metrics.items() if isinstance(v, (int, float))])
        else:
            analysis["financial_metrics_error"] = metrics["error"]
    
    # Extract company information
    if "fundamentals" in company_data:
        general = company_data["fundamentals"].get("general", {})
        highlights = company_data["fundamentals"].get("highlights", {})
        
        analysis["company_info"] = {
            "name": general.get("Name", general.get("CompanyName", symbol)),
            "sector": general.get("Sector", "Unknown"),
            "industry": general.get("Industry", "Unknown"),
            "description": general.get("Description", ""),
            "market_cap": highlights.get("MarketCapitalization"),
            "employee_count": general.get("FullTimeEmployees"),
            "founded": general.get("FiscalYearEnd"),
            "country": general.get("Country", "Unknown"),
            "currency": general.get("Currency", "USD")
        }
    
    # Process news sentiment
    if "sentiments" in company_data:
        sentiments = company_data["sentiments"]
        symbol_key = f"{symbol}.{company_data['exchange']}"
        
        if symbol_key in sentiments and isinstance(sentiments[symbol_key], list):
            sentiment_data = sentiments[symbol_key]
            
            if sentiment_data:
                # Calculate sentiment summary
                total_sentiment = sum(point.get("sentiment_score", 0) for point in sentiment_data)
                avg_sentiment = total_sentiment / len(sentiment_data)
                
                positive_days = sum(1 for point in sentiment_data if point.get("sentiment_score", 0) > 0.1)
                negative_days = sum(1 for point in sentiment_data if point.get("sentiment_score", 0) < -0.1)
                
                analysis["sentiment_analysis"] = {
                    "average_sentiment": round(avg_sentiment, 4),
                    "total_mentions": sum(point.get("mention_count", 0) for point in sentiment_data),
                    "positive_days": positive_days,
                    "negative_days": negative_days,
                    "neutral_days": len(sentiment_data) - positive_days - negative_days,
                    "data_points": len(sentiment_data)
                }
    
    # Process news articles
    if "news" in company_data:
        news_articles = company_data["news"]
        if isinstance(news_articles, list):
            analysis["news_summary"] = {
                "total_articles": len(news_articles),
                "recent_articles": len([a for a in news_articles if a.get("published_date")]),
                "sources": list(set(a.get("source", "Unknown") for a in news_articles if a.get("source")))
            }
    
    # Calculate overall investment score
    if "financial_metrics" in analysis:
        metrics = analysis["financial_metrics"]
        
        # Investment categories
        investment_scores = {}
        
        # Value Score (0-5)
        value_score = 0
        if metrics.get("pe_ratio", 999) < 15:
            value_score += 2
        elif metrics.get("pe_ratio", 999) < 25:
            value_score += 1
        
        if metrics.get("pb_ratio", 999) < 2:
            value_score += 2
        elif metrics.get("pb_ratio", 999) < 4:
            value_score += 1
        
        if metrics.get("ps_ratio", 999) < 3:
            value_score += 1
        
        investment_scores["value_score"] = value_score
        
        # Quality Score (0-5)
        quality_score = 0
        if metrics.get("roe", 0) > 0.20:
            quality_score += 2
        elif metrics.get("roe", 0) > 0.15:
            quality_score += 1
        
        if metrics.get("debt_to_equity", 999) < 0.5:
            quality_score += 2
        elif metrics.get("debt_to_equity", 999) < 1.0:
            quality_score += 1
        
        if metrics.get("piotroski_score", 0) >= 7:
            quality_score += 1
        
        investment_scores["quality_score"] = quality_score
        
        # Growth Score (0-5)
        growth_score = 0
        if metrics.get("revenue_growth_1y", 0) > 0.20:
            growth_score += 2
        elif metrics.get("revenue_growth_1y", 0) > 0.10:
            growth_score += 1
        
        if metrics.get("eps_growth", 0) > 0.20:
            growth_score += 2
        elif metrics.get("eps_growth", 0) > 0.10:
            growth_score += 1
        
        if metrics.get("roic", 0) > 0.15:
            growth_score += 1
        
        investment_scores["growth_score"] = growth_score
        
        # Safety Score (0-5)
        safety_score = 5
        if metrics.get("altman_z_score", 0) < 1.8:
            safety_score -= 3
        elif metrics.get("altman_z_score", 0) < 3.0:
            safety_score -= 1
        
        if metrics.get("current_ratio", 999) < 1.0:
            safety_score -= 2
        elif metrics.get("current_ratio", 999) < 1.5:
            safety_score -= 1
        
        if metrics.get("red_flag_count", 0) > 2:
            safety_score -= 2
        elif metrics.get("red_flag_count", 0) > 0:
            safety_score -= 1
        
        investment_scores["safety_score"] = max(0, safety_score)
        
        # Overall Score
        investment_scores["overall_score"] = sum(investment_scores.values())
        
        # Investment Category
        overall = investment_scores["overall_score"]
        if overall >= 16:
            category = "EXCELLENT"
        elif overall >= 12:
            category = "GOOD"
        elif overall >= 8:
            category = "FAIR"
        elif overall >= 4:
            category = "POOR"
        else:
            category = "RISKY"
        
        investment_scores["investment_category"] = category
        
        analysis["investment_scores"] = investment_scores
    
    return analysis

def run_comprehensive_analysis(settings, max_companies: int = None) -> Dict[str, Any]:
    """Run comprehensive analysis on all available companies."""
    
    print("🚀 Starting Comprehensive Analysis Pipeline")
    print("=" * 60)
    
    # Get list of available companies
    companies = []
    bronze_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=company_data"
    
    if bronze_dir.exists():
        for exchange_dir in bronze_dir.iterdir():
            if exchange_dir.is_dir() and exchange_dir.name.startswith("exchange="):
                exchange = exchange_dir.name.split("=")[1]
                for symbol_dir in exchange_dir.iterdir():
                    if symbol_dir.is_dir() and symbol_dir.name.startswith("symbol="):
                        symbol = symbol_dir.name.split("=")[1]
                        companies.append({"symbol": symbol, "exchange": exchange})
    
    if not companies:
        print("❌ No company data found. Run comprehensive download first.")
        return {"error": "No company data available"}
    
    # Apply limit if specified
    if max_companies:
        companies = companies[:max_companies]
        print(f"📊 Analyzing {len(companies)} companies (limited)")
    else:
        print(f"📊 Analyzing all {len(companies)} available companies")
    
    # Process each company
    analyses = []
    success_count = 0
    error_count = 0
    
    for i, company in enumerate(companies):
        try:
            print(f"🔍 [{i+1}/{len(companies)}] Analyzing {company['symbol']}...")
            
            # Load company data
            company_data = load_company_data(settings, company["symbol"], company["exchange"])
            
            if not company_data["data_available"]:
                print(f"  ⚠️  No data available for {company['symbol']}")
                error_count += 1
                continue
            
            # Process analysis
            analysis = process_company_analysis(company_data)
            analyses.append(analysis)
            success_count += 1
            
            print(f"  ✅ Analysis complete: {analysis.get('metrics_count', 0)} metrics calculated")
            
        except Exception as e:
            print(f"  ❌ Error analyzing {company['symbol']}: {e}")
            error_count += 1
            continue
    
    # Sort by overall score
    analyses.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)
    
    # Save results
    output_dir = settings.output_dir / "comprehensive_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"comprehensive_analysis_{timestamp}.jsonl"
    
    write_jsonl(output_file, analyses)
    
    # Generate summary
    summary = {
        "analysis_timestamp": datetime.now().isoformat(),
        "total_companies": len(companies),
        "successful_analyses": success_count,
        "errors": error_count,
        "output_file": str(output_file),
        "top_companies": [
            {
                "symbol": a["symbol"],
                "name": a.get("company_info", {}).get("name", a["symbol"]),
                "overall_score": a.get("investment_scores", {}).get("overall_score", 0),
                "category": a.get("investment_scores", {}).get("investment_category", "UNKNOWN"),
                "metrics_count": a.get("metrics_count", 0)
            }
            for a in analyses[:10]  # Top 10 companies
        ]
    }
    
    print(f"\n🎉 Comprehensive Analysis Completed!")
    print(f"✅ Successfully analyzed: {success_count} companies")
    print(f"❌ Errors: {error_count} companies")
    print(f"📁 Results saved to: {output_file}")
    print(f"🏆 Top company: {summary['top_companies'][0]['symbol']} ({summary['top_companies'][0]['category']})")
    
    # Save summary
    summary_file = output_dir / f"analysis_summary_{timestamp}.json"
    from equity_sorter.io_utils import write_json
    write_json(summary_file, summary)
    
    return summary

def main():
    parser = argparse.ArgumentParser(description="Run comprehensive analysis on EODHD data")
    parser.add_argument("--max-companies", type=int, help="Maximum number of companies to analyze")
    
    args = parser.parse_args()
    
    settings = load_settings()
    
    try:
        result = run_comprehensive_analysis(settings, args.max_companies)
        print(f"\n📊 Analysis Summary: {result}")
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
