#!/usr/bin/env python3

"""
Multi-Strategy Analysis System
Analyzes all companies using Conservative, Balanced, and Growth strategies with configurable parameters.
"""

import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_json, write_jsonl

@dataclass
class StrategyConfig:
    """Configuration for investment strategy."""
    name: str
    max_companies: int
    min_market_cap_millions: float
    quality_weight: float
    value_weight: float
    growth_weight: float
    safety_weight: float
    momentum_weight: float
    min_score_threshold: float
    description: str

def get_default_strategies() -> Dict[str, StrategyConfig]:
    """Get default strategy configurations."""
    return {
        "conservative": StrategyConfig(
            name="Conservative",
            max_companies=500,
            min_market_cap_millions=500.0,
            quality_weight=0.35,
            value_weight=0.35,
            growth_weight=0.15,
            safety_weight=0.15,
            momentum_weight=0.0,
            min_score_threshold=10.0,
            description="Focus on large-cap, high-quality companies with strong balance sheets"
        ),
        
        "balanced": StrategyConfig(
            name="Balanced",
            max_companies=1000,
            min_market_cap_millions=100.0,
            quality_weight=0.25,
            value_weight=0.25,
            growth_weight=0.25,
            safety_weight=0.15,
            momentum_weight=0.10,
            min_score_threshold=8.0,
            description="Balanced approach across quality, value, and growth factors"
        ),
        
        "growth": StrategyConfig(
            name="Growth",
            max_companies=1500,
            min_market_cap_millions=50.0,
            quality_weight=0.20,
            value_weight=0.15,
            growth_weight=0.40,
            safety_weight=0.10,
            momentum_weight=0.15,
            min_score_threshold=6.0,
            description="Emphasis on growth companies with strong momentum"
        )
    }

def calculate_strategy_score(company: Dict[str, Any], config: StrategyConfig) -> Dict[str, Any]:
    """Calculate strategy-specific score for a company."""
    
    # Get base scores from investment_scores
    base_scores = company.get("investment_scores", {})
    
    # Get financial metrics
    metrics = company.get("financial_metrics", {})
    company_info = company.get("company_info", {})
    
    # Calculate weighted score
    quality_score = base_scores.get("quality_score", 0) / 5.0  # Normalize to 0-1
    value_score = base_scores.get("value_score", 0) / 5.0
    growth_score = base_scores.get("growth_score", 0) / 5.0
    safety_score = base_scores.get("safety_score", 0) / 5.0
    momentum_score = base_scores.get("momentum_score", 0) / 5.0
    
    # Apply strategy weights
    weighted_score = (
        quality_score * config.quality_weight +
        value_score * config.value_weight +
        growth_score * config.growth_weight +
        safety_score * config.safety_weight +
        momentum_score * config.momentum_weight
    )
    
    # Convert to 0-20 scale
    strategy_score = weighted_score * 20
    
    # Apply market cap filter
    market_cap = company_info.get("market_cap", 0) / 1e6  # Convert to millions
    meets_market_cap = market_cap >= config.min_market_cap_millions
    
    # Determine if company qualifies for strategy
    qualifies = meets_market_cap and strategy_score >= config.min_score_threshold
    
    return {
        "strategy_name": config.name,
        "strategy_score": strategy_score,
        "qualifies": qualifies,
        "market_cap_millions": market_cap,
        "meets_market_cap": meets_market_cap,
        "score_breakdown": {
            "quality": quality_score * config.quality_weight * 20,
            "value": value_score * config.value_weight * 20,
            "growth": growth_score * config.growth_weight * 20,
            "safety": safety_score * config.safety_weight * 20,
            "momentum": momentum_score * config.momentum_weight * 20
        }
    }

def analyze_all_strategies(companies: List[Dict[str, Any]], 
                          strategies: Dict[str, StrategyConfig]) -> Dict[str, Any]:
    """Analyze all companies using all strategies."""
    
    print(f"🔍 Analyzing {len(companies)} companies with {len(strategies)} strategies...")
    
    results = {}
    
    for strategy_name, config in strategies.items():
        print(f"\n📊 Processing {config.name} strategy...")
        
        strategy_results = []
        qualified_count = 0
        
        for company in companies:
            strategy_result = calculate_strategy_score(company, config)
            
            # Add company info to result
            strategy_result.update({
                "symbol": company["symbol"],
                "name": company["name"],
                "sector": company["sector"],
                "base_score": company.get("investment_scores", {}).get("overall_score", 0),
                "revenue_b": company.get("financial_metrics", {}).get("revenue", 0) / 1e9,
                "roe_pct": company.get("financial_metrics", {}).get("roe", 0) * 100,
                "pe_ratio": company.get("financial_metrics", {}).get("pe_ratio", 0)
            })
            
            strategy_results.append(strategy_result)
            
            if strategy_result["qualifies"]:
                qualified_count += 1
        
        # Sort by strategy score (descending)
        strategy_results.sort(key=lambda x: x["strategy_score"], reverse=True)
        
        # Limit to max_companies
        limited_results = strategy_results[:config.max_companies]
        
        results[strategy_name] = {
            "config": {
                "name": config.name,
                "max_companies": config.max_companies,
                "min_market_cap_millions": config.min_market_cap_millions,
                "weights": {
                    "quality": config.quality_weight,
                    "value": config.value_weight,
                    "growth": config.growth_weight,
                    "safety": config.safety_weight,
                    "momentum": config.momentum_weight
                },
                "min_score_threshold": config.min_score_threshold,
                "description": config.description
            },
            "summary": {
                "total_analyzed": len(companies),
                "qualified_count": qualified_count,
                "qualified_rate": qualified_count / len(companies) * 100,
                "selected_count": len(limited_results),
                "top_score": limited_results[0]["strategy_score"] if limited_results else 0,
                "average_score": sum(r["strategy_score"] for r in limited_results) / len(limited_results) if limited_results else 0
            },
            "companies": limited_results
        }
        
        print(f"✅ {config.name}: {qualified_count}/{len(companies)} qualify ({qualified_count/len(companies)*100:.1f}%)")
        print(f"📈 Selected top {len(limited_results)} companies")
        print(f"🏆 Top score: {limited_results[0]['strategy_score']:.1f}/20" if limited_results else "🏆 No companies qualified")
    
    return results

