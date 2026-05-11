#!/usr/bin/env python3

"""
Full Scale Analysis - Process All Available Companies
Analyzes all available companies to reach the 1500 company target.
"""

import sys
from pathlib import Path
from datetime import datetime
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_json, read_jsonl, write_json, write_jsonl
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics

def get_all_available_companies():
    """Get all available companies from the data directory."""
    
    settings = load_settings()
    prices_dir = settings.data_dir / "bronze/provider=eodhd/dataset=prices_daily/exchange=US"
    fundamentals_dir = settings.data_dir / "bronze/provider=eodhd/dataset=fundamentals/exchange=US"
    
    print(f"🔍 Scanning for available companies...")
    print(f"📁 Prices directory: {prices_dir}")
    print(f"📁 Fundamentals directory: {fundamentals_dir}")
    
    # Get all unique symbols from price data
    price_symbols = set()
    if prices_dir.exists():
        for date_dir in prices_dir.iterdir():
            if date_dir.is_dir():
                for file in date_dir.glob("*.json"):
                    symbol = file.stem
                    price_symbols.add(symbol)
    
    # Get all unique symbols from fundamentals data (stored by date)
    fundamental_symbols = set()
    if fundamentals_dir.exists():
        for date_dir in fundamentals_dir.iterdir():
            if date_dir.is_dir():
                for file in date_dir.glob("*.json"):
                    symbol = file.stem
                    fundamental_symbols.add(symbol)
    
    # Find intersection (companies with both price and fundamental data)
    available_symbols = price_symbols.intersection(fundamental_symbols)
    
    print(f"📊 Found {len(price_symbols)} companies with price data")
    print(f"📊 Found {len(fundamental_symbols)} companies with fundamental data")
    print(f"✅ {len(available_symbols)} companies have both price and fundamental data")
    
    return sorted(list(available_symbols))

def load_company_data(symbol):
    """Load price and fundamental data for a company."""
    
    settings = load_settings()
    
    # Load price data
    prices_dir = settings.data_dir / "bronze/provider=eodhd/dataset=prices_daily/exchange=US"
    price_files = list(prices_dir.glob(f"*/{symbol}.json"))
    
    if not price_files:
        return None
    
    latest_price_file = max(price_files, key=lambda x: x.stat().st_mtime)
    price_data = read_json(latest_price_file)
    
    # Load fundamental data (stored by date)
    fundamentals_dir = settings.data_dir / "bronze/provider=eodhd/dataset=fundamentals/exchange=US"
    fundamental_files = list(fundamentals_dir.glob(f"*/{symbol}.json"))
    
    if not fundamental_files:
        return None
    
    latest_fundamental_file = max(fundamental_files, key=lambda x: x.stat().st_mtime)
    fundamental_data = read_json(latest_fundamental_file)
    
    return {
        "symbol": symbol,
        "price_data": price_data,
        "fundamental_data": fundamental_data
    }

