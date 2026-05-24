"""EODHD REST API client with caching and error handling.

Loads EODHD_API_KEY from environment (or .env file via python-dotenv).
All responses are cached to disk to avoid duplicate API calls.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, timedelta
from typing import Any

import requests

from .cache import DEFAULT_TTL_SECONDS, DiskCache

BASE_URL = "https://eodhd.com/api"
FUNDAMENTALS_VERSION = "v1.1"
REQUEST_TIMEOUT = 30
RATE_LIMIT_SLEEP = 0.25  # seconds between requests


def _load_api_key() -> str:
    """Load EODHD_API_KEY from env, falling back to .env discovery."""
    key = os.environ.get("EODHD_API_KEY", "").strip()
    if key:
        return key

    try:
        from dotenv import find_dotenv, load_dotenv
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path)
            key = os.environ.get("EODHD_API_KEY", "").strip()
            if key:
                return key
    except ImportError:
        pass

    print(
        "ERROR: EODHD_API_KEY not found.\n"
        "Set it as an environment variable or add it to a .env file.\n"
        "  export EODHD_API_KEY=your_key_here",
        file=sys.stderr,
    )
    sys.exit(1)


_TICKER_RE = re.compile(r"^[A-Z0-9._-]+\.[A-Z]+$", re.IGNORECASE)


def normalize_ticker(ticker: str) -> str:
    """Ensure ticker is in SYMBOL.EXCHANGE format. Defaults to .US."""
    ticker = ticker.strip().upper()
    if _TICKER_RE.match(ticker):
        return ticker
    return f"{ticker}.US"


class EodhdClient:
    """Thin wrapper around EODHD REST endpoints with disk caching."""

    def __init__(
        self,
        api_key: str | None = None,
        cache_ttl: int = DEFAULT_TTL_SECONDS,
        cache_dir: str | None = None,
    ) -> None:
        self.api_key = api_key or _load_api_key()
        cache_kwargs: dict[str, Any] = {"ttl_seconds": cache_ttl}
        if cache_dir:
            cache_kwargs["cache_dir"] = cache_dir
        self.cache = DiskCache(**cache_kwargs)
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_SLEEP:
            time.sleep(RATE_LIMIT_SLEEP - elapsed)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Execute a GET request with caching."""
        params = params or {}
        params.setdefault("api_token", self.api_key)
        params.setdefault("fmt", "json")

        cache_key = self.cache.make_key(path, params)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        url = f"{BASE_URL}/{path}"
        self._rate_limit()
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        self._last_request_time = time.time()

        if resp.status_code == 404:
            raise TickerNotFoundError(f"Ticker not found: {path}")
        if resp.status_code == 402:
            raise ApiLimitError("API call limit reached or plan does not cover this endpoint.")
        resp.raise_for_status()

        try:
            data = resp.json()
        except json.JSONDecodeError:
            data = resp.text

        self.cache.set(cache_key, data)
        return data

    # --- Public endpoints ---

    def fundamentals(
        self,
        ticker: str,
        filter_sections: str | None = None,
    ) -> dict[str, Any]:
        """Fetch fundamentals using v1.1 endpoint.

        Args:
            ticker: e.g. "AAPL.US"
            filter_sections: Comma-separated sections like
                "Highlights,Valuation,Financials" to reduce response size.
        """
        ticker = normalize_ticker(ticker)
        path = f"{FUNDAMENTALS_VERSION}/fundamentals/{ticker}"
        params: dict[str, Any] = {}
        if filter_sections:
            params["filter"] = filter_sections
        return self._get(path, params)

    def eod_prices(
        self,
        ticker: str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        period: str = "d",
    ) -> list[dict[str, Any]]:
        """Fetch end-of-day historical prices."""
        ticker = normalize_ticker(ticker)
        if start_date is None:
            start_date = date.today() - timedelta(days=365)
        if end_date is None:
            end_date = date.today()
        params = {
            "from": str(start_date),
            "to": str(end_date),
            "period": period,
        }
        return self._get(f"eod/{ticker}", params)

    def live_price(self, ticker: str) -> dict[str, Any]:
        """Fetch current/recent price snapshot."""
        ticker = normalize_ticker(ticker)
        return self._get(f"real-time/{ticker}")

    def technical(
        self,
        ticker: str,
        function: str,
        period: int = 14,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch server-computed technical indicator."""
        ticker = normalize_ticker(ticker)
        params: dict[str, Any] = {"function": function, "period": period}
        if start_date:
            params["from"] = str(start_date)
        if end_date:
            params["to"] = str(end_date)
        return self._get(f"technical/{ticker}", params)

    def news(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch company news articles."""
        ticker = normalize_ticker(ticker)
        return self._get("news", {"s": ticker, "limit": limit})

    def sentiment(self, ticker: str) -> list[dict[str, Any]]:
        """Fetch aggregated sentiment data."""
        ticker = normalize_ticker(ticker)
        return self._get("sentiments", {"s": ticker})

    def search(self, query: str) -> list[dict[str, Any]]:
        """Search for tickers by name or symbol."""
        return self._get(f"search/{query}")

    def fetch_all_for_analysis(self, ticker: str) -> dict[str, Any]:
        """Convenience method: fetch all data needed for a full stock analysis.

        Returns a dict with keys: fundamentals, eod_prices, live_price, news.
        Each value is the raw EODHD response (or None on error).
        """
        ticker = normalize_ticker(ticker)
        result: dict[str, Any] = {
            "ticker": ticker,
            "fundamentals": None,
            "eod_prices": None,
            "live_price": None,
            "news": None,
        }

        try:
            result["fundamentals"] = self.fundamentals(ticker)
        except Exception as e:
            result["fundamentals_error"] = str(e)

        try:
            result["eod_prices"] = self.eod_prices(ticker)
        except Exception as e:
            result["eod_prices_error"] = str(e)

        try:
            result["live_price"] = self.live_price(ticker)
        except Exception as e:
            result["live_price_error"] = str(e)

        try:
            result["news"] = self.news(ticker, limit=20)
        except Exception as e:
            result["news_error"] = str(e)

        return result


class EodhdError(Exception):
    pass


class TickerNotFoundError(EodhdError):
    pass


class ApiLimitError(EodhdError):
    pass
