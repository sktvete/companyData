from __future__ import annotations

from pathlib import Path
from typing import Any

from equity_sorter.canonical.factors import build_factor_snapshot, build_fundamentals_only_snapshot, build_hybrid_snapshot
from equity_sorter.canonical.normalization import (
    build_listing_context,
    normalize_corporate_actions,
    normalize_prices_daily,
    normalize_quarterly_fundamentals,
    normalize_sector_classification,
    normalize_symbol_records,
)
from equity_sorter.canonical.ranking import add_ranks, select_ranking_output
from equity_sorter.config import Settings
from equity_sorter.io_utils import file_checksum, read_json, read_jsonl, utc_now_iso, write_csv, write_json, write_jsonl, write_optional_parquet
from equity_sorter.providers.eodhd.corporate_actions import dividends_request, splits_request
from equity_sorter.providers.eodhd.fundamentals import fundamentals_request
from equity_sorter.providers.eodhd.prices import eod_prices_request
from equity_sorter.providers.eodhd.symbols import list_exchange_symbols_request, parse_symbol_payload
from equity_sorter.providers.eodhd.client import EODHDClient
from equity_sorter.quality import validate_fundamentals, validate_listings, validate_prices


def ingest_exchange_symbols(settings: Settings, exchange_code: str, bronze_date: str) -> Path:
    if not settings.eodhd_api_key:
        raise RuntimeError("EODHD_API_KEY is required for live ingestion")
    client = EODHDClient(settings.eodhd_api_key)
    request = list_exchange_symbols_request(exchange_code)
    payload = client.get_json(request)
    path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={bronze_date}" / "payload.json"
    write_json(path, {"request": request.__dict__, "payload": payload})
    return path


def normalize_exchange_symbols(settings: Settings, exchange_code: str, bronze_date: str) -> dict[str, Path]:
    raw_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=symbols" / f"exchange={exchange_code}" / f"date={bronze_date}" / "payload.json"
    raw = read_json(raw_path)
    symbols = parse_symbol_payload(raw["payload"], exchange_code)
    tables = normalize_symbol_records(symbols, settings.provider_name)
    output_paths: dict[str, Path] = {}
    for table_name, rows in tables.items():
        path = settings.data_dir / "silver" / table_name / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl"
        write_jsonl(path, rows)
        output_paths[table_name] = path
    return output_paths


def ingest_security_payloads(settings: Settings, symbols: list[dict[str, Any]], bronze_date: str, max_count: int) -> dict[str, list[Path]]:
    if not settings.eodhd_api_key:
        raise RuntimeError("EODHD_API_KEY is required for live ingestion")
    client = EODHDClient(settings.eodhd_api_key)
    fundamentals_paths: list[Path] = []
    price_paths: list[Path] = []
    split_paths: list[Path] = []
    dividend_paths: list[Path] = []
    sampled = symbols[:max_count]
    for symbol in sampled:
        code = symbol["ticker"]
        exchange_code = symbol["exchange_code"]
        fundamentals_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=fundamentals" / f"exchange={exchange_code}" / f"date={bronze_date}" / f"{code}.json"
        prices_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=prices_daily" / f"exchange={exchange_code}" / f"date={bronze_date}" / f"{code}.json"
        splits_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=corporate_actions_splits" / f"exchange={exchange_code}" / f"date={bronze_date}" / f"{code}.json"
        dividends_path = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / "dataset=corporate_actions_dividends" / f"exchange={exchange_code}" / f"date={bronze_date}" / f"{code}.json"
        write_json(fundamentals_path, client.get_json(fundamentals_request(code, exchange_code)))
        write_json(prices_path, client.get_json(eod_prices_request(code, exchange_code)))
        write_json(splits_path, client.get_json(splits_request(code, exchange_code)))
        write_json(dividends_path, client.get_json(dividends_request(code, exchange_code)))
        fundamentals_paths.append(fundamentals_path)
        price_paths.append(prices_path)
        split_paths.append(splits_path)
        dividend_paths.append(dividends_path)
    return {"fundamentals": fundamentals_paths, "prices": price_paths, "splits": split_paths, "dividends": dividend_paths}


