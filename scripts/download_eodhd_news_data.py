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
from equity_sorter.providers.eodhd.news import (
    news_request, sentiments_request, news_word_weights_request,
    parse_news_payload, parse_sentiments_payload, parse_word_weights_payload,
    get_historical_news_params, get_sentiment_summary
)
from equity_sorter.io_utils import write_json, write_jsonl

def download_company_news_data(settings, symbol: str, exchange_code: str, days_back: int = 30):
    """Download comprehensive news and sentiment data for a single company."""
    
    client = EODHDClient(settings.eodhd_api_key)
    bronze_date = date.today().isoformat()
    
    print(f"📰 Downloading news data for {symbol}.{exchange_code}...")
    
    # Create company directory
    company_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=company_data" / f"exchange={exchange_code}" / f"symbol={symbol}" / f"date={bronze_date}"
    company_dir.mkdir(parents=True, exist_ok=True)
    
    company_news_data = {
        "symbol": symbol,
        "exchange": exchange_code,
        "download_timestamp": datetime.now().isoformat(),
        "data_sources": []
    }
    
    # 1. Download historical news
    try:
        news_params = get_historical_news_params(days_back)
        news_request_obj = news_request(
            symbol=f"{symbol}.{exchange_code}",
            from_date=news_params['from_date'],
            to_date=news_params['to_date'],
            limit=100
        )
        news_payload = client.get_json(news_request_obj)
        
        if news_payload:
            parsed_news = parse_news_payload(news_payload)
            write_json(company_dir / "news.json", {"request": news_request_obj.__dict__, "payload": parsed_news})
            company_news_data["data_sources"].append("news")
            print(f"  ✅ News: {len(parsed_news)} articles")
        else:
            print(f"  ⚠️  No news data available for {symbol}")
            
    except Exception as e:
        print(f"  ❌ News download error for {symbol}: {e}")
    
    # 2. Download sentiment data
    try:
        sentiment_request_obj = sentiments_request(
            symbols=[f"{symbol}.{exchange_code}"],
            from_date=news_params['from_date'],
            to_date=news_params['to_date']
        )
        sentiment_payload = client.get_json(sentiment_request_obj)
        
        if sentiment_payload:
            parsed_sentiments = parse_sentiments_payload(sentiment_payload)
            
            # Calculate sentiment summary
            symbol_key = f"{symbol}.{exchange_code}"
            if symbol_key in parsed_sentiments:
                sentiment_summary = get_sentiment_summary(parsed_sentiments[symbol_key])
                parsed_sentiments[symbol_key + "_summary"] = sentiment_summary
            
            write_json(company_dir / "sentiments.json", {"request": sentiment_request_obj.__dict__, "payload": parsed_sentiments})
            company_news_data["data_sources"].append("sentiments")
            print(f"  ✅ Sentiments: {len(parsed_sentiments.get(symbol_key, []))} data points")
        else:
            print(f"  ⚠️  No sentiment data available for {symbol}")
            
    except Exception as e:
        print(f"  ❌ Sentiment download error for {symbol}: {e}")
    
    # 3. Download news word weights
    try:
        word_weights_request_obj = news_word_weights_request(
            symbol=f"{symbol}.{exchange_code}",
            from_date=news_params['from_date'],
            to_date=news_params['to_date']
        )
        word_weights_payload = client.get_json(word_weights_request_obj)
        
        if word_weights_payload:
            parsed_word_weights = parse_word_weights_payload(word_weights_payload)
            write_json(company_dir / "news_word_weights.json", {"request": word_weights_request_obj.__dict__, "payload": parsed_word_weights})
            company_news_data["data_sources"].append("word_weights")
            print(f"  ✅ Word weights: {len(parsed_word_weights.get('word_weights', {}))} words")
        else:
            print(f"  ⚠️  No word weights data available for {symbol}")
            
    except Exception as e:
        print(f"  ❌ Word weights download error for {symbol}: {e}")
    
    # Save company news summary
    write_json(company_dir / "news_summary.json", company_news_data)
    
    return company_news_data