def analyze_company(company_data):
    """Analyze a single company and calculate all metrics."""
    
    try:
        symbol = company_data["symbol"]
        price_data = company_data["price_data"]
        fundamental_data = company_data["fundamental_data"]
        
        # Extract basic company info
        company_info = {
            "symbol": symbol,
            "name": fundamental_data.get("General", {}).get("Name", symbol),
            "sector": fundamental_data.get("General", {}).get("Sector", "Unknown"),
            "industry": fundamental_data.get("General", {}).get("Industry", "Unknown"),
            "market_cap": fundamental_data.get("Highlights", {}).get("MarketCapitalization", 0),
            "exchange": "US"
        }
        
        # Calculate comprehensive metrics
        metrics = calculate_comprehensive_metrics(fundamental_data, price_data)
        
        # Calculate factor scores
        # Note: This is a simplified version - in production you'd need proper securities data
        factor_scores = {
            "quality_score": metrics.get("piotroski_score", 0) / 9.0 * 5,  # Normalize to 0-5
            "value_score": min(5, max(0, 5 - metrics.get("pe_ratio", 20) / 4)),  # Simple PE-based value score
            "growth_score": min(5, max(0, metrics.get("revenue_growth_1y", 0) * 50)),  # Growth score
            "safety_score": min(5, max(0, 5 - metrics.get("debt_to_equity", 1))),  # Safety score
            "momentum_score": 2.5  # Neutral momentum score
        }
        
        # Calculate overall score
        overall_score = sum(factor_scores.values())
        
        # Determine investment category
        if overall_score >= 15:
            category = "EXCELLENT"
        elif overall_score >= 12:
            category = "GOOD"
        elif overall_score >= 9:
            category = "FAIR"
        elif overall_score >= 6:
            category = "POOR"
        else:
            category = "RISKY"
        
        # Data quality assessment
        data_quality = {
            "price_data_points": len(price_data) if isinstance(price_data, list) else 0,
            "fundamental_data_points": len(fundamental_data.get("Financials", {}).get("Income_Statement", {})),
            "quality": "excellent" if len(fundamental_data.get("Financials", {}).get("Income_Statement", {})) >= 8 else "good"
        }
        
        return {
            "symbol": symbol,
            "name": company_info["name"],
            "sector": company_info["sector"],
            "company_info": company_info,
            "financial_metrics": metrics,
            "investment_scores": {
                "overall_score": overall_score,
                "category": category,
                **factor_scores
            },
            "data_quality": data_quality,
            "analysis_timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"❌ Error analyzing {company_data['symbol']}: {e}")
        return None

def run_full_scale_analysis():
    """Run analysis on all available companies."""
    
    print("🚀 FULL SCALE ANALYSIS - ALL AVAILABLE COMPANIES")
    print("=" * 60)
    
    # Get all available companies
    symbols = get_all_available_companies()
    
    if not symbols:
        print("❌ No companies found for analysis")
        return
    
    print(f"\n📊 Starting analysis of {len(symbols)} companies...")
    
    results = []
    successful = 0
    failed = 0
    
    for i, symbol in enumerate(symbols, 1):
        print(f"🔍 [{i}/{len(symbols)}] Analyzing {symbol}...")
        
        # Load company data
        company_data = load_company_data(symbol)
        if not company_data:
            print(f"❌ No data found for {symbol}")
            failed += 1
            continue
        
        # Analyze company
        analysis_result = analyze_company(company_data)
        if analysis_result:
            results.append(analysis_result)
            successful += 1
            print(f"✅ {symbol}: {analysis_result['investment_scores']['overall_score']:.1f}/20 ({analysis_result['investment_scores']['category']})")
        else:
            print(f"❌ Analysis failed for {symbol}")
            failed += 1
        
        # Progress indicator
        if i % 10 == 0:
            print(f"📈 Progress: {i}/{len(symbols)} ({i/len(symbols)*100:.1f}%)")
    
    print(f"\n🎯 ANALYSIS COMPLETE!")
    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")
    print(f"📊 Success rate: {successful/len(symbols)*100:.1f}%")
    
    if results:
        # Sort by overall score
        results.sort(key=lambda x: x["investment_scores"]["overall_score"], reverse=True)
        
        # Save results
        settings = load_settings()
        output_dir = settings.output_dir / "full_scale_analysis"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save detailed results
        results_file = output_dir / f"full_scale_analysis_{timestamp}.jsonl"
        write_jsonl(results_file, results)
        
        # Save summary
        summary = {
            "timestamp": timestamp,
            "total_companies": len(symbols),
            "successful_analyses": successful,
            "failed_analyses": failed,
            "success_rate": successful/len(symbols)*100,
            "top_companies": results[:10],
            "category_breakdown": {}
        }
        
        # Calculate category breakdown
        for result in results:
            category = result["investment_scores"]["category"]
            summary["category_breakdown"][category] = summary["category_breakdown"].get(category, 0) + 1
        
        summary_file = output_dir / f"full_scale_summary_{timestamp}.json"
        write_json(summary_file, summary)
        
        print(f"\n💾 Results saved:")
        print(f"📋 Detailed: {results_file}")
        print(f"📊 Summary: {summary_file}")
        
        # Show top results
        print(f"\n🏆 TOP 10 COMPANIES:")
        for i, company in enumerate(results[:10], 1):
            print(f"{i:2d}. {company['symbol']:6s} ({company['name'][:20]:20s}) - Score: {company['investment_scores']['overall_score']:4.1f}/20 ({company['investment_scores']['category']})")
        
        return output_dir, timestamp
    
    return None, None

if __name__ == "__main__":
    run_full_scale_analysis()
