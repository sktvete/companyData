from __future__ import annotations

from pathlib import Path
from typing import Any

from equity_sorter.canonical.normalization import normalize_symbol_records
from equity_sorter.canonical.provenance import candidates_from_row
from equity_sorter.config import Settings
from equity_sorter.io_utils import read_json, read_jsonl, utc_now_iso, write_jsonl
from equity_sorter.providers.eodhd.symbols import SymbolRecord
from equity_sorter.providers.local_csv.prices import parse_local_price_csv
from equity_sorter.providers.nasdaq_trader.symbols import parse_nasdaq_trader_symbols
from equity_sorter.providers.sec_edgar.companyfacts import extract_quarterly_facts
from equity_sorter.providers.sec_edgar.submissions import extract_company_metadata
from equity_sorter.providers.stooq.prices import parse_stooq_csv
from equity_sorter.quality import validate_fundamentals, validate_listings, validate_prices


def normalize_free_us_reference(settings: Settings, bronze_date: str) -> dict[str, Path]:
    parsed = _load_free_us_symbol_rows(settings, bronze_date)
    symbol_records = [
        SymbolRecord(
            code=str(row["ticker"]),
            exchange="US",
            name=str(row["name"]),
            country="USA",
            currency="USD",
            type="Common Stock",
            isin=None,
            delisted=False,
        )
        for row in parsed
        if _is_common_stock_candidate(row)
    ]
    tables = normalize_symbol_records(symbol_records, provider="free_us")
    outputs: dict[str, Path] = {}
    for table_name, rows in tables.items():
        path = settings.data_dir / "silver" / table_name / "exchange=US" / f"date={bronze_date}" / "rows.jsonl"
        write_jsonl(path, rows)
        outputs[table_name] = path
    return outputs


