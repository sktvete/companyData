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

On the dashboard, use **Universe scan** (top nav) to refresh fundamentals and rescore the saved symbol list. Progress is shown in the modal; the server reloads data when the run finishes.

The app loads the latest `outputs/scaled_analysis/scaled_analysis_*.jsonl` (plus any newer rescored overlay).

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
| `scripts/` | CLI tools (same pipeline as Universe scan; optional) |
| `outputs/` | Analysis JSONL consumed by the app (gitignored) |
| `docs/` | Older design notes and source research (optional reading) |