def normalize_security_payloads(settings: Settings, exchange_code: str, bronze_date: str) -> dict[str, Path]:
    silver_root = settings.data_dir / "silver"
    listings = read_jsonl(silver_root / "listings" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl")
    securities = read_jsonl(silver_root / "securities" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl")
    listing_map = build_listing_context(securities, listings)

    fundamentals_payloads = _load_bronze_symbol_payloads(settings, exchange_code, bronze_date, dataset="fundamentals")
    prices_payloads = _load_bronze_symbol_payloads(settings, exchange_code, bronze_date, dataset="prices_daily")
    splits_payloads = _load_bronze_symbol_payloads(settings, exchange_code, bronze_date, dataset="corporate_actions_splits")
    dividends_payloads = _load_bronze_symbol_payloads(settings, exchange_code, bronze_date, dataset="corporate_actions_dividends")

    fundamentals = normalize_quarterly_fundamentals(listing_map, fundamentals_payloads, settings.provider_name)
    prices = normalize_prices_daily(listing_map, prices_payloads, settings.provider_name, ingestion_timestamp=utc_now_iso())
    corporate_actions = normalize_corporate_actions(listing_map, splits_payloads, dividends_payloads, settings.provider_name)
    sector_classification = normalize_sector_classification(listing_map, fundamentals_payloads, settings.provider_name)

    outputs = {
        "fundamentals_quarterly": silver_root / "fundamentals_quarterly" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl",
        "prices_daily": silver_root / "prices_daily" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl",
        "corporate_actions": silver_root / "corporate_actions" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl",
        "sector_classification": silver_root / "sector_classification" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl",
    }
    write_jsonl(outputs["fundamentals_quarterly"], fundamentals)
    write_jsonl(outputs["prices_daily"], prices)
    write_jsonl(outputs["corporate_actions"], corporate_actions)
    write_jsonl(outputs["sector_classification"], sector_classification)
    return outputs


def build_sample_snapshot(
    settings: Settings,
    as_of_date: str,
    snapshot_name: str = "sample",
    exchange_codes: list[str] | None = None,
    source_date: str | None = None,
) -> dict[str, Path]:
    silver_root = settings.data_dir / "silver"
    companies = _load_latest_table(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date)
    securities = _load_latest_table(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date)
    listings = _load_latest_table(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date)
    fundamentals = _load_latest_table(silver_root / "fundamentals_quarterly", exchange_codes=exchange_codes, source_date=source_date)
    prices = _load_latest_table(silver_root / "prices_daily", exchange_codes=exchange_codes, source_date=source_date)
    sector_rows = _load_latest_table(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date)
    sectors = {row["security_id"]: row.get("sector") for row in sector_rows}
    source_names = sorted({row.get("provider") for row in fundamentals if row.get("provider")} | {row.get("provider") for row in prices if row.get("provider")})
    snapshot_rows = build_factor_snapshot(
        as_of_date,
        companies,
        securities,
        listings,
        prices,
        fundamentals,
        sectors=sectors,
        source_lineage="+".join(source_names) if source_names else "selected_sources",
    )
    ranked_rows = add_ranks(snapshot_rows)
    ranking_output = select_ranking_output(ranked_rows)
    csv_path = settings.output_dir / snapshot_name / as_of_date / "rankings.csv"
    jsonl_path = settings.output_dir / snapshot_name / as_of_date / "rankings.jsonl"
    manifest_path = settings.output_dir / snapshot_name / as_of_date / "manifest.json"
    parquet_path = settings.output_dir / snapshot_name / as_of_date / "rankings.parquet"
    write_csv(csv_path, ranking_output)
    write_jsonl(jsonl_path, ranking_output)
    source_files = {
        "companies": _latest_table_paths(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date),
        "securities": _latest_table_paths(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date),
        "listings": _latest_table_paths(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date),
        "fundamentals_quarterly": _latest_table_paths(silver_root / "fundamentals_quarterly", exchange_codes=exchange_codes, source_date=source_date),
        "prices_daily": _latest_table_paths(silver_root / "prices_daily", exchange_codes=exchange_codes, source_date=source_date),
        "sector_classification": _latest_table_paths(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date),
    }
    write_json(
        manifest_path,
        {
            "as_of_date": as_of_date,
            "snapshot_name": snapshot_name,
            "exchange_codes": exchange_codes or "all_latest",
            "row_count": len(ranking_output),
            "scoring_version": ranking_output[0]["scoring_version"] if ranking_output else None,
            "source_checksums": {
                name: {str(path): file_checksum(path) for path in paths}
                for name, paths in source_files.items()
            },
        },
    )
    write_optional_parquet(parquet_path, ranking_output)
    return {"csv": csv_path, "jsonl": jsonl_path, "manifest": manifest_path, "parquet": parquet_path}


def build_us_sample_snapshot(settings: Settings, as_of_date: str, snapshot_name: str = "us_sample") -> dict[str, Path]:
    return build_sample_snapshot(settings, as_of_date, snapshot_name=snapshot_name, exchange_codes=["US"])


def build_fundamentals_only_us_snapshot(
    settings: Settings,
    as_of_date: str,
    snapshot_name: str = "fundamentals_only_us",
    exchange_codes: list[str] | None = None,
    fundamentals_table_name: str = "fundamentals_quarterly",
    source_date: str | None = None,
) -> dict[str, Path]:
    silver_root = settings.data_dir / "silver"
    companies = _load_latest_table(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date)
    securities = _load_latest_table(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date)
    listings = _load_latest_table(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date)
    fundamentals = _load_latest_table(silver_root / fundamentals_table_name, exchange_codes=exchange_codes, source_date=source_date)
    sector_rows = _load_latest_table(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date)
    sectors = {row["security_id"]: row.get("sector") for row in sector_rows}
    snapshot_rows = build_fundamentals_only_snapshot(
        as_of_date,
        companies,
        securities,
        listings,
        fundamentals,
        sectors=sectors,
        source_lineage="sec_edgar+nasdaq_trader",
    )
    ranked_rows = add_ranks(snapshot_rows, score_field="total_score")
    ranking_output = select_ranking_output(ranked_rows)
    csv_path = settings.output_dir / snapshot_name / as_of_date / "rankings.csv"
    jsonl_path = settings.output_dir / snapshot_name / as_of_date / "rankings.jsonl"
    manifest_path = settings.output_dir / snapshot_name / as_of_date / "manifest.json"
    parquet_path = settings.output_dir / snapshot_name / as_of_date / "rankings.parquet"
    write_csv(csv_path, ranking_output)
    write_jsonl(jsonl_path, ranking_output)
    write_json(
        manifest_path,
        {
            "as_of_date": as_of_date,
            "snapshot_name": snapshot_name,
            "exchange_codes": exchange_codes or ["US"],
            "row_count": len(ranking_output),
            "scoring_version": ranking_output[0]["scoring_version"] if ranking_output else None,
            "ranking_mode": "fundamentals_only",
            "source_checksums": {
                "companies": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date)},
                "securities": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date)},
                "listings": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date)},
                fundamentals_table_name: {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / fundamentals_table_name, exchange_codes=exchange_codes, source_date=source_date)},
                "sector_classification": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date)},
            },
        },
    )
    write_optional_parquet(parquet_path, ranking_output)
    return {"csv": csv_path, "jsonl": jsonl_path, "manifest": manifest_path, "parquet": parquet_path}


