#!/usr/bin/env python3

"""
Deep Debug EODHD API Structure
Explore the complete data structure to find financial data.
"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest

def explore_dict_structure(d, prefix="", max_depth=3, current_depth=0):
    """Recursively explore dictionary structure."""
    
    if current_depth >= max_depth:
        return
    
    if isinstance(d, dict):
        for key, value in d.items():
            print(f"{prefix}  {key}: {type(value).__name__}")
            
            if isinstance(value, dict):
                if current_depth < max_depth - 1:
                    explore_dict_structure(value, prefix + "    ", max_depth, current_depth + 1)
            elif isinstance(value, list):
                print(f"{prefix}    List length: {len(value)}")
                if value and isinstance(value[0], dict):
                    print(f"{prefix}    First item keys: {list(value[0].keys())[:5]}...")
                    if len(value[0].keys()) <= 5 and current_depth < max_depth - 1:
                        explore_dict_structure(value[0], prefix + "      ", max_depth, current_depth + 1)

def deep_debug_api():
    """Deep debug the EODHD API to find financial data."""
    
    print("🔍 DEEP DEBUG: Exploring EODHD API Structure")
    print("=" * 60)
    
    settings = load_settings()
    client = EODHDClient(api_key=settings.eodhd_api_key)
    
    # Test with AAPL
    symbol = "AAPL"
    print(f"\n📊 Deep analysis of {symbol}...")
    
    try:
        fundamentals = client.get_json(EODHDRequest(
            endpoint=f"fundamentals/{symbol}.US",
            params={}
        ))
        
        print(f"Response type: {type(fundamentals)}")
        
        if isinstance(fundamentals, dict):
            print(f"\n📋 Complete structure:")
            explore_dict_structure(fundamentals, "", max_depth=4)
            
            # Look for any keys that might contain financial data
            print(f"\n🔍 Searching for financial data keys...")
            financial_keys = []
            for key in fundamentals.keys():
                key_lower = key.lower()
                if any(term in key_lower for term in ['financial', 'income', 'balance', 'cash', 'statement', 'quarter', 'annual']):
                    financial_keys.append(key)
            
            print(f"Potential financial data keys: {financial_keys}")
            
            # Explore each financial key
            for key in financial_keys:
                value = fundamentals[key]
                print(f"\n📊 Exploring '{key}':")
                
                if isinstance(value, dict):
                    print(f"  Type: dict with {len(value)} keys")
                    for subkey, subvalue in value.items():
                        if isinstance(subvalue, list):
                            print(f"    {subkey}: list with {len(subvalue)} items")
                            if subvalue and isinstance(subvalue[0], dict):
                                sample_keys = list(subvalue[0].keys())
                                print(f"      Sample keys: {sample_keys[:10]}")
                                # Check for revenue data
                                if any('revenue' in k.lower() for k in sample_keys):
                                    print(f"      ✅ Contains revenue data!")
                                if any('income' in k.lower() for k in sample_keys):
                                    print(f"      ✅ Contains income data!")
                        else:
                            print(f"    {subkey}: {type(subvalue).__name__}")
                elif isinstance(value, list):
                    print(f"  Type: list with {len(value)} items")
                    if value and isinstance(value[0], dict):
                        sample_keys = list(value[0].keys())
                        print(f"    Sample keys: {sample_keys[:10]}")
        
        # Also try to save the raw response for manual inspection
        print(f"\n💾 Saving raw response for inspection...")
        settings = load_settings()
        debug_dir = settings.output_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        raw_file = debug_dir / f"{symbol}_raw_response.json"
        with open(raw_file, 'w') as f:
            json.dump(fundamentals, f, indent=2, default=str)
        
        print(f"Raw response saved to: {raw_file}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    deep_debug_api()
