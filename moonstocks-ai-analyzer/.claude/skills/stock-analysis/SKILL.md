---
name: stock-analysis
description: >-
  Long-term fundamental stock analysis for US-listed equities. Produces strict
  JSON with buy/watchlist/no_buy recommendation, scored across growth, quality,
  valuation, balance sheet, earnings quality, catalysts, sentiment, technicals,
  and risk. Uses EODHD as the data source. Use when the user asks to analyze
  a stock, evaluate a ticker, or decide whether to buy a stock.
---

# Stock Analysis Skill

Analyze a US-listed stock and return a **strict valid JSON** verdict: `buy`, `watchlist`, or `no_buy`. Investment horizon is **1+ years**. This is fundamental-first analysis with technicals only as confirmation.

## Input

```json
{ "ticker": "NVDA", "exchange": "US" }
```

## Execution Workflow

### Step 1: Fetch All Data from EODHD MCP

All financial data must come from EODHD. No other financial data sources. No API key or auth handling needed — the MCP server manages authentication.

Call all four tools. Tools 2 and 3 can run in parallel with tool 1; tool 4 can run at any time.

1. **Fundamentals** (critical — provides ~80% of needed data):
   ```
   get_fundamentals_data(ticker="{TICKER}.{EXCHANGE}")
   ```
   Extract: General, Highlights, Valuation, SharesStats, Financials (Income_Statement, Balance_Sheet, Cash_Flow — yearly and quarterly), outstandingShares, InsiderTransactions, institutionalHolders, AnalystRatings, ESGScores.

2. **EOD prices** (1 year of daily data for technicals):
   ```
   get_historical_stock_prices(ticker="{TICKER}.{EXCHANGE}", start_date="{1Y_AGO}", end_date="{TODAY}", period="d")
   ```
   Compute from the returned array: 50-day SMA, 200-day SMA, 14-day RSI, 52-week high, drawdown.

3. **Live price** (current price):
   ```
   get_live_price_data(ticker="{TICKER}.{EXCHANGE}")
   ```

4. **Earnings trends** (analyst revisions for catalyst score):
   ```
   get_earnings_trends(symbols="{TICKER}.{EXCHANGE}")
   ```
   Provides EPS/revenue estimates, `epsTrend` (7/30/60/90 day snapshots), and `epsRevisions` (up/down counts) for forward-looking catalyst scoring.

See [eodhd-endpoints.md](eodhd-endpoints.md) for complete field mapping.

**Never hallucinate data.** If EODHD does not return a metric, set it to `null` and add it to `missing_fields`.

### Step 2: Extract Key Metrics

Compute every metric from the EODHD response. See [scoring-methodology.md](scoring-methodology.md) for calculation formulas.

**From Highlights:** market_cap, pe_ratio, peg_ratio, operating_margin, net_margin, eps, revenue TTM.
**From Valuation:** forward_pe, price_to_sales, ev_to_ebitda.
**From Financials.Income_Statement.yearly:** revenue (multi-year for YoY and 3Y CAGR), gross_profit (→ gross_margin), operating_income, net_income.
**From Financials.Balance_Sheet.yearly:** totalDebt, totalStockholderEquity, cash, totalAssets.
**From Financials.Cash_Flow.yearly:** totalCashFromOperatingActivities, capitalExpenditures (→ FCF = OCF − |CapEx|).
**From outstandingShares.annual:** share count trend for dilution check.
**From EOD prices:** 50 DMA, 200 DMA, RSI, price_vs_50dma (%), price_vs_200dma (%).

**Derived calculations:**
- `revenue_growth_yoy` = (latest_year_revenue / prior_year_revenue) − 1
- `revenue_cagr_3y` = (latest_year_revenue / three_years_ago_revenue)^(1/3) − 1
- `fcf` = totalCashFromOperatingActivities − |capitalExpenditures|
- `fcf_yield` = fcf / market_cap
- `fcf_per_share` = fcf / diluted_shares
- `roic` = NOPAT / invested_capital (or use Highlights.ReturnOnEquityTTM as proxy)
- `debt_to_equity` = totalDebt / totalStockholderEquity
- `net_debt_to_ebitda` = (totalDebt − cash) / EBITDA
- `interest_coverage` = operating_income / interestExpense

