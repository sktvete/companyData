#!/usr/bin/env python3

"""
Budget-Conscious GPT-4o Testing
Test GPT-4o qualitative analysis with minimal cost usage.
"""

import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import write_json
from equity_sorter.qualitative.gpt4o_analysis import GPT4oQualitativeAnalyzer

def test_gpt4o_minimal():
    """Test GPT-4o with minimal budget usage."""
    
    print("💰 BUDGET-CONSCIOUS GPT-4O TESTING")
    print("=" * 50)
    print("Testing with minimal API calls to control costs...")
    
    # Test data for top companies from our analysis
    test_companies = [
        {
            "symbol": "NVDA",
            "name": "NVIDIA Corporation",
            "sector": "Technology",
            "revenue_b": 68.1,
            "roe_pct": 27.3,
            "overall_score": 6,
            "category": "POOR",
            "key_metrics": {
                "revenue_growth": "Strong AI-driven growth",
                "profitability": "Excellent margins",
                "market_position": "AI chip leader"
            }
        },
        {
            "symbol": "AAPL", 
            "name": "Apple Inc.",
            "sector": "Technology",
            "revenue_b": 111.2,
            "roe_pct": 27.8,
            "overall_score": 3,
            "category": "RISKY",
            "key_metrics": {
                "revenue_growth": "Mature growth",
                "profitability": "Strong margins", 
                "market_position": "Consumer tech leader"
            }
        }
    ]
    
    try:
        # Initialize GPT-4o analyzer
        import os
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            print("❌ OPENAI_API_KEY not found in environment")
            return {"test_status": "FAILED", "error": "OpenAI API key not configured"}
        
        analyzer = GPT4oQualitativeAnalyzer(api_key=openai_key)
        
        print(f"✅ GPT-4o analyzer initialized")
        
        # Test with just 1 company to minimize cost
        test_company = test_companies[0]  # NVDA only
        
        print(f"\n🔍 Testing {test_company['symbol']} ({test_company['name']})...")
        
        # Create minimal prompt for business model analysis
        prompt = f"""
        Analyze {test_company['symbol']} ({test_company['name']}) in 2-3 sentences:
        
        Key data: {test_company['revenue_b']:.1f}B revenue, {test_company['roe_pct']:.1f}% ROE, {test_company['sector']} sector.
        
        Focus on: business model strength and competitive advantage.
        Keep response under 100 words to minimize cost.
        """
        
        # Make single API call
        response = analyzer.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a financial analyst. Be concise and factual."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,  # Limit tokens to control cost
            temperature=0.3
        )
        
        analysis = response.choices[0].message.content
        
        # Calculate estimated cost (rough approximation)
        # GPT-4o costs ~$0.005 per 1K input tokens, $0.015 per 1K output tokens
        input_tokens = len(prompt.split()) * 1.3  # Rough estimate
        output_tokens = len(analysis.split()) * 1.3
        
        estimated_cost = (input_tokens * 0.005 / 1000) + (output_tokens * 0.015 / 1000)
        
        print(f"✅ Analysis completed successfully!")
        print(f"💰 Estimated cost: ${estimated_cost:.6f}")
        print(f"📊 Response length: {len(analysis)} characters")
        
        print(f"\n📋 GPT-4o Analysis for {test_company['symbol']}:")
        print("-" * 40)
        print(analysis)
        print("-" * 40)
        
        # Save result
        result = {
            "test_timestamp": datetime.now().isoformat(),
            "company": test_company,
            "gpt4o_analysis": analysis,
            "estimated_cost_usd": estimated_cost,
            "token_estimate": {
                "input": int(input_tokens),
                "output": int(output_tokens)
            },
            "test_status": "SUCCESS"
        }
        
        settings = load_settings()
        output_dir = settings.output_dir / "gpt4o_tests"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        result_file = output_dir / f"budget_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        write_json(result_file, result)
        
        print(f"\n💾 Result saved to: {result_file}")
        
        # Budget analysis
        print(f"\n💡 BUDGET ANALYSIS:")
        print(f"  Single company test: ${estimated_cost:.6f}")
        print(f"  Cost for 10 companies: ${estimated_cost * 10:.4f}")
        print(f"  Cost for 50 companies: ${estimated_cost * 50:.4f}")
        print(f"  Cost for 100 companies: ${estimated_cost * 100:.4f}")
        print(f"  Your $20 budget could analyze: {int(20 / estimated_cost)} companies")
        
        if estimated_cost < 0.01:
            print(f"✅ Cost per company is very reasonable!")
        else:
            print(f"⚠️  Consider reducing analysis scope for larger scale")
        
        return result
        
    except Exception as e:
        print(f"❌ GPT-4o test failed: {e}")
        
        error_result = {
            "test_timestamp": datetime.now().isoformat(),
            "error": str(e),
            "test_status": "FAILED"
        }
        
        return error_result