def save_multi_strategy_results(results: Dict[str, Any], settings):
    """Save multi-strategy analysis results."""
    
    output_dir = settings.output_dir / "multi_strategy_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save detailed results
    results_file = output_dir / f"multi_strategy_results_{timestamp}.json"
    write_json(results_file, results)
    
    # Save summary for web interface
    summary = {
        "timestamp": timestamp,
        "strategies": {},
        "total_companies": next(iter(results.values()))["summary"]["total_analyzed"]
    }
    
    for strategy_name, strategy_data in results.items():
        summary["strategies"][strategy_name] = {
            "name": strategy_data["config"]["name"],
            "description": strategy_data["config"]["description"],
            "selected_count": strategy_data["summary"]["selected_count"],
            "qualified_rate": strategy_data["summary"]["qualified_rate"],
            "top_score": strategy_data["summary"]["top_score"],
            "average_score": strategy_data["summary"]["average_score"],
            "companies": strategy_data["companies"][:20]  # Top 20 for web interface
        }
    
    summary_file = output_dir / f"multi_strategy_summary_{timestamp}.json"
    write_json(summary_file, summary)
    
    # Save individual strategy files for web interface
    for strategy_name, strategy_data in results.items():
        strategy_file = output_dir / f"{strategy_name}_strategy_{timestamp}.jsonl"
        write_jsonl(strategy_file, strategy_data["companies"])
    
    print(f"\n💾 Results saved to: {output_dir}")
    print(f"📋 Summary: {summary_file}")
    print(f"📊 Detailed: {results_file}")
    
    return output_dir, timestamp

def load_base_analysis_data():
    """Load the most comprehensive analysis data available."""
    
    settings = load_settings()
    output_dir = settings.output_dir
    
    # Try scaled_analysis first (most comprehensive)
    scaled_dir = output_dir / "scaled_analysis"
    if scaled_dir.exists():
        analysis_files = list(scaled_dir.glob("scaled_analysis_*.jsonl"))
        if analysis_files:
            latest_file = max(analysis_files, key=lambda x: x.stat().st_mtime)
            companies = read_jsonl(latest_file)
            print(f"✅ Loaded {len(companies)} companies from scaled analysis")
            return companies
    
    # Fallback to final_working_analysis
    final_dir = output_dir / "final_working_analysis"
    if final_dir.exists():
        analysis_files = list(final_dir.glob("*analysis_*.jsonl"))
        if analysis_files:
            latest_file = max(analysis_files, key=lambda x: x.stat().st_mtime)
            companies = read_jsonl(latest_file)
            print(f"✅ Loaded {len(companies)} companies from final working analysis")
            return companies
    
    raise FileNotFoundError("No analysis data found")

def main():
    """Main function to run multi-strategy analysis."""
    
    print("🚀 MULTI-STRATEGY ANALYSIS SYSTEM")
    print("=" * 50)
    
    try:
        # Load base analysis data
        companies = load_base_analysis_data()
        
        # Get strategy configurations
        strategies = get_default_strategies()
        
        print(f"\n📋 Strategies to analyze:")
        for name, config in strategies.items():
            print(f"  • {config.name}: {config.description}")
            print(f"    Max companies: {config.max_companies}")
            print(f"    Min market cap: ${config.min_market_cap_millions}M")
            print(f"    Weights: Q:{config.quality_weight} V:{config.value_weight} G:{config.growth_weight} S:{config.safety_weight} M:{config.momentum_weight}")
        
        # Analyze all strategies
        results = analyze_all_strategies(companies, strategies)
        
        # Save results
        settings = load_settings()
        output_dir, timestamp = save_multi_strategy_results(results, settings)
        
        # Print summary
        print(f"\n🎯 MULTI-STRATEGY ANALYSIS COMPLETE!")
        print("=" * 60)
        
        for strategy_name, strategy_data in results.items():
            config = strategy_data["config"]
            summary = strategy_data["summary"]
            
            print(f"\n📊 {config['name']} Strategy:")
            print(f"  📈 Companies analyzed: {summary['total_analyzed']}")
            print(f"  ✅ Qualified: {summary['qualified_count']} ({summary['qualified_rate']:.1f}%)")
            print(f"  🎯 Selected: {summary['selected_count']}")
            print(f"  🏆 Top score: {summary['top_score']:.1f}/20")
            print(f"  📊 Average score: {summary['average_score']:.1f}/20")
            
            if strategy_data["companies"]:
                top_company = strategy_data["companies"][0]
                print(f"  🥇 Top company: {top_company['symbol']} ({top_company['name']})")
        
        print(f"\n💾 Results available for web interface")
        print(f"🌐 Ready to load in dashboard")
        
        return output_dir, timestamp
        
    except Exception as e:
        print(f"❌ Multi-strategy analysis failed: {e}")
        raise

if __name__ == "__main__":
    main()
