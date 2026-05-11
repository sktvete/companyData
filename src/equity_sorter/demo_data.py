from __future__ import annotations

from typing import Any


def build_demo_fixture() -> dict[str, Any]:
    return {
        "symbols": {
            "US": [
                {"Code": "ALFA", "Name": "Alpha Holdings", "Country": "USA", "Currency": "USD", "Type": "Common Stock", "ISIN": "US0000000001", "Delisted": 0},
                {"Code": "BETA", "Name": "Beta Industries", "Country": "USA", "Currency": "USD", "Type": "Common Stock", "ISIN": "US0000000002", "Delisted": 0},
                {"Code": "GAMM", "Name": "Gamma Retail", "Country": "USA", "Currency": "USD", "Type": "Common Stock", "ISIN": "US0000000003", "Delisted": 0},
            ],
            "OL": [
                {"Code": "NORD", "Name": "Nordic Energy", "Country": "Norway", "Currency": "NOK", "Type": "Common Stock", "ISIN": "NO0000000001", "Delisted": 0},
                {"Code": "FJRD", "Name": "Fjord Shipping", "Country": "Norway", "Currency": "NOK", "Type": "Common Stock", "ISIN": "NO0000000002", "Delisted": 0},
            ],
        },
        "prices": {
            "US": {
                "ALFA": _daily_prices("2024-01-31", 20.0, 0.10, 260),
                "BETA": _daily_prices("2024-01-31", 12.0, 0.03, 260),
                "GAMM": _daily_prices("2024-01-31", 18.0, -0.02, 260),
            },
            "OL": {
                "NORD": _daily_prices("2024-01-31", 140.0, 0.05, 260),
                "FJRD": _daily_prices("2024-01-31", 80.0, -0.01, 260),
            },
        },
        "fundamentals": {
            "US": {
                "ALFA": _fundamentals_payload("USD", "Technology", [
                    _quarter("2025-03-31", 2400, 1080, 520, 560, 400, 2.4, 900, 4200, 700, 2100, 100, 510, -80, 430),
                    _quarter("2024-12-31", 2300, 1035, 500, 540, 380, 2.3, 860, 4100, 720, 2040, 100, 500, -75, 425),
                    _quarter("2024-09-30", 2250, 1010, 470, 510, 360, 2.2, 840, 3980, 760, 1980, 100, 480, -72, 408),
                    _quarter("2024-06-30", 2200, 990, 450, 490, 340, 2.1, 820, 3900, 780, 1940, 100, 470, -70, 400),
                ]),
                "BETA": _fundamentals_payload("USD", "Industrials", [
                    _quarter("2025-03-31", 1800, 540, 190, 220, 130, 1.1, 300, 3600, 1100, 1200, 140, 210, -120, 90),
                    _quarter("2024-12-31", 1760, 528, 180, 210, 120, 1.0, 290, 3550, 1120, 1180, 140, 205, -118, 87),
                    _quarter("2024-09-30", 1710, 500, 170, 200, 110, 0.9, 280, 3500, 1150, 1160, 140, 200, -115, 85),
                    _quarter("2024-06-30", 1680, 490, 160, 190, 105, 0.9, 275, 3480, 1180, 1150, 140, 198, -112, 86),
                ]),
                "GAMM": _fundamentals_payload("USD", "Consumer Defensive", [
                    _quarter("2025-03-31", 1500, 390, 90, 110, -20, -0.2, 80, 2600, 900, 500, 160, 60, -70, -10),
                    _quarter("2024-12-31", 1510, 392, 92, 112, -15, -0.1, 85, 2620, 910, 520, 158, 62, -68, -6),
                    _quarter("2024-09-30", 1520, 395, 95, 115, -10, -0.1, 88, 2640, 920, 540, 156, 65, -67, -2),
                    _quarter("2024-06-30", 1530, 400, 100, 120, -8, -0.1, 92, 2660, 930, 560, 154, 68, -65, 3),
                ]),
            },
            "OL": {
                "NORD": _fundamentals_payload("NOK", "Energy", [
                    _quarter("2025-03-31", 3200, 1600, 650, 700, 500, 3.4, 1400, 7200, 1500, 3400, 85, 720, -130, 590),
                    _quarter("2024-12-31", 3100, 1550, 620, 680, 480, 3.2, 1380, 7100, 1520, 3340, 85, 710, -128, 582),
                    _quarter("2024-09-30", 3050, 1500, 610, 670, 470, 3.1, 1350, 7050, 1550, 3300, 85, 700, -125, 575),
                    _quarter("2024-06-30", 3000, 1480, 600, 660, 460, 3.0, 1320, 7000, 1580, 3260, 85, 690, -124, 566),
                ]),
                "FJRD": _fundamentals_payload("NOK", "Industrials", [
                    _quarter("2025-03-31", 2100, 750, 220, 260, 120, 1.0, 400, 5400, 1800, 1500, 120, 260, -200, 60),
                    _quarter("2024-12-31", 2080, 748, 218, 258, 115, 1.0, 395, 5380, 1810, 1485, 120, 255, -198, 57),
                    _quarter("2024-09-30", 2050, 735, 212, 250, 108, 0.9, 390, 5350, 1830, 1470, 120, 250, -196, 54),
                    _quarter("2024-06-30", 2020, 720, 205, 242, 100, 0.8, 385, 5320, 1850, 1455, 120, 246, -194, 52),
                ]),
            },
        },
        "splits": {"US": {"ALFA": [], "BETA": [], "GAMM": []}, "OL": {"NORD": [], "FJRD": []}},
        "dividends": {"US": {"ALFA": [{"date": "2025-03-15", "value": 0.2}], "BETA": [{"date": "2025-03-15", "value": 0.1}], "GAMM": []}, "OL": {"NORD": [{"date": "2025-03-15", "value": 1.4}], "FJRD": []}},
    }


