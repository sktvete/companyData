#!/usr/bin/env python3

"""
Generate Investment Rankings - Step 3
Combines quantitative metrics with GPT-4o qualitative analysis for comprehensive investment scoring.
"""

import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_jsonl, write_json
from equity_sorter.qualitative.gpt4o_analysis import GPT4oQualitativeAnalyzer

def load_phase1_analysis() -> List[Dict[str, Any]]:
    """Load Phase 1 quantitative analysis results."""
    
    settings = load_settings()
    analysis_file = settings.output_dir / "comprehensive_analysis" / "phase1_demo" / "detailed_analyses.jsonl"
    
    if not analysis_file.exists():
        print("❌ Phase 1 analysis not found. Run demo_phase1_analysis.py first.")
        return []
    
    companies = read_jsonl(analysis_file)
    print(f"📊 Loaded {len(companies)} companies from Phase 1 analysis")
    
    return companies

def enhance_with_qualitative_analysis(companies: List[Dict[str, Any]], max_companies: int = 10) -> List[Dict[str, Any]]:
    """Enhance quantitative analysis with GPT-4o qualitative insights."""
    
    print(f"🤖 Enhancing analysis with GPT-4o qualitative insights...")
    print(f"🎯 Analyzing top {max_companies} companies...")
    
    # Sort by quantitative score and take top companies
    companies.sort(key=lambda x: x.get("investment_scores", {}).get("overall_score", 0), reverse=True)
    top_companies = companies[:max_companies]
    
    analyzer = GPT4oQualitativeAnalyzer()
    enhanced_companies = []
    
    for i, company in enumerate(top_companies):
        symbol = company["symbol"]
        print(f"🔍 [{i+1}/{max_companies}] {symbol} - Qualitative analysis...")
        
        try:
            # Perform GPT-4o analysis
            qualitative_analysis = analyzer.comprehensive_analysis(company)
            
            # Merge with existing analysis
            enhanced_company = company.copy()
            enhanced_company["qualitative_analysis"] = qualitative_analysis
            enhanced_company["enhanced_timestamp"] = datetime.now().isoformat()
            
            # Calculate combined scores
            enhanced_company["combined_scores"] = calculate_combined_scores(enhanced_company)
            
            enhanced_companies.append(enhanced_company)
            
            # Show key results
            quant_score = company.get("investment_scores", {}).get("overall_score", 0)
            qual_score = qualitative_analysis.get("qualitative_scores", {}).get("overall_qualitative_score", 0) * 4  # Scale to 20
            combined_score = enhanced_company["combined_scores"]["overall_combined_score"]
            
            print(f"    Quantitative: {quant_score:.1f}/20")
            print(f"    Qualitative: {qual_score:.1f}/20")
            print(f"    Combined: {combined_score:.1f}/20")
            print()
            
        except Exception as e:
            print(f"    ❌ Qualitative analysis failed: {e}")
            enhanced_company = company.copy()
            enhanced_company["qualitative_analysis"] = {"error": str(e)}
            enhanced_company["combined_scores"] = {"overall_combined_score": company.get("investment_scores", {}).get("overall_score", 0)}
            enhanced_companies.append(enhanced_company)
    
    return enhanced_companies

