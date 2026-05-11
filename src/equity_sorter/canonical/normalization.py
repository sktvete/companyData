from __future__ import annotations

from collections import defaultdict
from typing import Any

from equity_sorter.canonical.ids import (
    make_company_id,
    make_identifier_id,
    make_listing_id,
    make_security_id,
    normalize_name,
)
from equity_sorter.canonical.schemas import Company, FundamentalsQuarterly, Identifier, Listing, Security
from equity_sorter.canonical.schemas import CorporateAction, PriceDaily
from equity_sorter.io_utils import utc_now_iso
from equity_sorter.providers.eodhd.corporate_actions import parse_dividends_payload, parse_splits_payload
from equity_sorter.providers.eodhd.prices import parse_eod_prices_payload
from equity_sorter.providers.eodhd.symbols import SymbolRecord


def normalize_symbol_records(symbols: list[SymbolRecord], provider: str) -> dict[str, list[dict[str, Any]]]:
    companies: list[Company] = []
    securities: list[Security] = []
    listings: list[Listing] = []
    identifiers: list[Identifier] = []
    seen_company: set[str] = set()
    seen_security: set[str] = set()

    for symbol in symbols:
        company_id = make_company_id(symbol.name or symbol.code, symbol.country)
        security_id = make_security_id(company_id, symbol.type)
        listing_id = make_listing_id(security_id, symbol.exchange, symbol.code)

        if company_id not in seen_company:
            companies.append(
                Company(
                    company_id=company_id,
                    legal_name=symbol.name or symbol.code,
                    normalized_name=normalize_name(symbol.name or symbol.code),
                    country_of_incorporation=symbol.country,
                    cik=None,
                    lei=None,
                    active_from=None,
                    active_to=None,
                    source_provider=provider,
                )
            )
            seen_company.add(company_id)

        if security_id not in seen_security:
            securities.append(
                Security(
                    security_id=security_id,
                    company_id=company_id,
                    security_type=symbol.type,
                    share_class=None,
                    primary_listing_id=listing_id,
                    active_from=None,
                    active_to=None,
                    is_active=not symbol.delisted,
                    delisting_date=None,
                    delisting_reason=None,
                    source_provider=provider,
                )
            )
            seen_security.add(security_id)

        listings.append(
            Listing(
                listing_id=listing_id,
                security_id=security_id,
                exchange_code=symbol.exchange,
                ticker=symbol.code,
                local_ticker=symbol.code,
                currency=symbol.currency,
                country=symbol.country,
                primary_listing_flag=True,
                valid_from=None,
                valid_to=None,
                source_provider=provider,
            )
        )

        identifiers.append(
            Identifier(
                identifier_id=make_identifier_id(listing_id, "ticker", symbol.code),
                company_id=company_id,
                security_id=security_id,
                listing_id=listing_id,
                id_type="ticker",
                id_value=symbol.code,
                valid_from=None,
                valid_to=None,
                source_provider=provider,
            )
        )

        if symbol.isin:
            identifiers.append(
                Identifier(
                    identifier_id=make_identifier_id(listing_id, "isin", symbol.isin),
                    company_id=company_id,
                    security_id=security_id,
                    listing_id=listing_id,
                    id_type="isin",
                    id_value=symbol.isin,
                    valid_from=None,
                    valid_to=None,
                    source_provider=provider,
                )
            )

    return {
        "companies": [row.to_dict() for row in companies],
        "securities": [row.to_dict() for row in securities],
        "listings": [row.to_dict() for row in listings],
        "identifiers": [row.to_dict() for row in identifiers],
    }


