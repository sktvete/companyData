---
name: stock-analysis
description: >-
  Long-term fundamental stock analysis for US-listed equities using EODHD data.
  Produces strict JSON with buy/watchlist/no_buy recommendation, scored across
  growth, quality, valuation, balance sheet, earnings quality, catalysts,
  sentiment, technicals, and risk. Use this skill whenever the user asks to
  analyze a stock, evaluate a ticker, screen an equity, decide whether to buy
  a stock, or compare fundamental quality of companies. Also use when the user
  mentions stock screening, investment analysis, or fundamental research for
  US equities.
---

# Stock Analysis Skill

Analyze a US-listed stock and return a **strict valid JSON** verdict: `buy`, `watchlist`, or `no_buy`. Investment horizon is **1+ years**. This is fundamental-first analysis with technicals only as confirmation.

## Input

The user provides a ticker and exchange. Default exchange is `US`.

```json
{ "ticker": "NVDA", "exchange": "US" }
```

EODHD uses the format `SYMBOL.EXCHANGE` (e.g., `AAPL.US`, `MSFT.US`, `TSLA.US`). When the user says "NVDA", assume `NVDA.US`. If uncertain, use the EODHD MCP `resolve_ticker` tool first.

## Data Source: EODHD

All financial data comes from EODHD exclusively — no Yahoo Finance, no Macrotrends, no web scraping.

### Preferred: EODHD MCP Tools

If the `user-eodhd` MCP server is connected, use MCP tools directly. They handle authentication automatically, accept flexible date formats, and support section filtering. The key tools are:

| MCP Tool | Purpose |
|---|---|
| `get_fundamentals_data` | Financials, valuation, earnings, holders, insider transactions, shares outstanding. Use `sections` param to filter (e.g., `["Highlights", "Valuation", "Financials"]`). |
| `get_historical_stock_prices` | EOD OHLCV prices. Use `start_date`/`end_date` with `period="d"`. |
| `get_live_price_data` | Current/recent price snapshot. |
| `get_technical_indicators` | Server-side SMA, EMA, RSI, MACD, Bollinger Bands, etc. |
| `get_company_news` | Recent news articles for catalyst/sentiment context. |
| `get_sentiment_data` | Aggregated sentiment scores from news. |
| `resolve_ticker` | Convert company name or partial ticker to `SYMBOL.EXCHANGE`. |

### Fallback: Direct EODHD REST API

If MCP tools are unavailable, use direct HTTP via `WebFetch`. Load `EODHD_API_KEY` from environment variable. See [eodhd-endpoints.md](eodhd-endpoints.md) for endpoint URLs, filters, and field mapping.

### Deterministic Scripts

For batch analysis or reproducible scoring, the `scripts/` directory contains Python tools that calculate metrics and scores deterministically:

```bash
# Single stock analysis
python scripts/analyze_stock.py --ticker AAPL.US --json

# Batch analysis
python scripts/analyze_batch.py --symbols-file symbols.txt --output output.jsonl

# Validate output against schema
python scripts/validate_output.py --file output.json
```

Scripts load `EODHD_API_KEY` from environment (or `.env` file), cache responses to avoid duplicate calls, and produce schema-compliant JSON.

## Execution Workflow

### Step 1: Fetch Data from EODHD

Fetch these three data sets. With MCP, you can run them in parallel.

**1a. Fundamentals** (provides ~80% of needed data):
- MCP: `get_fundamentals_data(ticker="AAPL.US")` — optionally pass `sections=["Highlights", "Valuation", "SharesStats", "Financials", "Earnings", "outstandingShares", "InsiderTransactions", "Holders", "AnalystRatings"]` to reduce response size.
- REST: `GET /api/v1.1/fundamentals/AAPL.US?api_token={KEY}&fmt=json`
- Use the `filter` param to pull specific sections if the full response is too large: `filter=Highlights,Valuation,Financials`

**1b. EOD prices** (1 year of daily data for technicals):
- MCP: `get_historical_stock_prices(ticker="AAPL.US", start_date="2025-05-14", end_date="2026-05-14", period="d")`
- REST: `GET /api/eod/AAPL.US?from=2025-05-14&to=2026-05-14&period=d&api_token={KEY}&fmt=json`

**1c. Current price**:
- MCP: `get_live_price_data(ticker="AAPL.US")`
- REST: `GET /api/real-time/AAPL.US?api_token={KEY}&fmt=json`

**1d. Technical indicators** (optional — saves manual calculation):
- MCP: `get_technical_indicators(ticker="AAPL.US", function="sma", period=50)` — repeat for `period=200` and `function="rsi", period=14`
- REST: `GET /api/technical/AAPL.US?function=sma&period=50&api_token={KEY}&fmt=json`

**1e. News/sentiment** (for catalyst score):
- MCP: `get_company_news(ticker="AAPL.US", limit=20)` and optionally `get_sentiment_data(ticker="AAPL.US")`

**Never hallucinate data.** If EODHD does not return a metric, set it to `null` and add it to `missing_fields`.

### Step 2: Extract Key Metrics

Compute every metric from the EODHD response. See [scoring-methodology.md](scoring-methodology.md) for calculation formulas and [eodhd-endpoints.md](eodhd-endpoints.md) for complete field mapping.