def _load_free_us_symbol_rows(settings: Settings, bronze_date: str) -> list[dict[str, Any]]:
    root = settings.data_dir / "bronze" / "provider=free_us"
    fixture_path = root / "dataset=nasdaq_trader_symbols" / f"date={bronze_date}" / "symbols.txt"
    if fixture_path.exists():
        return parse_nasdaq_trader_symbols(fixture_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for dataset in ["nasdaqlisted", "otherlisted"]:
        path = root / f"dataset={dataset}" / f"date={bronze_date}" / f"{dataset}.txt"
        if path.exists():
            rows.extend(parse_nasdaq_trader_symbols(path.read_text(encoding="utf-8")))
    return rows


def _is_common_stock_candidate(row: dict[str, Any]) -> bool:
    name = str(row.get("name") or "")
    exchange = str(row.get("exchange") or "").upper()
    if row.get("etf") or row.get("test_issue"):
        return False
    if any(token in name.upper() for token in ["ETF", "TRUST", "FUND", "PREFERRED", "NOTE", "WARRANT", "UNIT", "RIGHTS"]):
        return False
    if any(token in name.upper() for token in ["ADR", "ADS", "DEPOSITARY", "ORDINARY SHARES"]):
        return False
    return exchange in {"NASDAQ", "NYSE", "NYSE AMERICAN", "NYSE ARCA", "BATS", "US", "N", "A", "P", "V", "Z"}


def normalize_free_us_security_payloads(settings: Settings, bronze_date: str) -> dict[str, Path]:
    silver_root = settings.data_dir / "silver"
    listings = read_jsonl(silver_root / "listings" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    securities = read_jsonl(silver_root / "securities" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    companies = read_jsonl(silver_root / "companies" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    company_map = {row["company_id"]: row for row in companies}
    security_company_map = {row["security_id"]: row["company_id"] for row in securities}
    listing_map = {f"{row['ticker']}.US": row for row in listings}

    fundamentals_rows: list[dict[str, Any]] = []
    price_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    source_candidates: list[dict[str, Any]] = []
    ingestion_timestamp = utc_now_iso()

    sec_root = settings.data_dir / "bronze" / "provider=sec_edgar"
    stooq_root = settings.data_dir / "bronze" / "provider=stooq"

    for companyfacts_path in sorted((sec_root / "dataset=companyfacts" / f"date={bronze_date}").glob("*.json")):
        payload = read_json(companyfacts_path)
        cik = companyfacts_path.stem
        submissions = read_json(sec_root / "dataset=submissions" / f"date={bronze_date}" / f"{cik}.json")
        metadata = extract_company_metadata(submissions)
        ticker = metadata["tickers"][0]
        listing = listing_map.get(f"{ticker}.US")
        if not listing:
            continue
        security_id = listing["security_id"]
        company_id = security_company_map[security_id]
        company_map[company_id]["cik"] = cik
        facts_rows = extract_quarterly_facts(payload)
        for row in facts_rows:
            normalized = {
                "security_id": security_id,
                "company_id": company_id,
                "fiscal_period": row.get("fiscal_period"),
                "fiscal_period_end_date": row.get("fiscal_period_end_date"),
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_quarter": row.get("fiscal_quarter"),
                "report_date": row.get("report_date"),
                "filing_date": row.get("filing_date"),
                "accepted_timestamp": row.get("accepted_timestamp"),
                "currency": "USD",
                "accounting_standard": "us_gaap",
                "restatement_type": None,
                "provider": "sec_edgar",
                "revenue": row.get("revenue"),
                "gross_profit": row.get("gross_profit"),
                "operating_income": row.get("operating_income"),
                "ebit": row.get("operating_income"),
                "ebitda": None,
                "net_income": row.get("net_income"),
                "eps_basic": None,
                "cash_and_equivalents": row.get("cash_and_equivalents"),
                "total_assets": row.get("total_assets"),
                "total_debt": row.get("total_debt"),
                "total_equity": row.get("total_equity"),
                "shares_basic": row.get("shares_basic"),
                "operating_cash_flow": row.get("operating_cash_flow"),
                "capex": row.get("capex"),
                "free_cash_flow": row.get("free_cash_flow"),
            }
            fundamentals_rows.append(normalized)
            source_candidates.extend(
                candidates_from_row(
                    table_name="fundamentals_quarterly",
                    entity_id=f"{security_id}:{normalized['fiscal_period']}",
                    row=normalized,
                    fields=[
                        "revenue",
                        "gross_profit",
                        "operating_income",
                        "net_income",
                        "cash_and_equivalents",
                        "total_assets",
                        "total_debt",
                        "total_equity",
                        "shares_basic",
                        "operating_cash_flow",
                        "capex",
                        "free_cash_flow",
                    ],
                    source="sec_edgar",
                    source_record_id=row.get("source_record_id"),
                    period=normalized["fiscal_period"],
                    report_date=normalized["report_date"],
                    filing_date=normalized["filing_date"],
                    ingestion_timestamp=ingestion_timestamp,
                    confidence=0.95,
                    pit_safe=True,
                    license_class="official_public",
                    method="parsed_companyfacts",
                    selection_reason="official_source_first",
                )
            )
        sector_rows.append(
            {
                "security_id": security_id,
                "listing_id": listing["listing_id"],
                "sector": metadata.get("sic_description"),
                "industry": None,
                "valid_from": None,
                "valid_to": None,
                "source_provider": "sec_edgar",
            }
        )
        price_records = _load_price_records(settings, bronze_date, ticker)
        for source_name, confidence, pit_safe, license_class, method, dataset_status, records in price_records:
            for bar in records:
                normalized_price = {
                    "security_id": security_id,
                    "listing_id": listing["listing_id"],
                    "date": bar.get("date"),
                    "open": bar.get("open"),
                    "high": bar.get("high"),
                    "low": bar.get("low"),
                    "close": bar.get("close"),
                    "volume": bar.get("volume"),
                    "adjusted_close": bar.get("adjusted_close"),
                    "currency": bar.get("currency") or "USD",
                    "provider": source_name,
                    "provider_adjustment_method": bar.get("adjustment_method") or ("unknown_unadjusted" if source_name == "stooq" else "user_supplied"),
                    "price_data_status": dataset_status,
                    "price_confidence": confidence,
                    "ingestion_timestamp": ingestion_timestamp,
                    "data_quality_score": None,
                }
                price_rows.append(normalized_price)
                source_candidates.extend(
                    candidates_from_row(
                        table_name="prices_daily",
                        entity_id=f"{security_id}:{normalized_price['date']}",
                        row=normalized_price,
                        fields=["open", "high", "low", "close", "adjusted_close", "volume"],
                        source=source_name,
                        source_record_id=bar.get("source_record_id") or f"{ticker}.US",
                        period=normalized_price["date"],
                        report_date=normalized_price["date"],
                        filing_date=None,
                        ingestion_timestamp=ingestion_timestamp,
                        confidence=confidence,
                        pit_safe=pit_safe,
                        license_class=license_class,
                        method=method,
                        selection_reason="manual_price_import" if source_name == "local_csv" else "free_price_baseline",
                    )
                )
            if records:
                break

    fundamentals_rows.sort(key=lambda row: (row["security_id"], row["fiscal_period_end_date"] or ""))
    price_rows.sort(key=lambda row: (row["security_id"], row["date"] or ""))

    write_jsonl(silver_root / "companies" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl", list(company_map.values()))
    write_jsonl(silver_root / "fundamentals_quarterly" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl", fundamentals_rows)
    write_jsonl(silver_root / "prices_daily" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl", price_rows)
    write_jsonl(silver_root / "sector_classification" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl", sector_rows)
    write_jsonl(silver_root / "source_candidates" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl", source_candidates)

    return {
        "companies": silver_root / "companies" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl",
        "fundamentals_quarterly": silver_root / "fundamentals_quarterly" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl",
        "prices_daily": silver_root / "prices_daily" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl",
        "sector_classification": silver_root / "sector_classification" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl",
        "source_candidates": silver_root / "source_candidates" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl",
    }


def build_free_us_quality_report(settings: Settings, bronze_date: str) -> Path:
    silver_root = settings.data_dir / "silver"
    listings = read_jsonl(silver_root / "listings" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    prices = read_jsonl(silver_root / "prices_daily" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    fundamentals = read_jsonl(silver_root / "fundamentals_quarterly" / "exchange=US" / f"date={bronze_date}" / "rows.jsonl")
    events = []
    events.extend(validate_listings(listings, "free_us"))
    events.extend(validate_prices(prices, "stooq"))
    events.extend(validate_fundamentals(fundamentals, "sec_edgar"))
    if not prices:
        events.append(
            {
                "event_id": "dq_missing_public_prices",
                "table_name": "prices_daily",
                "entity_id": "US",
                "rule_name": "missing_public_price_series",
                "severity": "warning",
                "message": "No public price rows loaded. Stooq may require STOOQ_API_KEY or a manual CSV fallback.",
                "provider": "stooq",
                "event_timestamp": utc_now_iso(),
            }
        )
    path = settings.output_dir / "quality" / "US" / bronze_date / "events.jsonl"
    write_jsonl(path, events)
    return path


def _load_price_records(settings: Settings, bronze_date: str, ticker: str) -> list[tuple[str, float, bool, str, str, str, list[dict[str, Any]]]]:
    local_root = settings.data_dir / "bronze" / "provider=local_csv" / "dataset=prices_daily" / f"date={bronze_date}"
    stooq_root = settings.data_dir / "bronze" / "provider=stooq"
    local_status, local_rows = _load_local_csv_price_rows(local_root, ticker)
    stooq_path = stooq_root / "dataset=prices_daily" / f"date={bronze_date}" / f"{ticker}.US.csv"
    stooq_rows = parse_stooq_csv(stooq_path.read_text(encoding="utf-8")) if stooq_path.exists() else []
    return [
        ("local_csv", 0.85 if local_rows and local_status.startswith("real") else 0.6, False, "user_supplied_local", "parsed_csv", local_status, local_rows),
        ("stooq", 0.7, False, "public_free", "parsed_csv", "real_public_unadjusted_or_unknown", stooq_rows),
    ]


def _load_local_csv_price_rows(root: Path, ticker: str) -> tuple[str, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    statuses: list[str] = []
    for path in sorted(root.glob("*.csv")):
        manifest = _load_local_csv_manifest(path)
        statuses.append(_manifest_price_status(manifest))
        for row in parse_local_price_csv(path.read_text(encoding="utf-8"), column_map=manifest.get("column_map")):
            if row.get("ticker") == ticker.upper():
                row["adjustment_method"] = row.get("adjustment_method") or manifest.get("adjustment_method")
                row["currency"] = row.get("currency") or manifest.get("currency")
                rows.append(row)
    rows.sort(key=lambda row: row.get("date") or "")
    return (statuses[0] if statuses else "unknown_local_import", rows)


def _load_local_csv_manifest(csv_path: Path) -> dict[str, Any]:
    manifest_path = csv_path.with_suffix(csv_path.suffix + ".meta.json")
    if manifest_path.exists():
        return read_json(manifest_path)
    return {
        "column_map": None,
        "price_reality": "unknown",
        "currency": "USD",
        "adjustment_method": None,
    }


def _manifest_price_status(manifest: dict[str, Any]) -> str:
    price_reality = str(manifest.get("price_reality") or "unknown")
    adjustment_method = str(manifest.get("adjustment_method") or "unknown")
    if price_reality == "synthetic_demo":
        return "synthetic_demo"
    if adjustment_method in {"", "None", "unknown"}:
        return "real_imported_adjustment_unknown"
    return f"real_imported_{adjustment_method}"