def calculate_combined_scores(company: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate combined quantitative + qualitative scores."""
    
    # Get quantitative scores (scaled to 20)
    quant_scores = company.get("investment_scores", {})
    quant_overall = quant_scores.get("overall_score", 0)
    
    # Get qualitative scores (scaled to 20)
    qual_analysis = company.get("qualitative_analysis", {})
    qual_scores = qual_analysis.get("qualitative_scores", {})
    qual_overall = qual_scores.get("overall_qualitative_score", 0) * 4  # Scale 5-point to 20-point
    
    # Weighted combination (60% quantitative, 40% qualitative)
    combined_overall = quant_overall * 0.6 + qual_overall * 0.4
    
    # Individual component scores
    combined_scores = {
        "overall_combined_score": combined_overall,
        "quantitative_score": quant_overall,
        "qualitative_score": qual_overall,
        "quantitative_weight": 0.6,
        "qualitative_weight": 0.4,
        
        # Enhanced category scores
        "enhanced_value_score": quant_scores.get("value_score", 0) * 0.6 + qual_scores.get("business_model_score", 0) * 0.4,
        "enhanced_quality_score": quant_scores.get("quality_score", 0) * 0.6 + qual_scores.get("management_score", 0) * 0.4,
        "enhanced_growth_score": quant_scores.get("growth_score", 0) * 0.6 + qual_scores.get("business_model_score", 0) * 0.4,
        "enhanced_safety_score": quant_scores.get("safety_score", 0) * 0.6 + qual_scores.get("moat_score", 0) * 0.4,
    }
    
    # Determine investment category
    overall = combined_scores["overall_combined_score"]
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
    
    combined_scores["investment_category"] = category
    
    return combined_scores

def generate_investment_rankings(enhanced_companies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate comprehensive investment rankings."""
    
    print("📊 Generating comprehensive investment rankings...")
    
    # Sort by combined score
    enhanced_companies.sort(key=lambda x: x.get("combined_scores", {}).get("overall_combined_score", 0), reverse=True)
    
    # Create rankings
    rankings = {
        "analysis_timestamp": datetime.now().isoformat(),
        "total_companies_analyzed": len(enhanced_companies),
        "ranking_methodology": "60% Quantitative + 40% Qualitative (GPT-4o)",
        "top_performers": [],
        "category_breakdown": {},
        "score_analysis": {},
        "investment_recommendations": []
    }
    
    # Top performers
    for i, company in enumerate(enhanced_companies[:10]):
        symbol = company["symbol"]
        combined_scores = company.get("combined_scores", {})
        qual_analysis = company.get("qualitative_analysis", {})
        
        performer = {
            "rank": i + 1,
            "symbol": symbol,
            "category": company.get("category", "Unknown"),
            "combined_score": combined_scores.get("overall_combined_score", 0),
            "quantitative_score": combined_scores.get("quantitative_score", 0),
            "qualitative_score": combined_scores.get("qualitative_score", 0),
            "investment_category": combined_scores.get("investment_category", "UNKNOWN"),
            
            # Qualitative insights
            "business_model_strength": qual_analysis.get("gpt4o_analysis", {}).get("business_model", {}).get("business_model_strength", "UNKNOWN"),
            "moat_strength": qual_analysis.get("gpt4o_analysis", {}).get("competitive_advantages", {}).get("overall_moat_strength", "UNKNOWN"),
            "management_quality": qual_analysis.get("gpt4o_analysis", {}).get("management_quality", {}).get("overall_management_quality", "UNKNOWN"),
            "investment_recommendation": qual_analysis.get("gpt4o_analysis", {}).get("investment_thesis", {}).get("investment_recommendation", "UNKNOWN")
        }
        
        rankings["top_performers"].append(performer)
    
    # Category breakdown
    categories = {}
    for company in enhanced_companies:
        category = company.get("combined_scores", {}).get("investment_category", "UNKNOWN")
        categories[category] = categories.get(category, 0) + 1
    
    rankings["category_breakdown"] = categories
    
    # Score analysis
    combined_scores = [c.get("combined_scores", {}).get("overall_combined_score", 0) for c in enhanced_companies]
    quant_scores = [c.get("combined_scores", {}).get("quantitative_score", 0) for c in enhanced_companies]
    qual_scores = [c.get("combined_scores", {}).get("qualitative_score", 0) for c in enhanced_companies]
    
    rankings["score_analysis"] = {
        "average_combined_score": sum(combined_scores) / len(combined_scores) if combined_scores else 0,
        "average_quantitative_score": sum(quant_scores) / len(quant_scores) if quant_scores else 0,
        "average_qualitative_score": sum(qual_scores) / len(qual_scores) if qual_scores else 0,
        "highest_combined_score": max(combined_scores) if combined_scores else 0,
        "lowest_combined_score": min(combined_scores) if combined_scores else 0,
        "score_range": max(combined_scores) - min(combined_scores) if combined_scores else 0
    }
    
    # Investment recommendations
    buy_recommendations = [c for c in enhanced_companies if c.get("qualitative_analysis", {}).get("gpt4o_analysis", {}).get("investment_thesis", {}).get("investment_recommendation") == "BUY"]
    hold_recommendations = [c for c in enhanced_companies if c.get("qualitative_analysis", {}).get("gpt4o_analysis", {}).get("investment_thesis", {}).get("investment_recommendation") == "HOLD"]
    sell_recommendations = [c for c in enhanced_companies if c.get("qualitative_analysis", {}).get("gpt4o_analysis", {}).get("investment_thesis", {}).get("investment_recommendation") == "SELL"]
    
    rankings["investment_recommendations"] = {
        "buy": [{"symbol": c["symbol"], "combined_score": c.get("combined_scores", {}).get("overall_combined_score", 0)} for c in buy_recommendations],
        "hold": [{"symbol": c["symbol"], "combined_score": c.get("combined_scores", {}).get("overall_combined_score", 0)} for c in hold_recommendations],
        "sell": [{"symbol": c["symbol"], "combined_score": c.get("combined_scores", {}).get("overall_combined_score", 0)} for c in sell_recommendations],
        "buy_count": len(buy_recommendations),
        "hold_count": len(hold_recommendations),
        "sell_count": len(sell_recommendations)
    }
    
    return rankings

def create_analysis_reports(enhanced_companies: List[Dict[str, Any]], rankings: Dict[str, Any]) -> Dict[str, Any]:
    """Create detailed analysis reports (Step 4)."""
    
    print("📋 Creating comprehensive analysis reports...")
    
    reports = {
        "executive_summary": create_executive_summary(rankings),
        "detailed_company_reports": create_company_reports(enhanced_companies),
        "sector_analysis": create_sector_analysis(enhanced_companies),
        "risk_analysis": create_risk_analysis(enhanced_companies),
        "portfolio_recommendations": create_portfolio_recommendations(enhanced_companies, rankings)
    }
    
    return reports

def create_executive_summary(rankings: Dict[str, Any]) -> Dict[str, Any]:
    """Create executive summary report."""
    
    return {
        "total_companies_analyzed": rankings["total_companies_analyzed"],
        "analysis_methodology": rankings["ranking_methodology"],
        "key_findings": [
            f"Top performer: {rankings['top_performers'][0]['symbol']} with score {rankings['top_performers'][0]['combined_score']:.1f}/20",
            f"Average combined score: {rankings['score_analysis']['average_combined_score']:.1f}/20",
            f"Companies rated EXCELLENT: {rankings['category_breakdown'].get('EXCELLENT', 0)}",
            f"BUY recommendations: {rankings['investment_recommendations']['buy_count']}"
        ],
        "investment_highlights": [
            f"Best quantitative performer: {max(rankings['top_performers'], key=lambda x: x['quantitative_score'])['symbol']}",
            f"Best qualitative performer: {max(rankings['top_performers'], key=lambda x: x['qualitative_score'])['symbol']}",
            f"Most balanced: {min(rankings['top_performers'], key=lambda x: abs(x['quantitative_score'] - x['qualitative_score']))['symbol']}"
        ],
        "risk_considerations": [
            "Qualitative analysis adds important context to quantitative metrics",
            "GPT-4o insights help identify non-financial risks and opportunities",
            "Combined scoring provides more balanced investment decisions"
        ]
    }

def create_company_reports(companies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create detailed reports for each company."""
    
    reports = []
    for company in companies:
        symbol = company["symbol"]
        
        report = {
            "symbol": symbol,
            "executive_summary": f"{symbol} scores {company.get('combined_scores', {}).get('overall_combined_score', 0):.1f}/20 overall, combining quantitative analysis with GPT-4o qualitative insights.",
            "quantitative_analysis": {
                "overall_score": company.get("investment_scores", {}).get("overall_score", 0),
                "category": company.get("investment_scores", {}).get("investment_category", "UNKNOWN"),
                "key_metrics": {
                    "roe": company.get("financial_metrics", {}).get("roe", 0),
                    "pe_ratio": company.get("financial_metrics", {}).get("pe_ratio", 0),
                    "revenue_growth": company.get("financial_metrics", {}).get("revenue_growth_1y", 0)
                }
            },
            "qualitative_analysis": company.get("qualitative_analysis", {}).get("gpt4o_analysis", {}),
            "combined_assessment": {
                "overall_score": company.get("combined_scores", {}).get("overall_combined_score", 0),
                "category": company.get("combined_scores", {}).get("investment_category", "UNKNOWN"),
                "investment_recommendation": company.get("qualitative_analysis", {}).get("gpt4o_analysis", {}).get("investment_thesis", {}).get("investment_recommendation", "UNKNOWN")
            }
        }
        
        reports.append(report)
    
    return reports

def create_sector_analysis(companies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create sector-level analysis."""
    
    sectors = {}
    for company in companies:
        sector = company.get("category", "Unknown")
        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append(company)
    
    sector_analysis = {}
    for sector, sector_companies in sectors.items():
        combined_scores = [c.get("combined_scores", {}).get("overall_combined_score", 0) for c in sector_companies]
        
        sector_analysis[sector] = {
            "company_count": len(sector_companies),
            "average_score": sum(combined_scores) / len(combined_scores) if combined_scores else 0,
            "top_company": max(sector_companies, key=lambda x: x.get("combined_scores", {}).get("overall_combined_score", 0))["symbol"],
            "score_range": max(combined_scores) - min(combined_scores) if combined_scores else 0
        }
    
    return sector_analysis

def create_risk_analysis(companies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create risk analysis report."""
    
    risk_factors = {
        "quantitative_risks": [],
        "qualitative_risks": [],
        "combined_risk_assessment": []
    }
    
    for company in companies:
        symbol = company["symbol"]
        
        # Quantitative risks
        red_flags = company.get("financial_metrics", {}).get("red_flags", [])
        if red_flags:
            risk_factors["quantitative_risks"].append({
                "symbol": symbol,
                "risks": red_flags
            })
        
        # Qualitative risks
        qual_analysis = company.get("qualitative_analysis", {}).get("gpt4o_analysis", {})
        mgmt_concerns = qual_analysis.get("management_quality", {}).get("management_concerns", [])
        business_risks = qual_analysis.get("business_model", {}).get("business_model_risks", [])
        
        if mgmt_concerns or business_risks:
            risk_factors["qualitative_risks"].append({
                "symbol": symbol,
                "management_concerns": mgmt_concerns,
                "business_risks": business_risks
            })
    
    return risk_factors

def create_portfolio_recommendations(companies: List[Dict[str, Any]], rankings: Dict[str, Any]) -> Dict[str, Any]:
    """Create portfolio construction recommendations."""
    
    # Top performers for core holdings
    core_holdings = [c for c in companies if c.get("combined_scores", {}).get("overall_combined_score", 0) >= 12][:5]
    
    # Growth opportunities
    growth_candidates = [c for c in companies if c.get("financial_metrics", {}).get("revenue_growth_1y", 0) > 0.1][:3]
    
    # Value opportunities
    value_candidates = [c for c in companies if c.get("financial_metrics", {}).get("pe_ratio", 999) < 20][:3]
    
    return {
        "core_holdings": [{"symbol": c["symbol"], "score": c.get("combined_scores", {}).get("overall_combined_score", 0)} for c in core_holdings],
        "growth_opportunities": [{"symbol": c["symbol"], "growth": c.get("financial_metrics", {}).get("revenue_growth_1y", 0)} for c in growth_candidates],
        "value_opportunities": [{"symbol": c["symbol"], "pe_ratio": c.get("financial_metrics", {}).get("pe_ratio", 0)} for c in value_candidates],
        "portfolio_allocation_suggestions": {
            "core_holdings": "60-70%",
            "growth_opportunities": "20-25%",
            "value_opportunities": "10-15%"
        }
    }

def main():
    """Main execution function for Steps 3 & 4."""
    
    print("🚀 Steps 3 & 4: Investment Scoring & Report Generation")
    print("=" * 60)
    
    # Load Phase 1 analysis
    companies = load_phase1_analysis()
    if not companies:
        return
    
    # Step 3: Enhance with qualitative analysis
    enhanced_companies = enhance_with_qualitative_analysis(companies, max_companies=10)
    
    # Generate rankings
    rankings = generate_investment_rankings(enhanced_companies)
    
    # Step 4: Create reports
    reports = create_analysis_reports(enhanced_companies, rankings)
    
    # Save results
    settings = load_settings()
    output_dir = settings.output_dir / "comprehensive_analysis" / "phase2_enhanced"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save enhanced companies
    enhanced_file = output_dir / "enhanced_analyses.jsonl"
    write_jsonl(enhanced_file, enhanced_companies)
    
    # Save rankings
    rankings_file = output_dir / "investment_rankings.json"
    write_json(rankings_file, rankings)
    
    # Save reports
    reports_file = output_dir / "analysis_reports.json"
    write_json(reports_file, reports)
    
    # Display results
    print("\n🎉 Steps 3 & 4 Complete!")
    print("=" * 60)
    print(f"📊 Companies Enhanced: {len(enhanced_companies)}")
    print(f"🏆 Top Performer: {rankings['top_performers'][0]['symbol']} (Score: {rankings['top_performers'][0]['combined_score']:.1f}/20)")
    print(f"💡 Average Combined Score: {rankings['score_analysis']['average_combined_score']:.1f}/20")
    print(f"📈 BUY Recommendations: {rankings['investment_recommendations']['buy_count']}")
    
    print(f"\n🏆 Top 5 Enhanced Rankings:")
    for i, performer in enumerate(rankings['top_performers'][:5]):
        print(f"  {i+1}. {performer['symbol']} - {performer['combined_score']:.1f}/20 ({performer['investment_category']})")
    
    print(f"\n📁 Results saved to: {output_dir}")
    print(f"📊 Enhanced analyses: {enhanced_file}")
    print(f"🏆 Rankings: {rankings_file}")
    print(f"📋 Reports: {reports_file}")
    
    return rankings, reports

if __name__ == "__main__":
    main()
