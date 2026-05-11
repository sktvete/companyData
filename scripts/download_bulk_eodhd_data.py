#!/usr/bin/env python3

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient
from equity_sorter.providers.eodhd.symbols import list_exchange_symbols_request, parse_symbol_payload
from equity_sorter.providers.eodhd.prices import eod_prices_request, parse_eod_prices_payload
from equity_sorter.providers.eodhd.fundamentals import fundamentals_request
from equity_sorter.providers.eodhd.corporate_actions import splits_request, dividends_request, parse_splits_payload, parse_dividends_payload
from equity_sorter.io_utils import write_json, write_jsonl

def download_bulk_data(settings, exchange_code: str, max_companies: int = None, years_of_history: int = 5):
    """Download comprehensive data for maximum local coverage."""
    
    if not settings.eodhd_api_key:
        raise RuntimeError("EODHD_API_KEY required for bulk download")
    
    client = EODHDClient(settings.eodhd_api_key)
    bronze_date = date.today().isoformat()
    
    print(f"🚀 Starting bulk download for {exchange_code} exchange...")
    
    # Step 1: Download all exchange symbols
    print("📋 Downloading exchange symbols...")
    symbols_request = list_exchange_symbols_request(exchange_code)
    symbols_payload = client.get_json(symbols_request)
    symbols = parse_symbol_payload(symbols_payload, exchange_code)
    
    print(f"✅ Retrieved {len(symbols)} total symbols")
    
    # Step 2: Filter for common stocks (exclude ETFs, ADRs, etc.)
    common_stocks = [
        s for s in symbols 
        if s.type and 'common' in s.type.lower() and not s.delisted
    ]
    
    print(f"📊 Filtered to {len(common_stocks)} common stocks")
    
    # Step 3: Apply limit if specified
    if max_companies:
        common_stocks = common_stocks[:max_companies]
        print(f"🎯 Limited to {len(common_stocks)} companies")
    
    # Step 4: Save symbols metadata
    symbols_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={bronze_date}"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    write_json(symbols_dir / "payload.json", {"request": symbols_request.__dict__, "payload": symbols_payload})
    
    # Step 5: Download data for each company
    success_count = 0
    error_count = 0
    
    for i, symbol in enumerate(common_stocks):
        try:
            print(f"📈 [{i+1}/{len(common_stocks)}] Processing {symbol.code}...")
            
            # Create company directory
            company_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=company_data" / f"exchange={exchange_code}" / f"symbol={symbol.code}" / f"date={bronze_date}"
            company_dir.mkdir(parents=True, exist_ok=True)
            
            # Download prices (5 years of daily data)
            prices_request = eod_prices_request(symbol.code, exchange_code, "d")
            prices_payload = client.get_json(prices_request)
            write_json(company_dir / "prices.json", {"request": prices_request.__dict__, "payload": prices_payload})
            
            # Download fundamentals
            fundamentals_request_obj = fundamentals_request(symbol.code, exchange_code)
            fundamentals_payload = client.get_json(fundamentals_request_obj)
            write_json(company_dir / "fundamentals.json", {"request": fundamentals_request_obj.__dict__, "payload": fundamentals_payload})
            
            # Download corporate actions
            try:
                splits_request_obj = splits_request(symbol.code, exchange_code)
                splits_payload = client.get_json(splits_request_obj)
                write_json(company_dir / "splits.json", {"request": splits_request_obj.__dict__, "payload": splits_payload})
            except Exception as e:
                print(f"  ⚠️  No splits data for {symbol.code}: {e}")
            
            try:
                dividends_request_obj = dividends_request(symbol.code, exchange_code)
                dividends_payload = client.get_json(dividends_request_obj)
                write_json(company_dir / "dividends.json", {"request": dividends_request_obj.__dict__, "payload": dividends_payload})
            except Exception as e:
                print(f"  ⚠️  No dividends data for {symbol.code}: {e}")
            
            success_count += 1
            
            # Rate limiting - be respectful to API
            time.sleep(0.1)
            
        except Exception as e:
            print(f"  ❌ Error processing {symbol.code}: {e}")
            error_count += 1
            continue
    
    print(f"\n🎉 Bulk download completed!")
    print(f"✅ Successfully downloaded: {success_count} companies")
    print(f"❌ Errors: {error_count} companies")
    print(f"📁 Data saved to: {settings.data_dir}")
    
    return {
        "total_symbols": len(symbols),
        "common_stocks": len(common_stocks),
        "successful_downloads": success_count,
        "errors": error_count,
        "data_location": str(settings.data_dir)
    }

def main():
    parser = argparse.ArgumentParser(description="Download bulk EODHD data for maximum local coverage")
    parser.add_argument("--exchange", default="US", help="Exchange code (default: US)")
    parser.add_argument("--max-companies", type=int, help="Maximum number of companies to download")
    parser.add_argument("--years", type=int, default=5, help="Years of price history to download")
    
    args = parser.parse_args()
    
    settings = load_settings()
    
    try:
        result = download_bulk_data(settings, args.exchange, args.max_companies, args.years)
        print(f"\n📊 Summary: {result}")
    except Exception as e:
        print(f"❌ Bulk download failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