def test_cost_optimization():
    """Test different prompt strategies to optimize cost."""
    
    print(f"\n🔧 COST OPTIMIZATION TESTING")
    print("=" * 40)
    
    strategies = [
        {
            "name": "Ultra-Concise",
            "prompt": "NVDA business model in 1 sentence:",
            "max_tokens": 50
        },
        {
            "name": "Balanced", 
            "prompt": "NVDA competitive advantage in 2 sentences:",
            "max_tokens": 100
        },
        {
            "name": "Detailed",
            "prompt": "Analyze NVDA business model, competitive advantage, and risks in 3 sentences:",
            "max_tokens": 150
        }
    ]
    
    try:
        import os
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            print("❌ OPENAI_API_KEY not found")
            return []
        
        analyzer = GPT4oQualitativeAnalyzer(api_key=openai_key)
        
        results = []
        
        for strategy in strategies:
            print(f"\n📝 Testing: {strategy['name']}")
            
            response = analyzer.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": strategy['prompt']}
                ],
                max_tokens=strategy['max_tokens'],
                temperature=0.3
            )
            
            analysis = response.choices[0].message.content
            
            # Rough cost calculation
            input_tokens = len(strategy['prompt'].split()) * 1.3
            output_tokens = len(analysis.split()) * 1.3
            cost = (input_tokens * 0.005 / 1000) + (output_tokens * 0.015 / 1000)
            
            result = {
                "strategy": strategy['name'],
                "analysis": analysis,
                "cost_usd": cost,
                "char_count": len(analysis),
                "word_count": len(analysis.split())
            }
            
            results.append(result)
            
            print(f"  Cost: ${cost:.6f}")
            print(f"  Length: {result['word_count']} words")
            print(f"  Analysis: {analysis[:100]}...")
        
        # Find best value
        best_value = min(results, key=lambda x: x['cost_usd'] / x['word_count'])
        
        print(f"\n🏆 Best Value Strategy: {best_value['strategy']}")
        print(f"   Cost per word: ${best_value['cost_usd'] / best_value['word_count']:.6f}")
        
        return results
        
    except Exception as e:
        print(f"❌ Cost optimization test failed: {e}")
        return []

if __name__ == "__main__":
    print("🚀 Starting Budget-Conscious GPT-4o Testing")
    print("=" * 60)
    
    # Run minimal test
    result = test_gpt4o_minimal()
    
    # Run cost optimization
    cost_results = test_cost_optimization()
    
    print(f"\n🎯 TESTING SUMMARY:")
    print("=" * 40)
    
    if result.get("test_status") == "SUCCESS":
        print(f"✅ GPT-4o integration working")
        print(f"💰 Single analysis cost: ${result['estimated_cost_usd']:.6f}")
        print(f"📊 Your $20 budget can analyze ~{int(20 / result['estimated_cost_usd'])} companies")
    else:
        print(f"❌ GPT-4o test failed: {result.get('error', 'Unknown error')}")
    
    if cost_results:
        print(f"✅ Cost optimization tested with {len(cost_results)} strategies")
    
    print(f"\n💡 RECOMMENDATIONS:")
    print(f"  • Use ultra-concise prompts for large-scale analysis")
    print(f"  • Limit to top 20-50 companies within $20 budget")
    print(f"  • Cache results to avoid repeated API calls")
    print(f"  • Consider batch processing for efficiency")
