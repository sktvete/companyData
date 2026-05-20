# companyData

Equity screener and company research UI backed by EODHD fundamentals, with batch scoring for thousands of names.

## Quick start (web app)

1. Create `.env` with your API key:

   ```
   EODHD_API_KEY=your_key_here
   ```

2. Install and run:

   ```bash
   pip install -r web/requirements.txt
   python run_server.py
   ```

3. Open http://localhost:3000 — dashboard screener and filters.  
   Company pages: http://localhost:3000/company/NVDA (charts, live US quotes, Codex chat).

The server loads the latest `outputs/scaled_analysis/scaled_analysis_*.jsonl` universe (and any newer rescored overlay if present).

## Refresh the universe (batch scoring)

Re-score companies from EODHD and write a new analysis file:

```bash
python scripts/scale_analysis_1000.py --target 1000 --workers 32
```

Output lands under `outputs/scaled_analysis/`. Restart the web server to pick up the new file.

Other maintenance scripts (optional): `scripts/rescore_companies.py`, `scripts/discover_companies.py`, `scripts/validate_universe_smoke.py`.

## Environment

| Variable | Purpose |
|----------|---------|
| `EODHD_API_KEY` | Required for web app and batch analysis |
| `OPENAI_API_KEY` | Codex chat on company pages (optional) |
| `EQUITY_SORTER_DATA_DIR` | Override `./data` (batch / bronze paths) |
| `EQUITY_SORTER_OUTPUT_DIR` | Override `./outputs` |

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Layout

| Path | Role |
|------|------|
| `web/` | Flask app, templates, live quote + chart APIs |
| `src/equity_sorter/` | Metrics, caching, EODHD client |
| `scripts/` | Batch ingest, rescoring, universe tools |
| `outputs/` | Analysis JSONL consumed by the app (gitignored) |
| `docs/` | Older design notes and source research (optional reading) |