def normalize_quarterly_fundamentals(
    listing_map: dict[str, dict[str, Any]],
    fundamentals_payloads: dict[str, dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    records: list[FundamentalsQuarterly] = []
    grouped_balance = defaultdict(dict)
    grouped_cash = defaultdict(dict)
    grouped_income = defaultdict(dict)

    for symbol_key, payload in fundamentals_payloads.items():
        listing = listing_map[symbol_key]
        company_id = listing["company_id"]
        security_id = listing["security_id"]
        currency = ((payload.get("General") or {}).get("CurrencyCode") or (payload.get("General") or {}).get("CurrencyName"))
        financials = payload.get("Financials") or {}
        for row in (((financials.get("Balance_Sheet") or {}).get("quarterly") or {}).values()):
            grouped_balance[symbol_key][row.get("date")] = row
        for row in (((financials.get("Cash_Flow") or {}).get("quarterly") or {}).values()):
            grouped_cash[symbol_key][row.get("date")] = row
        for row in (((financials.get("Income_Statement") or {}).get("quarterly") or {}).values()):
            grouped_income[symbol_key][row.get("date")] = (row, currency, company_id, security_id)

    for symbol_key, entries in grouped_income.items():
        for fiscal_period_end, bundle in entries.items():
            income, currency, company_id, security_id = bundle
            balance = grouped_balance[symbol_key].get(fiscal_period_end, {})
            cash = grouped_cash[symbol_key].get(fiscal_period_end, {})
            records.append(
                FundamentalsQuarterly(
                    security_id=security_id,
                    company_id=company_id,
                    fiscal_period=str(fiscal_period_end),
                    fiscal_period_end_date=str(fiscal_period_end) if fiscal_period_end else None,
                    fiscal_year=_to_int(income.get("date", "")[:4]),
                    fiscal_quarter=_quarter_from_date(fiscal_period_end),
                    report_date=income.get("filing_date") or income.get("date"),
                    filing_date=income.get("filing_date"),
                    accepted_timestamp=income.get("accepted_date"),
                    currency=currency,
                    accounting_standard=None,
                    restatement_type=None,
                    provider=provider,
                    revenue=_to_float(income.get("totalRevenue")),
                    gross_profit=_to_float(income.get("grossProfit")),
                    operating_income=_to_float(income.get("operatingIncome")),
                    ebit=_to_float(income.get("ebit")),
                    ebitda=_to_float(income.get("ebitda")),
                    net_income=_to_float(income.get("netIncome")),
                    eps_basic=_to_float(income.get("eps")),
                    cash_and_equivalents=_to_float(balance.get("cashAndShortTermInvestments") or balance.get("cashAndCashEquivalents")),
                    total_assets=_to_float(balance.get("totalAssets")),
                    total_debt=_to_float(balance.get("shortLongTermDebtTotal") or balance.get("totalDebt")),
                    total_equity=_to_float(balance.get("totalStockholderEquity") or balance.get("totalEquity")),
                    shares_basic=_to_float(balance.get("commonStockSharesOutstanding")),
                    operating_cash_flow=_to_float(cash.get("totalCashFromOperatingActivities")),
                    capex=_to_float(cash.get("capitalExpenditures")),
                    free_cash_flow=_to_float(cash.get("freeCashFlow")),
                )
            )

    records.sort(key=lambda row: (row.security_id, row.fiscal_period_end_date or ""))
    return [row.to_dict() for row in records]


def normalize_sector_classification(
    listing_map: dict[str, dict[str, Any]],
    fundamentals_payloads: dict[str, dict[str, Any]],
    provider: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol_key, payload in fundamentals_payloads.items():
        listing = listing_map[symbol_key]
        general = payload.get("General") or {}
        sector = general.get("Sector")
        industry = general.get("Industry")
        if sector or industry:
            rows.append(
                {
                    "security_id": listing["security_id"],
                    "listing_id": listing["listing_id"],
                    "sector": sector,
                    "industry": industry,
                    "valid_from": None,
                    "valid_to": None,
                    "source_provider": provider,
                }
            )
    rows.sort(key=lambda row: row["security_id"])
    return rows


def build_listing_context(
    securities: list[dict[str, Any]],
    listings: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    security_to_company = {row["security_id"]: row["company_id"] for row in securities}
    context: dict[str, dict[str, Any]] = {}
    for listing in listings:
        symbol_key = f"{listing['ticker']}.{listing['exchange_code']}"
        context[symbol_key] = {
            **listing,
            "company_id": security_to_company.get(listing["security_id"]),
        }
    return context


def normalize_prices_daily(
    listing_map: dict[str, dict[str, Any]],
    price_payloads: dict[str, list[dict[str, Any]] | dict[str, Any]],
    provider: str,
    ingestion_timestamp: str | None = None,
) -> list[dict[str, Any]]:
    ingestion_timestamp = ingestion_timestamp or utc_now_iso()
    rows: list[PriceDaily] = []
    for symbol_key, payload in price_payloads.items():
        listing = listing_map[symbol_key]
        bars = parse_eod_prices_payload(payload if isinstance(payload, list) else payload.get("payload", []))
        for bar in bars:
            rows.append(
                PriceDaily(
                    security_id=listing["security_id"],
                    listing_id=listing["listing_id"],
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    adjusted_close=bar.adjusted_close,
                    currency=listing.get("currency"),
                    provider=provider,
                    provider_adjustment_method="eodhd_adjusted_close",
                    ingestion_timestamp=ingestion_timestamp,
                    data_quality_score=None,
                )
            )
    rows.sort(key=lambda row: (row.security_id, row.date))
    return [row.to_dict() for row in rows]


def normalize_corporate_actions(
    listing_map: dict[str, dict[str, Any]],
    split_payloads: dict[str, dict[str, Any] | list[dict[str, Any]]],
    dividend_payloads: dict[str, dict[str, Any] | list[dict[str, Any]]],
    provider: str,
) -> list[dict[str, Any]]:
    rows: list[CorporateAction] = []
    for symbol_key, payload in split_payloads.items():
        listing = listing_map[symbol_key]
        for split in parse_splits_payload(payload):
            action_date = split.get("date") or split.get("Date") or split.get("split_date")
            split_ratio = split.get("split") or split.get("split_ratio") or split.get("Split")
            if action_date:
                rows.append(
                    CorporateAction(
                        security_id=listing["security_id"],
                        listing_id=listing["listing_id"],
                        action_date=str(action_date),
                        action_type="split",
                        split_ratio=str(split_ratio) if split_ratio is not None else None,
                        cash_dividend=None,
                        source_provider=provider,
                        confidence_score=0.8,
                    )
                )
    for symbol_key, payload in dividend_payloads.items():
        listing = listing_map[symbol_key]
        for dividend in parse_dividends_payload(payload):
            action_date = dividend.get("date") or dividend.get("Date") or dividend.get("paymentDate") or dividend.get("declarationDate")
            amount = dividend.get("value") or dividend.get("dividend") or dividend.get("Dividend")
            if action_date:
                rows.append(
                    CorporateAction(
                        security_id=listing["security_id"],
                        listing_id=listing["listing_id"],
                        action_date=str(action_date),
                        action_type="cash_dividend",
                        split_ratio=None,
                        cash_dividend=_to_float(amount),
                        source_provider=provider,
                        confidence_score=0.8,
                    )
                )
    rows.sort(key=lambda row: (row.security_id, row.action_date, row.action_type))
    return [row.to_dict() for row in rows]


def _to_float(value: Any) -> float | None:
    if value in (None, "", "None"):
        return None
    return float(value)


def _to_int(value: Any) -> int | None:
    if value in (None, "", "None"):
        return None
    return int(value)


def _quarter_from_date(value: str | None) -> int | None:
    if not value or len(value) < 7:
        return None
    month = int(value[5:7])
    return ((month - 1) // 3) + 1