### Step 3: Score Each Category (0–100)

Apply the scoring rubric from [scoring-methodology.md](scoring-methodology.md). Each score is 0–100.

| Category | Weight | What It Measures |
|---|---|---|
| `growth_score` | 20% | Revenue growth, acceleration, FCF growth, EPS growth |
| `quality_score` | 20% | Margins, margin expansion, ROIC |
| `valuation_score` | 20% | P/E, forward P/E, PEG, EV/EBITDA, FCF yield, P/S vs growth |
| `balance_sheet_score` | 15% | Debt ratios, interest coverage, liquidity, dilution risk |
| `earnings_quality_score` | 10% | FCF vs net income, accruals, per-share economics |
| `catalyst_score` | 10% | Analyst estimates, insider transactions, institutional trends |
| `sentiment_score` | — | Insider buying, institutional trends (informational) |
| `technical_score` | 5% | Trend, MA position, RSI, drawdown context |
| `risk_red_flag_score` | — | Penalty score (0 = no flags, negative = red flags detected) |

`overall_score` = weighted sum of category scores + `risk_red_flag_score` penalty, clamped to 0–100.

### Step 4: Apply Hard Decision Rules

Read and apply every rule in [hard-rules.md](hard-rules.md). These override the score.

**Critical overrides (summarized):**
- **No `buy` if** valuation data is missing/unreliable, revenue/EPS/FCF too incomplete, severe dilution, weak balance sheet without strong justification, recommendation based only on hype/momentum/low P/E
- **Penalize** companies where growth is not visible per-share, EPS not supported by FCF, revenue grows but margins deteriorate
- **Separate** "great company but expensive" (watchlist) from "bad company" (no_buy)

### Step 5: Determine Recommendation

| overall_score | Recommendation | Conditions |
|---|---|---|
| ≥ 70 | `buy` | All hard rules pass, data confidence ≥ medium |
| 50–69 | `watchlist` | OR: score ≥ 70 but a hard rule blocks buy |
| < 50 | `no_buy` | OR: critical red flags present |

Set `confidence`:
- `high` — all key data available from EODHD, scores converge, no contradictions
- `medium` — minor data gaps or mixed signals
- `low` — significant data gaps, contradictory signals, stale data

### Step 6: Build Decision Summary

- `bull_case`: 2–4 strongest positive factors with numbers
- `bear_case`: 2–4 strongest risk factors with numbers
- `main_reason_for_recommendation`: one sentence, the single most important factor
- `what_would_change_the_decision`: 2–3 specific, measurable conditions

### Step 7: Output Strict JSON

Return **only** the JSON object below. No markdown fences, no prose, no commentary outside the JSON.

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
  "scores": { ... },
  "key_metrics": { ... },
  "decision_summary": { ... },
  "red_flags": [ ... ],
  "data_quality": { ... },
  "sources": [ ... ]
}
```

## Key Principles

1. **EODHD is the sole data source.** All financial metrics, fundamentals, prices, and technicals come from EODHD. No Yahoo Finance, no Macrotrends, no web scraping.
2. **Fundamental-first.** Technicals confirm; they never drive the recommendation.
3. **Per-share economics matter.** Always check diluted share count trends from `outstandingShares.annual`.
4. **Cash flow is king.** Earnings not backed by FCF are suspect.
5. **Valuation is relative to growth.** A high P/E with high sustainable growth may be fair.
6. **Be honest about missing data.** If EODHD returns null, report it. Never fill gaps with assumptions.
7. **Separate quality from price.** A great business at the wrong price is a watchlist.

## Additional Resources

- [scoring-methodology.md](scoring-methodology.md) — detailed scoring rubric for each category
- [hard-rules.md](hard-rules.md) — hard decision rules and red flag taxonomy
- [eodhd-endpoints.md](eodhd-endpoints.md) — EODHD API endpoint reference and field mapping
- [output-schema.json](output-schema.json) — complete JSON output schema
