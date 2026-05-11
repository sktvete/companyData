from __future__ import annotations

import csv
from io import StringIO
import requests


SP500_CONSTITUENTS_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"


def download_sp500_constituents() -> list[dict[str, str]]:
    response = requests.get(SP500_CONSTITUENTS_URL, timeout=60)
    response.raise_for_status()
    reader = csv.DictReader(StringIO(response.text))
    return [
        {
            "symbol": str(row.get("Symbol") or "").strip(),
            "security": str(row.get("Security") or "").strip(),
            "sector": str(row.get("GICS Sector") or "").strip(),
            "cik": str(row.get("CIK") or "").strip(),
        }
        for row in reader
        if row.get("Symbol")
    ]


def sample_sp500_tickers(limit: int = 120) -> list[str]:
    rows = download_sp500_constituents()
    return [row["symbol"] for row in rows[:limit]]
