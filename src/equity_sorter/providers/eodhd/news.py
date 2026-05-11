from __future__ import annotations

from typing import Any
from datetime import date, timedelta

from .client import EODHDRequest


def news_request(symbol: str | None = None, tag: str | None = None, 
                offset: int = 0, limit: int = 50, 
                from_date: str | None = None, to_date: str | None = None) -> EODHDRequest:
    """Create a request for financial news."""
    params = {
        'offset': offset,
        'limit': limit,
        'fmt': 'json'
    }
    
    if symbol:
        params['s'] = symbol
    if tag:
        params['t'] = tag
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date
    
    return EODHDRequest(endpoint='news', params=params)


def sentiments_request(symbols: list[str], from_date: str | None = None, 
                      to_date: str | None = None) -> EODHDRequest:
    """Create a request for sentiment data."""
    params = {
        's': ','.join(symbols),
        'fmt': 'json'
    }
    
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date
    
    return EODHDRequest(endpoint='sentiments', params=params)


def news_word_weights_request(symbol: str, from_date: str | None = None,
                             to_date: str | None = None) -> EODHDRequest:
    """Create a request for news word weights."""
    params = {
        's': symbol,
        'fmt': 'json'
    }
    
    if from_date:
        params['from'] = from_date
    if to_date:
        params['to'] = to_date
    
    return EODHDRequest(endpoint='news-word-weights', params=params)


def parse_news_payload(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse news API response."""
    parsed_news = []
    
    for article in payload:
        parsed_article = {
            'title': article.get('title'),
            'content': article.get('content'),
            'description': article.get('description'),
            'source': article.get('source'),
            'author': article.get('author'),
            'url': article.get('url'),
            'image_url': article.get('image_url'),
            'published_date': article.get('date'),
            'symbols': article.get('symbols', []),
            'tags': article.get('tags', []),
            'sentiment': article.get('sentiment'),
            'language': article.get('language')
        }
        parsed_news.append(parsed_article)
    
    return parsed_news


def parse_sentiments_payload(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Parse sentiment API response."""
    parsed_sentiments = {}
    
    for symbol, sentiment_data in payload.items():
        if isinstance(sentiment_data, list):
            parsed_data = []
            for data_point in sentiment_data:
                parsed_point = {
                    'date': data_point.get('date'),
                    'sentiment_score': data_point.get('normalized'),  # -1 to +1 scale
                    'mention_count': data_point.get('count'),
                    'raw_score': data_point.get('score')
                }
                parsed_data.append(parsed_point)
            parsed_sentiments[symbol] = parsed_data
    
    return parsed_sentiments


def parse_word_weights_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse news word weights response."""
    return {
        'symbol': payload.get('symbol'),
        'date': payload.get('date'),
        'word_weights': payload.get('word_weights', {}),
        'total_words': payload.get('total_words', 0),
        'top_words': payload.get('top_words', [])
    }


def get_historical_news_params(days_back: int = 30) -> dict[str, str]:
    """Get parameters for historical news request."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)
    
    return {
        'from_date': start_date.isoformat(),
        'to_date': end_date.isoformat()
    }


def get_sentiment_summary(sentiment_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate sentiment summary from sentiment data."""
    if not sentiment_data:
        return {
            'average_sentiment': 0.0,
            'sentiment_trend': 'neutral',
            'total_mentions': 0,
            'positive_days': 0,
            'negative_days': 0,
            'neutral_days': 0
        }
    
    # Calculate average sentiment
    total_sentiment = sum(point['sentiment_score'] for point in sentiment_data)
    average_sentiment = total_sentiment / len(sentiment_data)
    
    # Count sentiment categories
    positive_days = sum(1 for point in sentiment_data if point['sentiment_score'] > 0.1)
    negative_days = sum(1 for point in sentiment_data if point['sentiment_score'] < -0.1)
    neutral_days = len(sentiment_data) - positive_days - negative_days
    
    # Determine trend
    if len(sentiment_data) >= 2:
        recent_sentiment = sentiment_data[-1]['sentiment_score']
        older_sentiment = sentiment_data[0]['sentiment_score']
        if recent_sentiment > older_sentiment + 0.1:
            trend = 'improving'
        elif recent_sentiment < older_sentiment - 0.1:
            trend = 'declining'
        else:
            trend = 'stable'
    else:
        trend = 'insufficient_data'
    
    return {
        'average_sentiment': round(average_sentiment, 4),
        'sentiment_trend': trend,
        'total_mentions': sum(point['mention_count'] for point in sentiment_data),
        'positive_days': positive_days,
        'negative_days': negative_days,
        'neutral_days': neutral_days
    }
