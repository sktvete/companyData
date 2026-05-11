#!/usr/bin/env python3

"""
Demo Comprehensive Analysis - Shows Phase 1 Implementation
Demonstrates the full comprehensive analysis system with sample data.
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics
from equity_sorter.io_utils import write_jsonl

def create_sample_financial_data():
    """Create sample financial data for demonstration."""
    
    return {
        'income_statement': [
            {
                'date': '2024-12-31',
                'totalRevenue': 50000000000,
                'grossProfit': 20000000000,
                'operatingIncome': 8000000000,
                'ebit': 7500000000,
                'ebitda': 8500000000,
                'pretaxIncome': 7000000000,
                'netIncome': 5500000000,
                'epsBasic': 3.25,
                'epsDiluted': 3.20,
                'interestExpense': 500000000,
                'costOfRevenue': 30000000000
            },
            {
                'date': '2023-12-31',
                'totalRevenue': 45000000000,
                'grossProfit': 18000000000,
                'operatingIncome': 7200000000,
                'ebit': 6800000000,
                'ebitda': 7700000000,
                'pretaxIncome': 6300000000,
                'netIncome': 4900000000,
                'epsBasic': 2.90,
                'epsDiluted': 2.85,
                'interestExpense': 450000000,
                'costOfRevenue': 27000000000
            }
        ],
        'balance_sheet': [
            {
                'date': '2024-12-31',
                'cashAndCashEquivalents': 8000000000,
                'totalCurrentAssets': 25000000000,
                'inventory': 3000000000,
                'netReceivables': 5000000000,
                'totalAssets': 80000000000,
                'accountPayables': 4000000000,
                'totalCurrentLiabilities': 12000000000,
                'totalLiab': 30000000000,
                'shortTermDebt': 2000000000,
                'longTermDebt': 10000000000,
                'totalStockholderEquity': 50000000000,
                'retainedEarnings': 30000000000
            },
            {
                'date': '2023-12-31',
                'cashAndCashEquivalents': 7000000000,
                'totalCurrentAssets': 23000000000,
                'inventory': 2800000000,
                'netReceivables': 4500000000,
                'totalAssets': 75000000000,
                'accountPayables': 3800000000,
                'totalCurrentLiabilities': 11000000000,
                'totalLiab': 28000000000,
                'shortTermDebt': 1800000000,
                'longTermDebt': 9000000000,
                'totalStockholderEquity': 47000000000,
                'retainedEarnings': 28000000000
            }
        ],
        'cash_flow': [
            {
                'date': '2024-12-31',
                'operatingCashFlow': 6500000000,
                'capitalExpenditure': -1500000000,
                'freeCashFlow': 5000000000
            },
            {
                'date': '2023-12-31',
                'operatingCashFlow': 5800000000,
                'capitalExpenditure': -1200000000,
                'freeCashFlow': 4600000000
            }
        ]
    }

def create_sample_price_data():
    """Create sample price data for demonstration."""
    
    prices = []
    base_price = 150.0
    
    # Generate 252 trading days of price data
    for i in range(252):
        price = base_price + (i * 0.5) + (i % 10 * 2)  # Upward trend with volatility
        prices.append({
            'date': f'2024-{(i//21)+1:02d}-{(i%21)+1:02d}',
            'close': price,
            'market_cap': price * 1000000000,  # Assume 1B shares
            'enterprise_value': price * 1200000000  # EV > Market Cap
        })
    
    return prices

def demo_comprehensive_analysis():
    """Demonstrate comprehensive analysis with sample data."""
    
    print("🚀 Demo: Comprehensive Analysis System")
    print("=" * 60)
    
    # Create sample data
    print("📊 Creating sample financial data...")
    financial_data = create_sample_financial_data()
    price_data = create_sample_price_data()
    
    # Calculate comprehensive metrics
    print("🔍 Calculating comprehensive metrics...")
    metrics = calculate_comprehensive_metrics(financial_data, price_data)
    
    if "error" in metrics:
        print(f"❌ Error: {metrics['error']}")
        return
    
    # Display key results
    print("\n✅ Comprehensive Analysis Results:")
    print(f"📈 Total Metrics Calculated: {len([k for k, v in metrics.items() if isinstance(v, (int, float))])}")
    
    print(f"\n💰 Key Financial Metrics:")
    print(f"  Revenue: ${metrics['revenue']/1e9:.1f}B")
    print(f"  Net Income: ${metrics['net_income']/1e9:.1f}B")
    print(f"  Free Cash Flow: ${metrics['free_cash_flow']/1e9:.1f}B")
    
    print(f"\n📊 Profitability Ratios:")
    print(f"  Gross Margin: {metrics['gross_margin']*100:.1f}%")
    print(f"  Operating Margin: {metrics['operating_margin']*100:.1f}%")
    print(f"  Net Margin: {metrics['net_margin']*100:.1f}%")
    print(f"  ROE: {metrics['roe']*100:.1f}%")
    print(f"  ROIC: {metrics['roic']*100:.1f}%")
    
    print(f"\n🏦 Financial Health:")
    print(f"  Debt/Equity: {metrics['debt_to_equity']:.2f}")
    print(f"  Current Ratio: {metrics['current_ratio']:.2f}")
    print(f"  Interest Coverage: {metrics['interest_coverage']:.1f}x")
    print(f"  Altman Z-Score: {metrics['altman_z_score']:.2f}")
    
    print(f"\n📈 Growth Rates:")
    print(f"  Revenue Growth: {metrics['revenue_growth_1y']*100:.1f}%")
    print(f"  EPS Growth: {metrics['eps_growth']*100:.1f}%")
    print(f"  Net Income Growth: {metrics['net_income_growth']*100:.1f}%")
    
    print(f"\n💎 Valuation Metrics:")
    print(f"  P/E Ratio: {metrics['pe_ratio']:.1f}")
    print(f"  P/S Ratio: {metrics['ps_ratio']:.1f}")
    print(f"  EV/EBITDA: {metrics['ev_ebitda']:.1f}")
    fcf_yield = metrics.get('fcf_yield', 0)
    if fcf_yield > 0:
        print(f"  FCF Yield: {fcf_yield*100:.1f}%")
    else:
        print(f"  FCF Yield: N/A")
    
    print(f"\n🎯 Investment Scores:")
    print(f"  GARP Score: {metrics['garp_score']}/6")
    print(f"  Quality Score: {metrics['quality_score']}/4")
    print(f"  Overall Score: {metrics['overall_score']}/10")
    print(f"  Piotroski Score: {metrics['piotroski_score']}/9")
    
    if metrics['red_flags']:
        print(f"\n⚠️  Red Flags ({len(metrics['red_flags'])}):")
        for flag in metrics['red_flags']:
            print(f"  • {flag}")
    else:
        print(f"\n✅ No Red Flags Detected")
    
    print(f"\n📈 Momentum Indicators:")
    print(f"  12-Month Momentum: {metrics['momentum_12m']*100:.1f}%")
    print(f"  Distance from 52W High: {metrics['distance_from_52w_high']*100:.1f}%")
    print(f"  Distance from 52W Low: {metrics['distance_from_52w_low']*100:.1f}%")
    
    # Create demo analysis result
    demo_analysis = {
        "symbol": "DEMO",
        "exchange": "US",
        "analysis_timestamp": datetime.now().isoformat(),
        "data_sources": ["fundamentals", "prices"],
        "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))]),
        "financial_metrics": metrics,
        "company_info": {
            "name": "Demo Corporation",
            "sector": "Technology",
            "industry": "Software",
            "description": "A demonstration company for comprehensive analysis",
            "market_cap": metrics.get('market_cap', 0),
            "country": "United States",
            "currency": "USD"
        },
        "investment_scores": {
            "value_score": 3 if metrics.get('pe_ratio', 0) < 20 else 1,
            "quality_score": 4 if metrics.get('roe', 0) > 0.15 else 2,
            "growth_score": 3 if metrics.get('revenue_growth_1y', 0) > 0.10 else 1,
            "safety_score": 4 if metrics.get('altman_z_score', 0) > 3 else 2,
            "overall_score": metrics.get('overall_score', 0),
            "investment_category": "GOOD" if metrics.get('overall_score', 0) >= 12 else "FAIR"
        }
    }
    
    # Save demo results
    from equity_sorter.config import load_settings
    settings = load_settings()
    
    output_dir = settings.output_dir / "demo_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "demo_comprehensive_analysis.jsonl"
    write_jsonl(output_file, [demo_analysis])
    
    print(f"\n🎉 Demo Analysis Completed!")
    print(f"📁 Results saved to: {output_file}")
    print(f"📊 Total Metrics: {demo_analysis['metrics_count']}")
    print(f"🏆 Investment Category: {demo_analysis['investment_scores']['investment_category']}")
    print(f"⭐ Overall Score: {demo_analysis['investment_scores']['overall_score']}/10")
    
    return demo_analysis

if __name__ == "__main__":
    demo_comprehensive_analysis()