def build_hybrid_us_snapshot(
    settings: Settings,
    as_of_date: str,
    snapshot_name: str = "hybrid_us",
    exchange_codes: list[str] | None = None,
    source_date: str | None = None,
) -> dict[str, Path]:
    silver_root = settings.data_dir / "silver"
    companies = _load_latest_table(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date)
    securities = _load_latest_table(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date)
    listings = _load_latest_table(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date)
    fundamentals = _load_latest_table(silver_root / "fundamentals_quarterly", exchange_codes=exchange_codes, source_date=source_date)
    prices = _load_latest_table(silver_root / "prices_daily", exchange_codes=exchange_codes, source_date=source_date)
    sector_rows = _load_latest_table(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date)
    sectors = {row["security_id"]: row.get("sector") for row in sector_rows}
    source_names = sorted({row.get("provider") for row in fundamentals if row.get("provider")} | {row.get("provider") for row in prices if row.get("provider")})
    snapshot_rows = build_hybrid_snapshot(
        as_of_date,
        companies,
        securities,
        listings,
        prices,
        fundamentals,
        sectors=sectors,
        source_lineage="+".join(source_names) if source_names else "selected_sources",
    )
    ranked_rows = sorted(
        snapshot_rows,
        key=lambda row: (0 if row.get("ranking_mode") == "hybrid_price_backed" else 1, -float(row.get("hybrid_score", 0.0))),
    )
    mode_counts: dict[str, int] = {}
    for index, row in enumerate(ranked_rows, start=1):
        row["rank"] = index
        mode = str(row.get("ranking_mode") or "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        row["mode_rank"] = mode_counts[mode]
    ranking_output = select_ranking_output(ranked_rows)
    csv_path = settings.output_dir / snapshot_name / as_of_date / "rankings.csv"
    jsonl_path = settings.output_dir / snapshot_name / as_of_date / "rankings.jsonl"
    manifest_path = settings.output_dir / snapshot_name / as_of_date / "manifest.json"
    parquet_path = settings.output_dir / snapshot_name / as_of_date / "rankings.parquet"
    write_csv(csv_path, ranking_output)
    write_jsonl(jsonl_path, ranking_output)
    price_backed_count = sum(1 for row in ranking_output if row.get("ranking_mode") == "hybrid_price_backed")
    fundamentals_only_count = sum(1 for row in ranking_output if row.get("ranking_mode") == "hybrid_fundamentals_only")
    write_json(
        manifest_path,
        {
            "as_of_date": as_of_date,
            "snapshot_name": snapshot_name,
            "exchange_codes": exchange_codes or ["US"],
            "row_count": len(ranking_output),
            "scoring_version": ranking_output[0]["scoring_version"] if ranking_output else None,
            "ranking_mode": "hybrid",
            "price_backed_count": price_backed_count,
            "fundamentals_only_count": fundamentals_only_count,
            "source_checksums": {
                "companies": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "companies", exchange_codes=exchange_codes, source_date=source_date)},
                "securities": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "securities", exchange_codes=exchange_codes, source_date=source_date)},
                "listings": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "listings", exchange_codes=exchange_codes, source_date=source_date)},
                "fundamentals_quarterly": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "fundamentals_quarterly", exchange_codes=exchange_codes, source_date=source_date)},
                "prices_daily": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "prices_daily", exchange_codes=exchange_codes, source_date=source_date)},
                "sector_classification": {str(path): file_checksum(path) for path in _latest_table_paths(silver_root / "sector_classification", exchange_codes=exchange_codes, source_date=source_date)},
            },
        },
    )
    write_optional_parquet(parquet_path, ranking_output)
    return {"csv": csv_path, "jsonl": jsonl_path, "manifest": manifest_path, "parquet": parquet_path}


