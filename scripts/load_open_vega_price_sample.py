from __future__ import annotations

import argparse
import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
import sys

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings


VEGA_STOCKS_URL = "https://raw.githubusercontent.com/vega/vega-datasets/master/data/stocks.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", required=True)
    parser.add_argument("--tickers", default="AAPL,MSFT,IBM")
    parser.add_argument("--name", default="vega_stocks_sample.csv")
    args = parser.parse_args()

    settings = load_settings()
    tickers = {ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()}
    response = requests.get(VEGA_STOCKS_URL, timeout=60)
    response.raise_for_status()
    reader = csv.DictReader(StringIO(response.text))
    out_rows = ["symbol,trading_date,last_px,currency,source_record_id"]
    kept = 0
    for row in reader:
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in tickers:
            continue
        date_value = datetime.strptime(str(row["date"]), "%b %d %Y").date().isoformat()
        out_rows.append(f"{symbol},{date_value},{row['price']},USD,vega:{symbol}:{date_value}")
        kept += 1
    destination = settings.data_dir / "bronze" / "provider=local_csv" / "dataset=prices_daily" / f"date={args.bronze_date}" / args.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(out_rows) + "\n", encoding="utf-8")
    meta = {
        "price_reality": "real_imported",
        "currency": "USD",
        "adjustment_method": "unadjusted_or_unknown",
        "required_fields": ["ticker", "date", "close"],
        "column_map": {
            "ticker": ["symbol"],
            "date": ["trading_date"],
            "close": ["last_px"],
            "currency": ["currency"],
            "source_record_id": ["source_record_id"],
        },
        "source_name": "vega_datasets",
        "notes": "Monthly close-only open dataset. No adjusted close, OHLC, or volume.",
    }
    destination.with_suffix(destination.suffix + ".meta.json").write_text(__import__("json").dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    print(destination)
    print(f"rows={kept}")


if __name__ == "__main__":
    main()
