from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--tickers", default="AAPL,MSFT,KO")
    args = parser.parse_args()

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["ticker,date,open,high,low,close,volume,currency,adjustment_method"]
    ticker_list = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    base_prices = {ticker: price for ticker, price in zip(ticker_list, [190.0, 420.0, 62.0], strict=False)}
    drifts = {ticker: drift for ticker, drift in zip(ticker_list, [0.14, 0.11, 0.05], strict=False)}
    for ticker in ticker_list:
        close = base_prices.get(ticker, 100.0)
        current_date = date(2024, 5, 1)
        added = 0
        while added < 260:
            if current_date.weekday() < 5:
                close = round(close * (1 + drifts.get(ticker, 0.06) / 252), 4)
                open_price = round(close * 0.996, 4)
                high_price = round(close * 1.01, 4)
                low_price = round(close * 0.99, 4)
                volume = 1000000 + added * 5000
                lines.append(f"{ticker},{current_date.isoformat()},{open_price},{high_price},{low_price},{close},{volume},USD,synthetic_demo")
                added += 1
            current_date += timedelta(days=1)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
