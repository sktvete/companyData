#!/usr/bin/env python3

"""
Demo Phase 1 Comprehensive Analysis
Shows the complete analysis pipeline with sample data for our top 50 strategic companies.
"""

import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_jsonl, write_json
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics

def create_sample_company_data(symbol: str, category: str) -> Dict[str, Any]:
    """Create realistic sample data for a company based on its category."""
    
    # Base parameters by category
    category_params = {
        "Tech Leaders": {
            "revenue_base": 50000000000,
            "growth_rate": 0.15,
            "margin_base": 0.20,
            "pe_base": 25,
            "debt_ratio": 0.2
        },
        "Financial Giants": {
            "revenue_base": 100000000000,
            "growth_rate": 0.05,
            "margin_base": 0.15,
            "pe_base": 12,
            "debt_ratio": 0.8
        },
        "Healthcare Leaders": {
            "revenue_base": 80000000000,
            "growth_rate": 0.08,
            "margin_base": 0.25,
            "pe_base": 18,
            "debt_ratio": 0.3
        },
        "Consumer Staples": {
            "revenue_base": 60000000000,
            "growth_rate": 0.03,
            "margin_base": 0.10,
            "pe_base": 20,
            "debt_ratio": 0.4
        },
        "Energy & Industrial": {
            "revenue_base": 120000000000,
            "growth_rate": 0.02,
            "margin_base": 0.08,
            "pe_base": 15,
            "debt_ratio": 0.6
        }
    }
    
    params = category_params.get(category, category_params["Tech Leaders"])
    
    # Add some randomization for realism
    import random
    random.seed(hash(symbol) % 1000)  # Consistent randomization per symbol
    
    revenue_multiplier = 0.5 + random.random() * 2.0  # 0.5x to 2.5x
    revenue = params["revenue_base"] * revenue_multiplier
    
    # Financial statements
    gross_profit = revenue * (params["margin_base"] + random.random() * 0.1)
    operating_income = revenue * (params["margin_base"] * 0.7 + random.random() * 0.05)
    net_income = operating_income * (0.7 + random.random() * 0.2)
    
    # Balance sheet
    total_assets = revenue * 1.5
    total_debt = total_assets * params["debt_ratio"]
    equity = total_assets - total_debt
    
    # Price data
    shares_outstanding = equity / 100  # Assume $100 book value per share
    pe_ratio = params["pe_base"] * (0.8 + random.random() * 0.4)
    price = net_income / shares_outstanding * pe_ratio
    market_cap = price * shares_outstanding
    
    return {
        "symbol": symbol,
        "category": category,
        "financials": {
            "income_statement": [
                {
                    "date": "2024-12-31",
                    "totalRevenue": revenue,
                    "grossProfit": gross_profit,
                    "operatingIncome": operating_income,
                    "ebit": operating_income * 0.95,
                    "ebitda": operating_income * 1.1,
                    "pretaxIncome": operating_income * 0.9,
                    "netIncome": net_income,
                    "epsBasic": net_income / shares_outstanding,
                    "epsDiluted": net_income / (shares_outstanding * 1.05),
                    "interestExpense": total_debt * 0.05,
                    "costOfRevenue": revenue - gross_profit
                },
                {
                    "date": "2023-12-31",
                    "totalRevenue": revenue / (1 + params["growth_rate"]),
                    "grossProfit": gross_profit / (1 + params["growth_rate"]),
                    "operatingIncome": operating_income / (1 + params["growth_rate"]),
                    "ebit": operating_income * 0.95 / (1 + params["growth_rate"]),
                    "ebitda": operating_income * 1.1 / (1 + params["growth_rate"]),
                    "pretaxIncome": operating_income * 0.9 / (1 + params["growth_rate"]),
                    "netIncome": net_income / (1 + params["growth_rate"]),
                    "epsBasic": (net_income / shares_outstanding) / (1 + params["growth_rate"]),
                    "epsDiluted": (net_income / (shares_outstanding * 1.05)) / (1 + params["growth_rate"]),
                    "interestExpense": total_debt * 0.05,
                    "costOfRevenue": (revenue - gross_profit) / (1 + params["growth_rate"])
                }
            ],
            "balance_sheet": [
                {
                    "date": "2024-12-31",
                    "cashAndCashEquivalents": total_assets * 0.1,
                    "totalCurrentAssets": total_assets * 0.3,
                    "inventory": total_assets * 0.05,
                    "netReceivables": total_assets * 0.15,
                    "totalAssets": total_assets,
                    "accountPayables": total_assets * 0.08,
                    "totalCurrentLiabilities": total_assets * 0.15,
                    "totalLiab": total_debt + total_assets * 0.15,
                    "shortTermDebt": total_debt * 0.3,
                    "longTermDebt": total_debt * 0.7,
                    "totalStockholderEquity": equity,
                    "retainedEarnings": equity * 0.7
                },
                {
                    "date": "2023-12-31",
                    "cashAndCashEquivalents": total_assets * 0.08,
                    "totalCurrentAssets": total_assets * 0.28,
                    "inventory": total_assets * 0.04,
                    "netReceivables": total_assets * 0.14,
                    "totalAssets": total_assets * 0.9,
                    "accountPayables": total_assets * 0.07,
                    "totalCurrentLiabilities": total_assets * 0.14,
                    "totalLiab": (total_debt * 0.9) + total_assets * 0.14,
                    "shortTermDebt": total_debt * 0.3,
                    "longTermDebt": total_debt * 0.6,
                    "totalStockholderEquity": equity * 0.9,
                    "retainedEarnings": equity * 0.65
                }
            ],
            "cash_flow": [
                {
                    "date": "2024-12-31",
                    "operatingCashFlow": net_income * 1.2,
                    "capitalExpenditure": -revenue * 0.05,
                    "freeCashFlow": net_income * 1.2 - revenue * 0.05
                },
                {
                    "date": "2023-12-31",
                    "operatingCashFlow": (net_income / (1 + params["growth_rate"])) * 1.2,
                    "capitalExpenditure": -(revenue / (1 + params["growth_rate"])) * 0.05,
                    "freeCashFlow": (net_income / (1 + params["growth_rate"])) * 1.2 - (revenue / (1 + params["growth_rate"])) * 0.05
                }
            ]
        },
        "prices": [
            {
                "date": "2024-12-31",
                "close": price,
                "market_cap": market_cap,
                "enterprise_value": market_cap * 1.2
            }
        ]
    }

