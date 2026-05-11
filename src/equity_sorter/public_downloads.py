from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import time
import requests

from equity_sorter.config import Settings
from equity_sorter.io_utils import write_json
from equity_sorter.providers.sec_edgar.client import SECClient
from equity_sorter.providers.sec_edgar.companyfacts import companyfacts_request
from equity_sorter.providers.sec_edgar.submissions import submissions_request
from equity_sorter.providers.sec_edgar.tickers import company_tickers_request, parse_company_tickers
from equity_sorter.providers.nasdaq_trader.symbols import parse_nasdaq_trader_symbols


NASDAQ_TRADER_URLS = {
    "nasdaqlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "otherlisted": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}


@dataclass(frozen=True)
class DownloadSummary:
    tickers: list[str]
    cik_count: int
    bronze_date: str
    price_failures: list[str]


def download_public_us_sample(settings: Settings, bronze_date: str, tickers: list[str]) -> DownloadSummary:
    return download_public_us_sample_with_options(settings, bronze_date, tickers, download_prices=True)


def download_public_us_sample_with_options(settings: Settings, bronze_date: str, tickers: list[str], download_prices: bool) -> DownloadSummary:
    sec_client = SECClient(user_agent=settings.sec_user_agent)
    ticker_map_payload = sec_client.get_json(company_tickers_request())
    write_json(
        settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=company_tickers" / f"date={bronze_date}" / "payload.json",
        ticker_map_payload,
    )
    ticker_rows = parse_company_tickers(ticker_map_payload)
    ticker_to_cik = _build_ticker_lookup(ticker_rows)

    _download_nasdaq_trader_files(settings, bronze_date)

    selected_ciks: list[str] = []
    price_failures: list[str] = []
    fundamentals_failures: list[str] = []
    for ticker in [value.upper() for value in tickers]:
        cik = ticker_to_cik.get(ticker)
        if not cik:
            continue
        try:
            submissions_payload = sec_client.get_json(submissions_request(cik))
            companyfacts_payload = sec_client.get_json(companyfacts_request(cik))
        except requests.HTTPError as exc:
            fundamentals_failures.append(f"{ticker}:{cik}:{exc.response.status_code if exc.response else 'http_error'}")
            time.sleep(0.12)
            continue
        selected_ciks.append(cik)
        write_json(
            settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=submissions" / f"date={bronze_date}" / f"{cik}.json",
            submissions_payload,
        )
        write_json(
            settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=companyfacts" / f"date={bronze_date}" / f"{cik}.json",
            companyfacts_payload,
        )
        time.sleep(0.12)
        if download_prices:
            try:
                _download_stooq_price(settings, bronze_date, ticker)
            except RuntimeError as exc:
                price_failures.append(f"{ticker}: {exc}")

    return DownloadSummary(
        tickers=[value.upper() for value in tickers],
        cik_count=len(selected_ciks),
        bronze_date=bronze_date,
        price_failures=price_failures + fundamentals_failures,
    )


def download_commonstock_sec_sample(settings: Settings, bronze_date: str, limit: int, download_prices: bool = False) -> DownloadSummary:
    sec_client = SECClient(user_agent=settings.sec_user_agent)
    ticker_map_payload = sec_client.get_json(company_tickers_request())
    write_json(
        settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=company_tickers" / f"date={bronze_date}" / "payload.json",
        ticker_map_payload,
    )
    ticker_rows = parse_company_tickers(ticker_map_payload)
    ticker_to_cik = _build_ticker_lookup(ticker_rows)
    _download_nasdaq_trader_files(settings, bronze_date)
    commonstock_tickers = _select_commonstock_tickers(settings, bronze_date, ticker_to_cik, limit)
    return download_public_us_sample_with_options(settings, bronze_date, commonstock_tickers, download_prices=download_prices)


def _build_ticker_lookup(ticker_rows: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in ticker_rows:
        ticker = str(row["ticker"]).upper()
        cik = row["cik"]
        lookup[ticker] = cik
        lookup[ticker.replace("-", ".")] = cik
        lookup[ticker.replace(".", "-")] = cik
    return lookup


def _select_commonstock_tickers(settings: Settings, bronze_date: str, ticker_to_cik: dict[str, str], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for dataset in ["nasdaqlisted", "otherlisted"]:
        path = settings.data_dir / "bronze" / "provider=free_us" / f"dataset={dataset}" / f"date={bronze_date}" / f"{dataset}.txt"
        rows = parse_nasdaq_trader_symbols(path.read_text(encoding="utf-8"))
        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            name = str(row.get("name") or "")
            if ticker in seen or ticker not in ticker_to_cik:
                continue
            if _is_common_stock_name(name):
                selected.append(ticker)
                seen.add(ticker)
            if len(selected) >= limit:
                return selected
    return selected


def _is_common_stock_name(name: str) -> bool:
    upper_name = name.upper()
    blocked_tokens = ["ETF", "TRUST", "FUND", "PREFERRED", "NOTE", "WARRANT", "UNIT", "RIGHTS", "ADR", "ADS", "DEPOSITARY"]
    return not any(token in upper_name for token in blocked_tokens)


def _download_nasdaq_trader_files(settings: Settings, bronze_date: str) -> None:
    session = requests.Session()
    for dataset, url in NASDAQ_TRADER_URLS.items():
        response = session.get(url, timeout=60)
        response.raise_for_status()
        path = settings.data_dir / "bronze" / "provider=free_us" / f"dataset={dataset}" / f"date={bronze_date}" / f"{dataset}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")


def _download_stooq_price(settings: Settings, bronze_date: str, ticker: str) -> None:
    session = requests.Session()
    url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"
    if settings.stooq_api_key:
        url += f"&apikey={settings.stooq_api_key}"
    response = session.get(url, timeout=60)
    response.raise_for_status()
    if "get_apikey" in response.text.lower() or "Get your apikey" in response.text:
        raise RuntimeError(
            "Stooq historical download requires an API key/captcha. Set STOOQ_API_KEY or use a local CSV/manual fallback."
        )
    path = settings.data_dir / "bronze" / "provider=stooq" / "dataset=prices_daily" / f"date={bronze_date}" / f"{ticker}.US.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
