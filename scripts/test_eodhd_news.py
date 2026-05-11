#!/usr/bin/env python3

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.eodhd.client import EODHDClient, EODHDRequest

def test_eodhd_news_capabilities():
    """Test EODHD news and sentiment API capabilities."""
    
    settings = load_settings()
    if not settings.eodhd_api_key:
        print("❌ EODHD_API_KEY not configured")
        return False
    
    client = EODHDClient(settings.eodhd_api_key)
    
    print("🔍 Testing EODHD News and Sentiment Capabilities")
    print("=" * 60)
    
    # Test 1: General market news
    print("\n📰 Testing General Market News...")
    try:
        news_request = EODHDRequest(endpoint='news', params={})
        print(f"   Request: {news_request.endpoint}")
        
        news_payload = client.get_json(news_request)
        print(f"   ✅ Success! Response type: {type(news_payload)}")
        
        if isinstance(news_payload, list):
            print(f"   📊 News articles count: {len(news_payload)}")
            if news_payload:
                first_article = news_payload[0]
                print(f"   🔍 Sample article keys: {list(first_article.keys())}")
                print(f"   📝 Sample title: {first_article.get('title', 'N/A')[:100]}...")
                print(f"   📅 Sample date: {first_article.get('date', 'N/A')}")
        elif isinstance(news_payload, dict):
            print(f"   🔍 Response keys: {list(news_payload.keys())}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 2: Company-specific news
    print("\n🏢 Testing Company-Specific News (AAPL)...")
    try:
        aapl_news_request = EODHDRequest(endpoint='news', params={'s': 'AAPL.US'})
        print(f"   Request: {aapl_news_request.endpoint} with params {aapl_news_request.params}")
        
        aapl_news_payload = client.get_json(aapl_news_request)
        print(f"   ✅ Success! Response type: {type(aapl_news_payload)}")
        
        if isinstance(aapl_news_payload, list):
            print(f"   📊 AAPL news articles count: {len(aapl_news_payload)}")
            if aapl_news_payload:
                first_article = aapl_news_payload[0]
                print(f"   🔍 Sample article keys: {list(first_article.keys())}")
                print(f"   📝 Sample title: {first_article.get('title', 'N/A')[:100]}...")
                print(f"   📅 Sample date: {first_article.get('date', 'N/A')}")
        elif isinstance(aapl_news_payload, dict):
            print(f"   🔍 Response keys: {list(aapl_news_payload.keys())}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 3: Sentiment data
    print("\n📊 Testing Sentiment Data...")
    try:
        sentiment_request = EODHDRequest(endpoint='sentiments', params={'s': 'AAPL.US'})
        print(f"   Request: {sentiment_request.endpoint} with params {sentiment_request.params}")
        
        sentiment_payload = client.get_json(sentiment_request)
        print(f"   ✅ Success! Response type: {type(sentiment_payload)}")
        
        if isinstance(sentiment_payload, dict):
            print(f"   🔍 Sentiment data keys: {list(sentiment_payload.keys())}")
            for key, value in sentiment_payload.items():
                if isinstance(value, (int, float)):
                    print(f"      {key}: {value}")
                elif isinstance(value, str) and len(value) < 100:
                    print(f"      {key}: {value}")
                elif isinstance(value, list):
                    print(f"      {key}: list with {len(value)} items")
                else:
                    print(f"      {key}: {type(value)}")
        elif isinstance(sentiment_payload, list):
            print(f"   📊 Sentiment data count: {len(sentiment_payload)}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Test 4: Historical news with date range
    print("\n📅 Testing Historical News with Date Range...")
    try:
        from datetime import datetime, timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        historical_news_request = EODHDRequest(endpoint='news', params={
            's': 'AAPL.US',
            'from': start_date.strftime('%Y-%m-%d'),
            'to': end_date.strftime('%Y-%m-%d')
        })
        print(f"   Request: {historical_news_request.endpoint} with date range")
        print(f"   From: {start_date.strftime('%Y-%m-%d')} To: {end_date.strftime('%Y-%m-%d')}")
        
        historical_payload = client.get_json(historical_news_request)
        print(f"   ✅ Success! Response type: {type(historical_payload)}")
        
        if isinstance(historical_payload, list):
            print(f"   📊 Historical news count: {len(historical_payload)}")
            if historical_payload:
                # Check date range
                dates = [article.get('date') for article in historical_payload if article.get('date')]
                if dates:
                    print(f"   📅 Date range: {min(dates)} to {max(dates)}")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 60)
    print("✅ EODHD News Capabilities Test Completed")
    return True

if __name__ == "__main__":
    test_eodhd_news_capabilities()