def download_bulk_news_data(settings, exchange_code: str, symbols: List[str], days_back: int = 30):
    """Download news data for multiple companies."""
    
    print(f"🚀 Starting bulk news download for {len(symbols)} companies...")
    print(f"📅 Date range: Last {days_back} days")
    
    success_count = 0
    error_count = 0
    data_summary = {
        "total_attempted": len(symbols),
        "successful_downloads": 0,
        "errors": 0,
        "data_points": {},
        "date_range": get_historical_news_params(days_back)
    }
    
    for i, symbol in enumerate(symbols):
        try:
            print(f"📰 [{i+1}/{len(symbols)}] Processing {symbol}...")
            
            result = download_company_news_data(settings, symbol, exchange_code, days_back)
            
            if result and result.get("data_sources"):
                success_count += 1
                data_summary["successful_downloads"] = success_count
                
                for source in result["data_sources"]:
                    data_summary["data_points"][source] = data_summary["data_points"].get(source, 0) + 1
            else:
                error_count += 1
                data_summary["errors"] = error_count
            
            # Rate limiting
            time.sleep(0.2)
            
        except Exception as e:
            print(f"  ❌ Error processing {symbol}: {e}")
            error_count += 1
            data_summary["errors"] = error_count
            continue
    
    data_summary["errors"] = error_count
    
    print(f"\n🎉 Bulk news download completed!")
    print(f"✅ Successfully downloaded: {success_count} companies")
    print(f"❌ Errors: {error_count} companies")
    print(f"📊 Data points collected:")
    for source, count in data_summary["data_points"].items():
        print(f"  {source}: {count}")
    
    # Save summary
    bronze_date = date.today().isoformat()
    summary_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=download_summary" / f"date={bronze_date}"
    summary_dir.mkdir(parents=True, exist_ok=True)
    write_json(summary_dir / "news_download_summary.json", data_summary)
    
    return data_summary

def download_market_news_data(settings, days_back: int = 7):
    """Download general market news."""
    
    print(f"📰 Downloading market news for last {days_back} days...")
    
    client = EODHDClient(settings.eodhd_api_key)
    bronze_date = date.today().isoformat()
    
    try:
        news_params = get_historical_news_params(days_back)
        news_request_obj = news_request(
            from_date=news_params['from_date'],
            to_date=news_params['to_date'],
            limit=200
        )
        news_payload = client.get_json(news_request_obj)
        
        if news_payload:
            parsed_news = parse_news_payload(news_payload)
            
            # Save market news
            market_news_dir = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=market_news" / f"date={bronze_date}"
            market_news_dir.mkdir(parents=True, exist_ok=True)
            
            write_json(market_news_dir / "market_news.json", {
                "request": news_request_obj.__dict__,
                "payload": parsed_news,
                "download_timestamp": datetime.now().isoformat()
            })
            
            print(f"✅ Market news downloaded: {len(parsed_news)} articles")
            return parsed_news
        else:
            print("⚠️  No market news available")
            return []
            
    except Exception as e:
        print(f"❌ Market news download error: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Download EODHD news and sentiment data")
    parser.add_argument("--exchange", default="US", help="Exchange code (default: US)")
    parser.add_argument("--symbols", nargs="+", help="Specific symbols to download")
    parser.add_argument("--max-symbols", type=int, help="Maximum number of symbols from existing data")
    parser.add_argument("--days-back", type=int, default=30, help="Days of historical news to download")
    parser.add_argument("--market-news", action="store_true", help="Download general market news")
    
    args = parser.parse_args()
    
    settings = load_settings()
    
    if not settings.eodhd_api_key:
        print("❌ EODHD_API_KEY required for news downloads")
        sys.exit(1)
    
    try:
        # Download market news if requested
        if args.market_news:
            download_market_news_data(settings, args.days_back)
        
        # Get symbols to process
        symbols = []
        if args.symbols:
            symbols = args.symbols
        elif args.max_symbols:
            # Load symbols from existing data
            from equity_sorter.io_utils import read_jsonl
            listings_dir = settings.data_dir / "silver" / "listings" / f"exchange={args.exchange}"
            if listings_dir.exists():
                for date_dir in listings_dir.iterdir():
                    if date_dir.is_dir():
                        listings_file = date_dir / "rows.jsonl"
                        if listings_file.exists():
                            listings = read_jsonl(listings_file)
                            symbols = [listing.get('ticker') for listing in listings[:args.max_symbols] if listing.get('ticker')]
                            break
        
        if not symbols:
            print("❌ No symbols specified. Use --symbols or --max-symbols")
            sys.exit(1)
        
        # Download news data
        result = download_bulk_news_data(settings, args.exchange, symbols, args.days_back)
        print(f"\n📊 News Download Summary: {result}")
        
    except Exception as e:
        print(f"❌ News download failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
