#!/usr/bin/env python3

"""
Initiate Comprehensive Analysis for Strategic Companies
Starts the analysis pipeline with our selected top companies.
"""

import sys
from pathlib import Path
from typing import List, Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_json

def load_strategic_companies() -> List[Dict[str, Any]]:
    """Load the strategic company selection."""
    
    settings = load_settings()
    selection_file = settings.output_dir / "strategic_selection" / "top_1000_companies.jsonl"
    
    if not selection_file.exists():
        print("❌ Strategic company selection not found. Run strategic_company_selection.py first.")
        return []
    
    companies = read_jsonl(selection_file)
    print(f"📊 Loaded {len(companies)} strategic companies")
    
    return companies

def create_analysis_batches(companies: List[Dict[str, Any]], batch_size: int = 50) -> List[List[Dict[str, Any]]]:
    """Create analysis batches for processing."""
    
    batches = []
    for i in range(0, len(companies), batch_size):
        batch = companies[i:i + batch_size]
        batches.append(batch)
    
    return batches

def initiate_analysis_phase_1(companies: List[Dict[str, Any]], max_companies: int = 50):
    """Initiate Phase 1 analysis with top priority companies."""
    
    print("🚀 Initiating Comprehensive Analysis - Phase 1")
    print("=" * 60)
    
    # Select top companies for Phase 1
    phase1_companies = companies[:max_companies]
    
    print(f"🎯 Phase 1 Target: {len(phase1_companies)} companies")
    print(f"📊 Top 10 Companies:")
    for i, company in enumerate(phase1_companies[:10], 1):
        print(f"  {i:2d}. {company['symbol']} ({company['category']})")
    
    # Create analysis configuration
    analysis_config = {
        "phase": 1,
        "total_companies": len(phase1_companies),
        "companies": [{"symbol": c["symbol"], "category": c["category"]} for c in phase1_companies],
        "analysis_types": [
            "comprehensive_financial_metrics",
            "investment_scoring", 
            "risk_analysis",
            "quality_assessment",
            "valuation_analysis"
        ],
        "data_sources": [
            "eodhd_fundamentals",
            "eodhd_prices",
            "eodhd_news",
            "eodhd_sentiments"
        ],
        "output_metrics": [
            "profitability_ratios",
            "financial_health",
            "growth_rates", 
            "valuation_metrics",
            "quality_scores",
            "red_flags",
            "investment_categories"
        ]
    }
    
    # Save analysis configuration
    settings = load_settings()
    config_file = settings.output_dir / "comprehensive_analysis" / "phase1_config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(config_file, analysis_config)
    
    print(f"\n📋 Analysis Configuration:")
    print(f"  Phase: {analysis_config['phase']}")
    print(f"  Companies: {analysis_config['total_companies']}")
    print(f"  Analysis Types: {len(analysis_config['analysis_types'])}")
    print(f"  Data Sources: {len(analysis_config['data_sources'])}")
    print(f"  Output Metrics: {len(analysis_config['output_metrics'])}")
    print(f"  Config saved to: {config_file}")
    
    return phase1_companies, analysis_config

def create_execution_plan(companies: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
    """Create detailed execution plan for the analysis."""
    
    execution_plan = {
        "analysis_id": f"phase1_{len(companies)}_companies",
        "timestamp": str(Path(__file__).resolve()),
        "steps": [
            {
                "step": 1,
                "name": "Data Download",
                "description": "Download comprehensive EODHD data for all companies",
                "script": "download_comprehensive_eodhd_data.py",
                "parameters": f"--max-companies {len(companies)}",
                "estimated_time": "30-60 minutes",
                "dependencies": ["EODHD_API_KEY"]
            },
            {
                "step": 2,
                "name": "Metrics Calculation", 
                "description": "Calculate 76+ comprehensive financial metrics",
                "script": "run_comprehensive_analysis.py",
                "parameters": f"--max-companies {len(companies)}",
                "estimated_time": "10-15 minutes",
                "dependencies": ["Data Download"]
            },
            {
                "step": 3,
                "name": "Investment Scoring",
                "description": "Generate investment scores and rankings",
                "script": "generate_investment_rankings.py",
                "parameters": "--phase 1",
                "estimated_time": "5-10 minutes", 
                "dependencies": ["Metrics Calculation"]
            },
            {
                "step": 4,
                "name": "Report Generation",
                "description": "Create detailed analysis reports and visualizations",
                "script": "create_analysis_reports.py",
                "parameters": "--format html,pdf",
                "estimated_time": "15-20 minutes",
                "dependencies": ["Investment Scoring"]
            }
        ],
        "total_estimated_time": "60-105 minutes",
        "success_criteria": [
            "All companies downloaded successfully",
            "76+ metrics calculated per company", 
            "Investment scores generated",
            "Analysis reports created"
        ]
    }
    
    return execution_plan

def main():
    """Main execution function."""
    
    print("🎯 Initiating Comprehensive Analysis System")
    print("=" * 60)
    
    # Load strategic companies
    companies = load_strategic_companies()
    if not companies:
        return
    
    # Start Phase 1 with top 50 companies
    phase1_companies, config = initiate_analysis_phase_1(companies, max_companies=50)
    
    # Create execution plan
    execution_plan = create_execution_plan(phase1_companies, config)
    
    # Save execution plan
    settings = load_settings()
    plan_file = settings.output_dir / "comprehensive_analysis" / "execution_plan.json"
    write_json(plan_file, execution_plan)
    
    print(f"\n📋 Execution Plan:")
    print(f"  Analysis ID: {execution_plan['analysis_id']}")
    print(f"  Estimated Time: {execution_plan['total_estimated_time']}")
    print(f"  Success Criteria: {len(execution_plan['success_criteria'])} items")
    print(f"  Plan saved to: {plan_file}")
    
    print(f"\n🚀 Ready to Execute!")
    print(f"📊 Next Steps:")
    for step in execution_plan["steps"]:
        print(f"  Step {step['step']}: {step['name']} ({step['estimated_time']})")
    
    # Check if EODHD API key is configured
    settings = load_settings()
    if settings.eodhd_api_key:
        print(f"\n✅ EODHD API Key configured: {'*' * len(settings.eodhd_api_key)}")
        print(f"🚀 Ready to start data download!")
        
        # Ask user if they want to proceed
        print(f"\n🎯 To start the analysis, run:")
        print(f"  python scripts/download_comprehensive_eodhd_data.py --max-companies 50")
        
    else:
        print(f"\n⚠️  EODHD API Key not configured")
        print(f"📋 To configure: Set EODHD_API_KEY environment variable")
        print(f"🎯 Then run: python scripts/download_comprehensive_eodhd_data.py --max-companies 50")
    
    return execution_plan

if __name__ == "__main__":
    main()
