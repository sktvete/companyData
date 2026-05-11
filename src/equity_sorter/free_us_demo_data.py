from __future__ import annotations

from typing import Any


def build_free_us_demo_fixture() -> dict[str, Any]:
    return {
        "nasdaq_trader_symbols": "Symbol|Security Name|Exchange|ETF|Test Issue|Round Lot Size\nALFA|Alpha Holdings|NASDAQ|N|N|100\nBETA|Beta Industries|NYSE|N|N|100\nGAMM|Gamma Retail|NASDAQ|N|N|100\nFile Creation Time|20260509||||\n",
        "sec_submissions": {
            "0000001001": _submission("0000001001", "Alpha Holdings", "ALFA", "NASDAQ", "Technology"),
            "0000001002": _submission("0000001002", "Beta Industries", "BETA", "NYSE", "Industrials"),
            "0000001003": _submission("0000001003", "Gamma Retail", "GAMM", "NASDAQ", "Consumer Defensive"),
        },
        "sec_companyfacts": {
            "0000001001": _companyfacts("0000001001", "Alpha Holdings", "ALFA", [
                _sec_quarter("2024-06-30", "2024-08-05", 2200, 990, 450, 340, 820, 3900, 780, 1940, 100, 470, -70),
                _sec_quarter("2024-09-30", "2024-11-05", 2250, 1010, 470, 360, 840, 3980, 760, 1980, 100, 480, -72),
                _sec_quarter("2024-12-31", "2025-02-05", 2300, 1035, 500, 380, 860, 4100, 720, 2040, 100, 500, -75),
                _sec_quarter("2025-03-31", "2025-05-05", 2400, 1080, 520, 400, 900, 4200, 700, 2100, 100, 510, -80),
            ]),
            "0000001002": _companyfacts("0000001002", "Beta Industries", "BETA", [
                _sec_quarter("2024-06-30", "2024-08-08", 1680, 490, 160, 105, 275, 3480, 1180, 1150, 140, 198, -112),
                _sec_quarter("2024-09-30", "2024-11-08", 1710, 500, 170, 110, 280, 3500, 1150, 1160, 140, 200, -115),
                _sec_quarter("2024-12-31", "2025-02-08", 1760, 528, 180, 120, 290, 3550, 1120, 1180, 140, 205, -118),
                _sec_quarter("2025-03-31", "2025-05-08", 1800, 540, 190, 130, 300, 3600, 1100, 1200, 140, 210, -120),
            ]),
            "0000001003": _companyfacts("0000001003", "Gamma Retail", "GAMM", [
                _sec_quarter("2024-06-30", "2024-08-11", 1530, 400, 100, -8, 92, 2660, 930, 560, 154, 68, -65),
                _sec_quarter("2024-09-30", "2024-11-11", 1520, 395, 95, -10, 88, 2640, 920, 540, 156, 65, -67),
                _sec_quarter("2024-12-31", "2025-02-11", 1510, 392, 92, -15, 85, 2620, 910, 520, 158, 62, -68),
                _sec_quarter("2025-03-31", "2025-05-11", 1500, 390, 90, -20, 80, 2600, 900, 500, 160, 60, -70),
            ]),
        },
        "stooq_prices": {
            "ALFA.US": _stooq_csv("2024-01-31", 20.0, 0.10, 260),
            "BETA.US": _stooq_csv("2024-01-31", 12.0, 0.03, 260),
            "GAMM.US": _stooq_csv("2024-01-31", 18.0, -0.02, 260),
        },
    }


def _submission(cik: str, name: str, ticker: str, exchange: str, sic_description: str) -> dict[str, Any]:
    return {
        "cik": cik,
        "name": name,
        "tickers": [ticker],
        "exchanges": [exchange],
        "sicDescription": sic_description,
    }


def _companyfacts(cik: str, name: str, ticker: str, quarters: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cik": cik,
        "entityName": name,
        "tickers": [ticker],
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [_fact_row(q, "revenue") for q in quarters]}},
                "GrossProfit": {"units": {"USD": [_fact_row(q, "gross_profit") for q in quarters]}},
                "OperatingIncomeLoss": {"units": {"USD": [_fact_row(q, "operating_income") for q in quarters]}},
                "NetIncomeLoss": {"units": {"USD": [_fact_row(q, "net_income") for q in quarters]}},
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [_fact_row(q, "cash_and_equivalents") for q in quarters]}},
                "Assets": {"units": {"USD": [_fact_row(q, "total_assets") for q in quarters]}},
                "LongTermDebt": {"units": {"USD": [_fact_row(q, "total_debt") for q in quarters]}},
                "StockholdersEquity": {"units": {"USD": [_fact_row(q, "total_equity") for q in quarters]}},
                "WeightedAverageNumberOfSharesOutstandingBasic": {"units": {"shares": [_fact_row(q, "shares_basic") for q in quarters]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_fact_row(q, "operating_cash_flow") for q in quarters]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [_fact_row(q, "capex") for q in quarters]}},
            }
        },
    }


def _sec_quarter(end: str, filed: str, revenue: float, gross_profit: float, operating_income: float, net_income: float, cash: float, total_assets: float, total_debt: float, total_equity: float, shares_basic: float, operating_cash_flow: float, capex: float) -> dict[str, Any]:
    return {
        "end": end,
        "filed": filed,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "cash_and_equivalents": cash,
        "total_assets": total_assets,
        "total_debt": total_debt,
        "total_equity": total_equity,
        "shares_basic": shares_basic,
        "operating_cash_flow": operating_cash_flow,
        "capex": capex,
    }


def _fact_row(quarter: dict[str, Any], field: str) -> dict[str, Any]:
    end = quarter["end"]
    month = int(end[5:7])
    quarter_number = ((month - 1) // 3) + 1
    return {
        "end": end,
        "filed": quarter["filed"],
        "fy": int(end[:4]),
        "fp": f"Q{quarter_number}",
        "form": "10-Q",
        "frame": f"CY{end[:4]}Q{quarter_number}",
        "accn": f"{end.replace('-', '')}-{field}",
        "val": quarter[field],
    }


def _stooq_csv(start_date: str, start_price: float, drift: float, count: int) -> str:
    from datetime import date, timedelta

    rows = ["Date,Open,High,Low,Close,Volume"]
    current_date = date.fromisoformat(start_date)
    close = start_price
    added = 0
    while added < count:
        if current_date.weekday() < 5:
            close = round(close * (1 + drift / 252), 4)
            open_price = round(close * 0.995, 4)
            high_price = round(close * 1.01, 4)
            low_price = round(close * 0.99, 4)
            rows.append(f"{current_date.isoformat()},{open_price},{high_price},{low_price},{close},{1000000 + added * 1000}")
            added += 1
        current_date += timedelta(days=1)
    return "\n".join(rows) + "\n"
