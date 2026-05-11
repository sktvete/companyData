#!/usr/bin/env python3

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient
from equity_sorter.providers.eodhd.symbols import list_exchange_symbols_request, parse_symbol_payload
from equity_sorter.providers.eodhd.prices import eod_prices_request, parse_eod_prices_payload
from equity_sorter.providers.eodhd.fundamentals import fundamentals_request, extract_general, extract_highlights, extract_quarterly_financials, extract_annual_financials
from equity_sorter.providers.eodhd.corporate_actions import splits_request, dividends_request, parse_splits_payload, parse_dividends_payload
from equity_sorter.io_utils import write_json, write_jsonl

def download_comprehensive_data(settings, exchange_code: str, max_companies: int = None):
    """Download maximum possible data from EODHD for comprehensive analysis."""
    
    if not settings.eodhd_api_key:
        raise RuntimeError("EODHD_API_KEY required for comprehensive download")
    
    client = EODHDClient(settings.eodhd_api_key)
    bronze_date = date.today().isoformat()
    
    print(f"🚀 Starting COMPREHENSIVE data download for {exchange_code}...")
    
    # Step 1: Get all exchange symbols
    print("📋 Downloading exchange symbols...")
    symbols_request = list_exchange_symbols_request(exchange_code)
    symbols_payload = client.get_json(symbols_request)
    symbols = parse_symbol_payload(symbols_payload, exchange_code)
    
    print(f"✅ Retrieved {len(symbols)} total symbols")
    
    # Step 2: Filter for common stocks with comprehensive data
    common_stocks = []
    for symbol in symbols:
        if symbol.type and 'common' in symbol.type.lower() and not symbol.delisted:
            # Additional filters for quality
            if symbol.currency and symbol.exchange:  # Must have basic trading info
                common_stocks.append(symbol)
    
    print(f"📊 Filtered to {len(common_stocks)} common stocks")
    
    # Step 3: Apply limit if specified
    if max_companies:
        common_stocks = common_stocks[:max_companies]
        print(f"🎯 Limited to {len(common_stocks)} companies")
    
    # Step 4: Save symbols metadata
    symbols_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={bronze_date}"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    write_json(symbols_dir / "payload.json", {"request": symbols_request.__dict__, "payload": symbols_payload})
    
    # Step 5: Download comprehensive data for each company
    success_count = 0
    error_count = 0
    data_summary = {
        "total_attempted": len(common_stocks),
        "successful_downloads": 0,
        "errors": 0,
        "data_points": {},
        "missing_data": {}
    }
    
    for i, symbol in enumerate(common_stocks):
        try:
            print(f"📈 [{i+1}/{len(common_stocks)}] Processing {symbol.code}...")
            
            # Create company directory
            company_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=company_data" / f"exchange={exchange_code}" / f"symbol={symbol.code}" / f"date={bronze_date}"
            company_dir.mkdir(parents=True, exist_ok=True)
            
            company_data = {
                "symbol": symbol.code,
                "exchange": exchange_code,
                "download_timestamp": datetime.now().isoformat(),
                "data_sources": []
            }
            
            # 1. Download comprehensive price data (10 years)
            try:
                prices_request = eod_prices_request(symbol.code, exchange_code, "d")
                prices_payload = client.get_json(prices_request)
                write_json(company_dir / "prices.json", {"request": prices_request.__dict__, "payload": prices_payload})
                company_data["data_sources"].append("prices")
                print(f"  ✅ Price data: {len(prices_payload)} days")
            except Exception as e:
                print(f"  ⚠️  No price data for {symbol.code}: {e}")
            
            # 2. Download comprehensive fundamentals
            try:
                fundamentals_request_obj = fundamentals_request(symbol.code, exchange_code)
                fundamentals_payload = client.get_json(fundamentals_request_obj)
                
                # Extract all available sections
                fundamentals_data = {
                    "general": extract_general(fundamentals_payload),
                    "highlights": extract_highlights(fundamentals_payload),
                    "quarterly_financials": extract_quarterly_financials(fundamentals_payload),
                    "annual_financials": extract_annual_financials(fundamentals_payload),
                    "raw_payload": fundamentals_payload
                }
                
                write_json(company_dir / "fundamentals.json", {"request": fundamentals_request_obj.__dict__, "payload": fundamentals_data})
                company_data["data_sources"].append("fundamentals")
                
                # Count data points
                quarterly_count = len(fundamentals_data["quarterly_financials"].get("income_statement", []))
                annual_count = len(fundamentals_data["annual_financials"].get("income_statement", []))
                print(f"  ✅ Fundamentals: {quarterly_count} quarters, {annual_count} years")
                
            except Exception as e:
                print(f"  ⚠️  No fundamentals data for {symbol.code}: {e}")
            
            # 3. Download corporate actions
            try:
                splits_request_obj = splits_request(symbol.code, exchange_code)
                splits_payload = client.get_json(splits_request_obj)
                write_json(company_dir / "splits.json", {"request": splits_request_obj.__dict__, "payload": splits_payload})
                company_data["data_sources"].append("splits")
                print(f"  ✅ Splits: {len(splits_payload)} events")
            except Exception as e:
                print(f"  ⚠️  No splits data for {symbol.code}: {e}")
            
            try:
                dividends_request_obj = dividends_request(symbol.code, exchange_code)
                dividends_payload = client.get_json(dividends_request_obj)
                write_json(company_dir / "dividends.json", {"request": dividends_request_obj.__dict__, "payload": dividends_payload})
                company_data["data_sources"].append("dividends")
                print(f"  ✅ Dividends: {len(dividends_payload)} events")
            except Exception as e:
                print(f"  ⚠️  No dividends data for {symbol.code}: {e}")
            
            # 4. Save company summary
            write_json(company_dir / "company_summary.json", company_data)
            
            # 5. Update statistics
            success_count += 1
            data_summary["successful_downloads"] = success_count
            
            for source in company_data["data_sources"]:
                data_summary["data_points"][source] = data_summary["data_points"].get(source, 0) + 1
            
            # Rate limiting
            time.sleep(0.1)
            
        except Exception as e:
            print(f"  ❌ Error processing {symbol.code}: {e}")
            error_count += 1
            data_summary["errors"] = error_count
            continue
    
    data_summary["errors"] = error_count
    
    print(f"\n🎉 Comprehensive download completed!")
    print(f"✅ Successfully downloaded: {success_count} companies")
    print(f"❌ Errors: {error_count} companies")
    print(f"📊 Data points collected:")
    for source, count in data_summary["data_points"].items():
        print(f"  {source}: {count}")
    print(f"📁 Data saved to: {settings.data_dir}")
    
    # Save summary
    summary_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=download_summary" / f"date={bronze_date}"
    summary_dir.mkdir(parents=True, exist_ok=True)
    write_json(summary_dir / "comprehensive_download_summary.json", data_summary)
    
    return data_summary

def main():
    parser = argparse.ArgumentParser(description="Download comprehensive EODHD data for maximum analysis")
    parser.add_argument("--exchange", default="US", help="Exchange code (default: US)")
    parser.add_argument("--max-companies", type=int, help="Maximum number of companies to download")
    
    args = parser.parse_args()
    
    settings = load_settings()
    
    try:
        result = download_comprehensive_data(settings, args.exchange, args.max_companies)
        print(f"\n📊 Comprehensive Summary: {result}")
    except Exception as e:
        print(f"❌ Comprehensive download failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