def build_quality_report(settings: Settings, exchange_code: str, bronze_date: str) -> Path:
    silver_root = settings.data_dir / "silver"
    listings = read_jsonl(silver_root / "listings" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl")
    prices = read_jsonl(silver_root / "prices_daily" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl")
    fundamentals = read_jsonl(silver_root / "fundamentals_quarterly" / f"exchange={exchange_code}" / f"date={bronze_date}" / "rows.jsonl")
    events = []
    events.extend(validate_listings(listings, settings.provider_name))
    events.extend(validate_prices(prices, settings.provider_name))
    events.extend(validate_fundamentals(fundamentals, settings.provider_name))
    path = settings.output_dir / "quality" / exchange_code / bronze_date / "events.jsonl"
    write_jsonl(path, events)
    return path


def _load_latest_table(root: Path, exchange_codes: list[str] | None = None, source_date: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _latest_table_paths(root, exchange_codes=exchange_codes, source_date=source_date):
        rows.extend(read_jsonl(path))
    return rows


def _latest_table_paths(root: Path, exchange_codes: list[str] | None = None, source_date: str | None = None) -> list[Path]:
    if exchange_codes:
        selected: list[Path] = []
        for exchange_code in exchange_codes:
            if source_date:
                exact_path = root / f"exchange={exchange_code}" / f"date={source_date}" / "rows.jsonl"
                if exact_path.exists():
                    selected.append(exact_path)
                continue
            candidates = sorted(root.glob(f"exchange={exchange_code}/date=*/rows.jsonl"))
            if candidates:
                selected.append(candidates[-1])
        return selected
    if source_date:
        candidates = sorted(root.glob(f"**/date={source_date}/rows.jsonl"))
        return candidates
    candidates = sorted(root.glob("**/rows.jsonl"))
    return [candidates[-1]] if candidates else []


def _load_bronze_symbol_payloads(settings: Settings, exchange_code: str, bronze_date: str, dataset: str) -> dict[str, Any]:
    root = settings.data_dir / "bronze" / f"provider={settings.provider_name}" / f"dataset={dataset}" / f"exchange={exchange_code}" / f"date={bronze_date}"
    payloads: dict[str, Any] = {}
    for path in sorted(root.glob("*.json")):
        symbol_key = f"{path.stem}.{exchange_code}"
        payloads[symbol_key] = read_json(path)
    return payloads