def _quarter(
    date_value: str,
    revenue: float,
    gross_profit: float,
    operating_income: float,
    ebit: float,
    net_income: float,
    eps: float,
    cash: float,
    total_assets: float,
    total_debt: float,
    total_equity: float,
    shares: float,
    ocf: float,
    capex: float,
    fcf: float,
) -> dict[str, Any]:
    return {
        "date": date_value,
        "filing_date": _filing_date_for(date_value),
        "accepted_date": _filing_date_for(date_value) + "T08:00:00Z",
        "totalRevenue": revenue,
        "grossProfit": gross_profit,
        "operatingIncome": operating_income,
        "ebit": ebit,
        "ebitda": ebit + 20,
        "netIncome": net_income,
        "eps": eps,
        "cashAndShortTermInvestments": cash,
        "cashAndCashEquivalents": cash,
        "totalAssets": total_assets,
        "totalDebt": total_debt,
        "totalEquity": total_equity,
        "totalStockholderEquity": total_equity,
        "commonStockSharesOutstanding": shares,
        "totalCashFromOperatingActivities": ocf,
        "capitalExpenditures": capex,
        "freeCashFlow": fcf,
    }


def _fundamentals_payload(currency: str, sector: str, quarters: list[dict[str, Any]]) -> dict[str, Any]:
    quarterly = {row["date"]: row for row in quarters}
    return {
        "General": {"CurrencyCode": currency, "Sector": sector},
        "Financials": {
            "Income_Statement": {"quarterly": quarterly},
            "Balance_Sheet": {"quarterly": quarterly},
            "Cash_Flow": {"quarterly": quarterly},
        },
    }


def _daily_prices(start_date: str, start_price: float, drift: float, count: int) -> list[dict[str, Any]]:
    from datetime import date, timedelta

    rows: list[dict[str, Any]] = []
    current_date = date.fromisoformat(start_date)
    close = start_price
    added = 0
    while added < count:
        if current_date.weekday() < 5:
            close = round(close * (1 + drift / 252), 4)
            open_price = round(close * 0.995, 4)
            high_price = round(close * 1.01, 4)
            low_price = round(close * 0.99, 4)
            rows.append({
                "date": current_date.isoformat(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close,
                "adjusted_close": close,
                "volume": 1000000 + added * 1000,
            })
            added += 1
        current_date += timedelta(days=1)
    return rows


def _filing_date_for(period_end: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(period_end) + timedelta(days=35)).isoformat()
