# Equity Sorter

Phase 0 foundation for a provider-agnostic equity sorting engine.

Current focus:
- free/open-source US proof first
- notebook/script-first workflow
- canonical schemas, provenance, and normalization
- SEC + Nasdaq Trader + Stooq prototype ingestion
- US sample ingestion and first GARP ranking
- reproducibility and data quality checks

## Phase 0 flow

1. Ingest raw source payloads into bronze storage.
2. Normalize symbols, prices, fundamentals, and corporate actions into silver tables.
3. Build a monthly factor snapshot.
4. Produce a deterministic GARP ranking with explanation columns.
5. Preserve source provenance and confidence alongside selected values.

## Environment

Set `EODHD_API_KEY` before running live EODHD ingestion scripts.

Optional:
- `EQUITY_SORTER_DATA_DIR` to override `./data`
- `EQUITY_SORTER_OUTPUT_DIR` to override `./outputs`
- `SEC_USER_AGENT` for SEC requests, e.g. `your-name your-email@example.com`
- `STOOQ_API_KEY` for direct Stooq historical CSV access if you have it

## Scripts

- Free/offline fixture ingest:
`python scripts/load_free_us_demo_fixture.py`
- Build free US snapshot:
`python scripts/build_sample_snapshot.py --as-of-date 2025-05-30 --exchange US --snapshot-name free_us_demo`
- Run free US ranking:
`python scripts/run_garp_ranking.py --as-of-date 2025-05-30 --exchange US --snapshot-name free_us_demo`
- Optional live EODHD ingest:
`python scripts/ingest_eodhd_sample.py --exchange US --country USA --max-count 1000`
- Legacy EODHD fixture path:
`python scripts/load_demo_fixture.py`

## Free/Open Demo Flow

1. `python scripts/load_free_us_demo_fixture.py`
2. `python scripts/run_garp_ranking.py --as-of-date 2025-05-30 --exchange US --snapshot-name free_us_demo`
3. Inspect `outputs/quality/US/` and `outputs/free_us_demo/`

## Real Public-Source Flow

Set a real SEC user agent first:

`$env:SEC_USER_AGENT="your-name your-email@example.com"`

Then run:

1. `python scripts/download_public_us_sample.py --bronze-date 2026-05-09 --tickers AAPL,MSFT,KO`
2. `python scripts/build_public_us_sample.py --bronze-date 2026-05-09`
3. `python scripts/run_garp_ranking.py --as-of-date 2025-05-30 --exchange US --snapshot-name public_us_phase0`
4. `python scripts/generate_sec_normalization_report.py --bronze-date 2026-05-09`

Artifacts:

- ranking: `outputs/public_us_phase0/<date>/rankings.csv`
- quality: `outputs/quality/US/<bronze-date>/events.jsonl`
- comparison: `outputs/comparison/US/<bronze-date>/source_comparison.csv`

## Local Price Import Flow

Use this when fundamentals/reference data are live but public price downloads are unavailable.

1. Generate a sample local CSV for testing:
`python scripts/generate_sample_local_price_csv.py --output data/manual_inputs/us_prices_sample.csv --tickers AAPL,MSFT,KO`
2. Copy or import your own price CSV into bronze:
`python scripts/import_local_price_csv.py --bronze-date 2026-05-09-live2 --csv-path data/manual_inputs/us_prices_sample.csv`
3. Rebuild the public US sample:
`python scripts/build_public_us_sample.py --bronze-date 2026-05-09-live2`
4. Run the ranking:
`python scripts/run_garp_ranking.py --as-of-date 2025-05-30 --exchange US --snapshot-name public_us_phase0_local_prices`

Expected CSV columns for local import:

`ticker,date,open,high,low,close,volume,currency`

Optional columns:

`adjusted_close,adjustment_method,source_record_id`

## Research Artifacts

- `docs/free_source_inventory.md`
- `docs/free_open_gap_report.md`
- `docs/source_resolution_model.md`

## Web app (screener + company pages)

Requires `EODHD_API_KEY` in `.env` for live fundamentals, prices, and US quotes.

```bash
pip install -r web/requirements.txt
python run_server.py
```

Open http://localhost:3000 for the dashboard screener; `/company/{SYMBOL}` for charts, live quotes, and Codex chat.

## Tests

- `python -m unittest discover -s tests -p "test_*.py"`