**From Highlights:** market_cap, pe_ratio, peg_ratio, operating_margin, net_margin, eps, revenue TTM.
**From Valuation:** forward_pe, price_to_sales, ev_to_ebitda.
**From Financials.Income_Statement.yearly:** revenue (multi-year for YoY and 3Y CAGR), gross_profit, operating_income, net_income, interest_expense.
**From Financials.Balance_Sheet.yearly:** totalDebt, totalStockholderEquity, cash, totalAssets.
**From Financials.Cash_Flow.yearly:** operating cash flow, capex → derive FCF.
**From outstandingShares.annual:** share count trend for dilution check.
**From EOD prices or technical indicators:** 50 DMA, 200 DMA, RSI-14, 52-week high, drawdown.

**Derived calculations:**
- `revenue_growth_yoy` = (latest_year_revenue / prior_year_revenue) - 1
- `revenue_cagr_3y` = (latest_year_revenue / three_years_ago_revenue)^(1/3) - 1
- `fcf` = totalCashFromOperatingActivities - |capitalExpenditures|
- `fcf_yield` = fcf / market_cap
- `fcf_per_share` = fcf / diluted_shares
- `roic` = NOPAT / invested_capital (or use ReturnOnEquityTTM as proxy)
- `debt_to_equity` = totalDebt / totalStockholderEquity
- `net_debt_to_ebitda` = (totalDebt - cash) / EBITDA
- `interest_coverage` = operating_income / interestExpense

### Step 3: Score Each Category (0-100)

Apply the scoring rubric from [scoring-methodology.md](scoring-methodology.md). Each score is 0-100.

| Category | Weight | What It Measures |
|---|---|---|
| `growth_score` | 20% | Revenue growth, acceleration, FCF growth, EPS growth |
| `quality_score` | 20% | Margins, margin expansion, ROIC |
| `valuation_score` | 20% | P/E, forward P/E, PEG, EV/EBITDA, FCF yield, P/S vs growth |
| `balance_sheet_score` | 15% | Debt ratios, interest coverage, liquidity, dilution risk |
| `earnings_quality_score` | 10% | FCF vs net income, accruals, per-share economics |
| `catalyst_score` | 10% | Analyst estimates, insider transactions, institutional trends |
| `sentiment_score` | — | Insider buying, institutional trends (informational, not weighted) |
| `technical_score` | 5% | Trend, MA position, RSI, drawdown context |
| `risk_red_flag_score` | — | Penalty score (0 = no flags, negative = red flags detected) |

`overall_score` = weighted sum of category scores + `risk_red_flag_score` penalty, clamped to 0-100.

### Step 4: Apply Hard Decision Rules

Read and apply every rule in [hard-rules.md](hard-rules.md). These override the score.

**Critical overrides (summary):**
- **No `buy` if** valuation data is missing/unreliable, revenue/EPS/FCF too incomplete, severe dilution, weak balance sheet, or recommendation based only on hype/momentum/low P/E
- **Penalize** companies where growth is not visible per-share, EPS not supported by FCF, revenue grows but margins deteriorate
- **Separate** "great company but expensive" (watchlist) from "bad company" (no_buy)

### Step 5: Determine Recommendation

| overall_score | Recommendation | Conditions |
|---|---|---|
| >= 70 | `buy` | All hard rules pass, data confidence >= medium |
| 50-69 | `watchlist` | OR: score >= 70 but a hard rule blocks buy |
| < 50 | `no_buy` | OR: critical red flags present |

Set `confidence`:
- `high` — all key data available, scores converge, no contradictions
- `medium` — minor data gaps or mixed signals
- `low` — significant data gaps, contradictory signals, stale data

### Step 6: Build Decision Summary

- `bull_case`: 2-4 strongest positive factors with numbers
- `bear_case`: 2-4 strongest risk factors with numbers
- `main_reason_for_recommendation`: one sentence, the single most important factor
- `what_would_change_the_decision`: 2-3 specific, measurable conditions

### Step 7: Output Strict JSON

Return **only** the JSON object. No markdown fences, no prose, no commentary outside the JSON.

See [output-schema.json](output-schema.json) for the complete schema.

```json
{
  "ticker": "",
  "exchange": "",
  "company_name": null,
  "currency": null,
  "analysis_date": "YYYY-MM-DD",
  "time_horizon": "long_term_1y_plus",
  "recommendation": "buy|watchlist|no_buy",
  "confidence": "low|medium|high",
  "overall_score": 0,
  "scores": { "..." : "..." },
  "key_metrics": { "..." : "..." },
  "decision_summary": { "..." : "..." },
  "red_flags": [],
  "data_quality": { "..." : "..." },
  "sources": []
}
```

## Key Principles

1. **EODHD is the sole data source.** All financial data comes from EODHD (MCP tools or REST API). No other financial data providers.
2. **Fundamental-first.** Technicals confirm; they never drive the recommendation.
3. **Per-share economics matter.** Always check diluted share count trends from `outstandingShares.annual`.
4. **Cash flow is king.** Earnings not backed by FCF are suspect.
5. **Valuation is relative to growth.** A high P/E with high sustainable growth may be fair.
6. **Be honest about missing data.** If EODHD returns null, report it. Never fill gaps with assumptions.
7. **Separate quality from price.** A great business at the wrong price is a watchlist.
8. **Determinism where possible.** Use the bundled scripts for reproducible metric calculations and scoring. The scripts implement the exact same rubric as scoring-methodology.md.

## Additional Resources

- [scoring-methodology.md](scoring-methodology.md) — detailed scoring rubric for each category
- [hard-rules.md](hard-rules.md) — hard decision rules and red flag taxonomy
- [eodhd-endpoints.md](eodhd-endpoints.md) — EODHD API/MCP reference and field mapping
- [output-schema.json](output-schema.json) — complete JSON output schema
- `scripts/` — deterministic Python scripts for analysis, scoring, and validation