def analyze_company(company_data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze a single company with comprehensive metrics."""
    
    symbol = company_data["symbol"]
    category = company_data["category"]
    
    # Calculate comprehensive metrics
    metrics = calculate_comprehensive_metrics(
        company_data["financials"], 
        company_data["prices"]
    )
    
    if "error" in metrics:
        return {"symbol": symbol, "error": metrics["error"]}
    
    # Create comprehensive analysis
    analysis = {
        "symbol": symbol,
        "category": category,
        "analysis_timestamp": datetime.now().isoformat(),
        "metrics_count": len([k for k, v in metrics.items() if isinstance(v, (int, float))]),
        "financial_metrics": metrics,
        
        # Company info
        "company_info": {
            "name": f"{symbol} Corporation",
            "sector": category.split()[0],
            "industry": category,
            "market_cap": metrics.get("market_cap", 0),
            "currency": "USD"
        },
        
        # Investment scores
        "investment_scores": {
            "value_score": min(5, max(0, 5 - metrics.get("pe_ratio", 50) / 10)),
            "quality_score": min(5, max(0, metrics.get("roe", 0) * 20)),
            "growth_score": min(5, max(0, metrics.get("revenue_growth_1y", 0) * 20)),
            "safety_score": min(5, max(0, metrics.get("altman_z_score", 0) / 2)),
            "overall_score": 0,
            "investment_category": "UNKNOWN"
        }
    }
    
    # Calculate overall score and category
    scores = analysis["investment_scores"]
    scores["overall_score"] = scores["value_score"] + scores["quality_score"] + scores["growth_score"] + scores["safety_score"]
    
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
    
    return analysis

def run_phase1_demo():
    """Run the complete Phase 1 analysis demonstration."""
    
    print("🚀 Phase 1 Comprehensive Analysis Demo")
    print("=" * 60)
    
    # Load strategic companies
    settings = load_settings()
    selection_file = settings.output_dir / "strategic_selection" / "top_1000_companies.jsonl"
    
    if not selection_file.exists():
        print("❌ Strategic company selection not found")
        return
    
    companies = read_jsonl(selection_file)
    phase1_companies = companies[:50]  # Top 50 for demo
    
    print(f"📊 Analyzing {len(phase1_companies)} companies...")
    
    # Analyze each company
    analyses = []
    for i, company in enumerate(phase1_companies):
        print(f"🔍 [{i+1:2d}/50] {company['symbol']} ({company['category']})")
        
        # Create sample data
        company_data = create_sample_company_data(company["symbol"], company["category"])
        
        # Analyze company
        analysis = analyze_company(company_data)
        analyses.append(analysis)
        
        # Show key results
        metrics = analysis["financial_metrics"]
        scores = analysis["investment_scores"]
        
        print(f"    Revenue: ${metrics['revenue']/1e9:.1f}B")
        print(f"    ROE: {metrics['roe']*100:.1f}%, P/E: {metrics['pe_ratio']:.1f}")
        print(f"    Overall Score: {scores['overall_score']}/20 ({scores['investment_category']})")
        print()
    
    # Sort by overall score
    analyses.sort(key=lambda x: x["investment_scores"]["overall_score"], reverse=True)
    
    # Create summary
    summary = {
        "analysis_id": "phase1_demo_50_companies",
        "timestamp": datetime.now().isoformat(),
        "total_companies": len(analyses),
        "categories": {},
        "top_performers": [],
        "investment_distribution": {},
        "key_insights": []
    }
    
    # Category analysis
    categories = {}
    for analysis in analyses:
        category = analysis["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(analysis)
    
    for category, category_analyses in categories.items():
        avg_score = sum(a["investment_scores"]["overall_score"] for a in category_analyses) / len(category_analyses)
        summary["categories"][category] = {
            "count": len(category_analyses),
            "avg_score": round(avg_score, 1),
            "top_performer": category_analyses[0]["symbol"]
        }
    
    # Top 10 performers
    summary["top_performers"] = [
        {
            "rank": i + 1,
            "symbol": a["symbol"],
            "category": a["category"],
            "overall_score": a["investment_scores"]["overall_score"],
            "category": a["investment_scores"]["investment_category"],
            "roe": a["financial_metrics"]["roe"],
            "pe_ratio": a["financial_metrics"]["pe_ratio"]
        }
        for i, a in enumerate(analyses[:10])
    ]
    
    # Investment distribution
    categories = {}
    for analysis in analyses:
        category = analysis["investment_scores"]["investment_category"]
        categories[category] = categories.get(category, 0) + 1
    
    summary["investment_distribution"] = categories
    
    # Key insights
    excellent_companies = [a for a in analyses if a["investment_scores"]["investment_category"] == "EXCELLENT"]
    risky_companies = [a for a in analyses if a["investment_scores"]["investment_category"] == "RISKY"]
    
    summary["key_insights"] = [
        f"Excellent companies: {len(excellent_companies)} ({len(excellent_companies)/len(analyses)*100:.1f}%)",
        f"Risky companies: {len(risky_companies)} ({len(risky_companies)/len(analyses)*100:.1f}%)",
        f"Top performer: {analyses[0]['symbol']} with score {analyses[0]['investment_scores']['overall_score']}/20",
        f"Average metrics per company: {sum(a['metrics_count'] for a in analyses)/len(analyses):.0f}"
    ]
    
    # Save results
    output_dir = settings.output_dir / "comprehensive_analysis" / "phase1_demo"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save detailed analyses
    analyses_file = output_dir / "detailed_analyses.jsonl"
    write_jsonl(analyses_file, analyses)
    
    # Save summary
    summary_file = output_dir / "analysis_summary.json"
    write_json(summary_file, summary)
    
    # Display results
    print("🎉 Phase 1 Analysis Complete!")
    print("=" * 60)
    print(f"📊 Total Companies Analyzed: {summary['total_companies']}")
    print(f"📈 Average Metrics per Company: {summary['key_insights'][3].split(': ')[1]}")
    print()
    
    print("🏆 Top 10 Performers:")
    for performer in summary["top_performers"]:
        print(f"  {performer['rank']:2d}. {performer['symbol']} ({performer['category']}) - Score: {performer['overall_score']}/20")
    
    print()
    print("📊 Investment Distribution:")
    for category, count in summary["investment_distribution"].items():
        percentage = count / summary["total_companies"] * 100
        print(f"  {category}: {count} companies ({percentage:.1f}%)")
    
    print()
    print("💡 Key Insights:")
    for insight in summary["key_insights"]:
        print(f"  • {insight}")
    
    print()
    print(f"📁 Results saved to: {output_dir}")
    print(f"📋 Detailed analyses: {analyses_file}")
    print(f"📊 Summary report: {summary_file}")
    
    return summary

if __name__ == "__main__":
    run_phase1_demo()
