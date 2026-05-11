#!/usr/bin/env python3

"""
Strategic Company Selection for Comprehensive Analysis
Selects top companies by market cap and prioritizes for analysis.
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_json, write_jsonl

def get_top_companies_by_criteria() -> List[Dict[str, Any]]:
    """Get strategic selection of top companies for analysis."""
    
    print("🎯 Selecting Strategic Companies for Comprehensive Analysis")
    print("=" * 60)
    
    # Priority 1: Major Tech Companies (High Growth, High Quality)
    tech_companies = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "ADBE", 
        "CRM", "INTC", "AMD", "NFLX", "PYPL", "CSCO", "ORCL"
    ]
    
    # Priority 2: Financial Giants (Stable, High Dividend)
    financial_companies = [
        "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SPGI", "V",
        "MA", "COF", "USB", "PNC", "TFC", "SCHW", "ICE", "CME", "AON", "MMC"
    ]
    
    # Priority 3: Healthcare Leaders (Defensive, Innovation)
    healthcare_companies = [
        "JNJ", "UNH", "PFE", "ABBV", "TMO", "ABT", "DHR", "BMY", "AMGN", 
        "GILD", "CVS", "CI", "UNP", "MDT", "ISRG", "SYK", "BSX", "ZTS", "HCA"
    ]
    
    # Priority 4: Consumer Staples (Recession-Resistant)
    consumer_companies = [
        "PG", "KO", "PEP", "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "LOW",
        "TGT", "KR", "CL", "KMB", "GIS", "HSY", "K", "SYY", "CAG", "CHD"
    ]
    
    # Priority 5: Energy & Industrial (Cyclical Value)
    energy_industrial = [
        "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "BKR", "PSX", "VLO", "MPC",
        "CAT", "DE", "GE", "MMM", "HON", "UPS", "RTX", "LMT", "BA", "NOC"
    ]
    
    # Priority 6: Telecom & Utilities (High Dividend)
    telecom_utilities = [
        "VZ", "T", "TMUS", "NEE", "DUK", "SO", "AEP", "EXC", "SRE", "XEL",
        "WEC", "ED", "D", "PEG", "AWK", "ETR", "ATO", "CNP", "CMS"
    ]
    
    # Priority 7: Real Estate & REITs
    reit_companies = [
        "AMT", "PLD", "CCI", "EQIX", "PSA", "DLR", "O", "PRO", "EXR", "VICI",
        "SPG", "CBRE", "Well", "AVB", "EQR", "ESS", "MAA", "UDR", "VTR"
    ]
    
    # Priority 8: Specialized & Growth
    specialized_growth = [
        "BRK.B", "UNH", "HD", "DIS", "NFLX", "TSLA", "AMZN", "META", "GOOGL", "MSFT",
        "AAPL", "NVDA", "CRM", "ADBE", "PYPL", "SQ", "SHOP", "ZM", "DOCU", "SNOW"
    ]
    
    # Combine all categories
    all_companies = []
    categories = [
        ("Tech Leaders", tech_companies),
        ("Financial Giants", financial_companies),
        ("Healthcare Leaders", healthcare_companies),
        ("Consumer Staples", consumer_companies),
        ("Energy & Industrial", energy_industrial),
        ("Telecom & Utilities", telecom_utilities),
        ("REITs", reit_companies),
        ("Specialized Growth", specialized_growth)
    ]
    
    for category_name, companies in categories:
        print(f"📊 {category_name}: {len(companies)} companies")
        for symbol in companies:
            all_companies.append({
                "symbol": symbol,
                "category": category_name,
                "priority": len(all_companies) + 1
            })
    
    # Remove duplicates while preserving order
    seen = set()
    unique_companies = []
    for company in all_companies:
        if company["symbol"] not in seen:
            seen.add(company["symbol"])
            unique_companies.append(company)
    
    print(f"\n🎯 Total Unique Companies: {len(unique_companies)}")
    
    # If we need more companies to reach 1000, add additional mid-cap companies
    if len(unique_companies) < 1000:
        additional_needed = 1000 - len(unique_companies)
        print(f"📈 Adding {additional_needed} additional companies...")
        
        # Additional mid-cap companies by sector
        additional_companies = [
            # Additional Tech
            "INTU", "MU", "TXN", "QCOM", "AVGO", "MRVL", "LRCX", "KLAC", "SNPS", "CDNS",
            "ANSS", "KEYS", "ZBRA", "PTC", "TYL", "VRSN", "FTNT", "CHKP", "PANW", "CRWD",
            # Additional Healthcare
            "REGN", "MRNA", "BIIB", "ILMN", "IDXX", "DGX", "LH", "CRL", "PKI", "BAX",
            "HOLX", "RMD", "BSX", "ALGN", "DXCM", "EW", "BDX", "WAT", "TECH", "INCY",
            # Additional Financial
            "BK", "STT", "TROW", "IVZ", "AMP", "EVR", "LAZ", "NTRS", "PFG", "AFL",
            "MET", "PRU", "LNC", "AIG", "TRV", "ALL", "HIG", "CB", "CINF", "WRB",
            # Additional Consumer
            "TJX", "ROST", "DLTR", "BIG", "FIVE", "COST", "WMT", "HD", "MCD", "YUM",
            "DRI", "CMG", "DPZ", "PZZA", "MNST", "KDP", "STZ", "BFB", "SAM", "TAP"
        ]
        
        for symbol in additional_companies:
            if symbol not in seen and len(unique_companies) < 1000:
                unique_companies.append({
                    "symbol": symbol,
                    "category": "Additional Growth",
                    "priority": len(unique_companies) + 1
                })
                seen.add(symbol)
    
    print(f"🎯 Final Selection: {len(unique_companies)} companies")
    
    return unique_companies[:1000]  # Ensure we don't exceed 1000

def create_company_analysis_plan(companies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create analysis plan for the selected companies."""
    
    # Group by category
    categories = {}
    for company in companies:
        category = company["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(company)
    
    # Create analysis plan
    plan = {
        "total_companies": len(companies),
        "categories": {},
        "analysis_phases": [
            {
                "phase": 1,
                "name": "Priority Leaders",
                "companies": sum([len(c) for c in list(categories.values())[:3]]),
                "description": "Tech, Financial, and Healthcare leaders"
            },
            {
                "phase": 2,
                "name": "Stable Companies", 
                "companies": sum([len(c) for c in list(categories.values())[3:5]]),
                "description": "Consumer staples and energy/industrial"
            },
            {
                "phase": 3,
                "name": "Income & Growth",
                "companies": sum([len(c) for c in list(categories.values())[5:]]),
                "description": "REITs, utilities, and specialized growth"
            }
        ]
    }
    
    for category_name, category_companies in categories.items():
        plan["categories"][category_name] = {
            "count": len(category_companies),
            "companies": [c["symbol"] for c in category_companies[:10]]  # Show first 10
        }
    
    return plan

def main():
    """Main execution function."""
    
    # Get strategic company selection
    companies = get_top_companies_by_criteria()
    
    # Create analysis plan
    plan = create_company_analysis_plan(companies)
    
    # Save selection and plan
    settings = load_settings()
    
    # Save company selection
    selection_file = settings.output_dir / "strategic_selection" / "top_1000_companies.jsonl"
    selection_file.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(selection_file, companies)
    
    # Save analysis plan
    plan_file = settings.output_dir / "strategic_selection" / "analysis_plan.json"
    write_json(plan_file, plan)
    
    # Display summary
    print(f"\n🎯 Strategic Company Selection Complete!")
    print(f"📊 Total Companies: {plan['total_companies']}")
    print(f"📁 Selection saved to: {selection_file}")
    print(f"📋 Analysis plan saved to: {plan_file}")
    
    print(f"\n📈 Analysis Phases:")
    for i, phase in enumerate(plan["analysis_phases"], 1):
        print(f"  Phase {i}: {phase['name']} ({phase['companies']} companies)")
        print(f"    {phase['description']}")
    
    print(f"\n🏆 Top 10 Companies by Priority:")
    for company in companies[:10]:
        print(f"  {company['priority']:2d}. {company['symbol']} ({company['category']})")
    
    return plan

if __name__ == "__main__":
    main()
