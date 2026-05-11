#!/usr/bin/env python3

"""
Debug EODHD API Response Structure
Investigate the actual structure of fundamental data responses.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest

def debug_api_response():
    """Debug the actual structure of EODHD API responses."""
    
    print("🔍 Debugging EODHD API Response Structure")
    print("=" * 60)
    
    settings = load_settings()
    client = EODHDClient(api_key=settings.eodhd_api_key)
    
    # Test a few companies
    test_symbols = ["AAPL", "MSFT", "GOOGL"]
    
    for symbol in test_symbols:
        print(f"\n📊 Debugging {symbol}...")
        
        try:
            # Get fundamental data
            fundamentals = client.get_json(EODHDRequest(
                endpoint=f"fundamentals/{symbol}.US",
                params={}
            ))
            
            print(f"  Response type: {type(fundamentals)}")
            
            if isinstance(fundamentals, dict):
                print(f"  Top-level keys: {list(fundamentals.keys())}")
                
                # Check quarterly_financials
                quarterly = fundamentals.get("quarterly_financials", {})
                print(f"  quarterly_financials type: {type(quarterly)}")
                
                if isinstance(quarterly, dict):
                    print(f"  quarterly_financials keys: {list(quarterly.keys())}")
                    
                    for key, value in quarterly.items():
                        print(f"    {key}: {type(value)} - {len(value) if isinstance(value, list) else 'N/A'} items")
                        
                        if isinstance(value, list) and value:
                            print(f"      First item keys: {list(value[0].keys()) if isinstance(value[0], dict) else 'Not a dict'}")
                
                # Check annual_financials
                annual = fundamentals.get("annual_financials", {})
                print(f"  annual_financials type: {type(annual)}")
                
                if isinstance(annual, dict):
                    print(f"  annual_financials keys: {list(annual.keys())}")
                
                # Check general info
                general = fundamentals.get("general", {})
                print(f"  General info available: {bool(general)}")
                if general:
                    print(f"    Company name: {general.get('CompanyName', 'N/A')}")
                    print(f"    Sector: {general.get('Sector', 'N/A')}")
                
                # Check highlights
                highlights = fundamentals.get("highlights", {})
                print(f"  Highlights available: {bool(highlights)}")
                if highlights:
                    print(f"    Market cap: {highlights.get('MarketCapitalization', 'N/A')}")
                    print(f"    P/E ratio: {highlights.get('PERatio', 'N/A')}")
                
            else:
                print(f"  Unexpected response format: {fundamentals}")
                
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    print(f"\n🔍 Next, let's check if there are alternative endpoints...")
    
    # Try alternative endpoint format
    for symbol in test_symbols[:1]:  # Just test one
        print(f"\n📊 Testing alternative endpoint for {symbol}...")
        
        try:
            # Try without .US suffix
            fundamentals_alt = client.get_json(EODHDRequest(
                endpoint=f"fundamentals/{symbol}",
                params={}
            ))
            
            print(f"  Alternative endpoint response type: {type(fundamentals_alt)}")
            
            if isinstance(fundamentals_alt, dict):
                quarterly_alt = fundamentals_alt.get("quarterly_financials", {})
                print(f"  Alternative quarterly_financials items: {len(quarterly_alt.get('income_statement', [])) if isinstance(quarterly_alt, dict) else 'N/A'}")
                
        except Exception as e:
            print(f"  ❌ Alternative endpoint error: {e}")

if __name__ == "__main__":
    debug_api_response()
