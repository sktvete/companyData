# EODHD Data Reference

This document covers both the EODHD MCP tools (preferred) and the direct REST API (fallback). The MCP server exposes 77 tools; this reference focuses on the ones relevant to stock analysis.

## Symbol Format

EODHD uses `SYMBOL.EXCHANGE` everywhere:
- US stocks: `AAPL.US`, `MSFT.US`, `NVDA.US`, `TSLA.US`
- Other exchanges: `SAP.XETRA`, `SHOP.TO`, `7203.TSE`
- Forex: `EURUSD.FOREX`
- Crypto: `BTC-USD.CC`

If the user gives just a ticker like "NVDA", assume `.US`. If uncertain, resolve it first.

## API Key

Scripts and REST fallback load the key from the `EODHD_API_KEY` environment variable. All REST endpoints require `?api_token={KEY}&fmt=json`.

The MCP server handles authentication automatically — no key needed in MCP tool calls.

---

## Table of Contents

1. [Fundamentals](#1-fundamentals)
2. [EOD Prices](#2-eod-prices)
3. [Live / Real-Time Price](#3-live--real-time-price)
4. [Technical Indicators](#4-technical-indicators)
5. [News & Sentiment](#5-news--sentiment)
6. [Dividends & Splits](#6-dividends--splits)
7. [Ticker Search / Resolution](#7-ticker-search--resolution)
8. [Fundamentals Field Mapping](#8-fundamentals-field-mapping)
9. [Technical Calculations from EOD Prices](#9-technical-calculations-from-eod-prices)

---

## 1. Fundamentals

The single most important call. Provides financials, valuation, earnings, holders, and share data.

### MCP (preferred)

```
get_fundamentals_data(
    ticker="AAPL.US",
    sections=["Highlights", "Valuation", "SharesStats", "Financials",
              "Earnings", "outstandingShares", "InsiderTransactions",
              "Holders", "AnalystRatings"]
)
```

The `sections` parameter filters the response to only the sections you need, reducing token usage significantly.

### REST API

**Recommended (v1.1):**
```
GET https://eodhd.com/api/v1.1/fundamentals/AAPL.US?api_token={KEY}&fmt=json
```

v1.1 fixes missing Q4 data in Earnings Trend and splits Earnings Trend into Quarterly/Annual sections. Use v1.1 for all new work.

**Legacy (still works):**
```
GET https://eodhd.com/api/fundamentals/AAPL.US?api_token={KEY}&fmt=json
```

### Filters (REST)

The full fundamentals response can be very large. Use `filter=` to fetch only what you need. Filter layers are separated by `::`.

```
# Single section
?filter=Highlights&api_token={KEY}&fmt=json

# Nested field
?filter=Financials::Balance_Sheet::yearly&api_token={KEY}&fmt=json

# Multiple sections (comma-separated)
?filter=Highlights,Valuation,Financials&api_token={KEY}&fmt=json

# Specific field
?filter=General::Code&api_token={KEY}&fmt=json
```

**Recommended filter for stock analysis (balances completeness vs size):**
```
?filter=Highlights,Valuation,SharesStats,Financials,Earnings,outstandingShares,InsiderTransactions,AnalystRatings&api_token={KEY}&fmt=json
```

---

## 2. EOD Prices

Daily/weekly/monthly OHLCV history. Used for technical calculations.

### MCP

```
get_historical_stock_prices(
    ticker="AAPL.US",
    start_date="2025-05-14",
    end_date="2026-05-14",
    period="d"
)
```

### REST

```
GET https://eodhd.com/api/eod/AAPL.US?from=2025-05-14&to=2026-05-14&period=d&api_token={KEY}&fmt=json
```

Returns array of `{ date, open, high, low, close, adjusted_close, volume }`.

---

## 3. Live / Real-Time Price

Current price snapshot (delayed ~15-20 min).

### MCP

```
get_live_price_data(ticker="AAPL.US")
```

### REST

```
GET https://eodhd.com/api/real-time/AAPL.US?api_token={KEY}&fmt=json
```

Returns `{ code, timestamp, gmtoffset, open, high, low, close, volume, previousClose, change, change_p }`.

---

## 4. Technical Indicators

Server-side computed indicators. Each call consumes 5 API calls.

### MCP

```
get_technical_indicators(ticker="AAPL.US", function="sma", period=50)
get_technical_indicators(ticker="AAPL.US", function="sma", period=200)
get_technical_indicators(ticker="AAPL.US", function="rsi", period=14)
```

Supported functions: `sma`, `ema`, `wma`, `macd`, `rsi`, `stochastic`, `stochrsi`, `bbands`, `atr`, `adx`, `dmi`, `cci`, `sar`, `beta`, `volatility`, `avgvol`.

### REST

```
GET https://eodhd.com/api/technical/AAPL.US?function=sma&period=50&api_token={KEY}&fmt=json
GET https://eodhd.com/api/technical/AAPL.US?function=rsi&period=14&api_token={KEY}&fmt=json
```

**Note:** The technical endpoint can return large responses. Use `filter=last_sma` (or `last_rsi`, etc.) to get only the most recent value. Or compute indicators yourself from EOD price data — see [section 9](#9-technical-calculations-from-eod-prices).

---

## 5. News & Sentiment

### MCP

```
get_company_news(ticker="AAPL.US", limit=20)
get_sentiment_data(ticker="AAPL.US")
```

### REST

```
GET https://eodhd.com/api/news?s=AAPL.US&limit=20&api_token={KEY}&fmt=json
GET https://eodhd.com/api/sentiments?s=AAPL.US&api_token={KEY}&fmt=json
```

News returns articles with title, content, date, and related tickers. Sentiment returns aggregated positive/negative/neutral scores.

---

## 6. Dividends & Splits

### MCP

```
get_historical_dividends(ticker="AAPL.US")
get_historical_splits(ticker="AAPL.US")
```

### REST

```
GET https://eodhd.com/api/div/AAPL.US?api_token={KEY}&fmt=json
GET https://eodhd.com/api/splits/AAPL.US?api_token={KEY}&fmt=json
```

These are supplementary — dividend and split history is also embedded in the fundamentals response under `SplitsDividends`.

---

## 7. Ticker Search / Resolution

### MCP

```
resolve_ticker(query="Apple")
```

Converts company name, partial ticker, or ISIN to `SYMBOL.EXCHANGE`. Returns top 10 matches with exchange details.

### REST

```
GET https://eodhd.com/api/search/AAPL?api_token={KEY}&fmt=json
```

---

## 8. Fundamentals Field Mapping

### Highlights → key_metrics

| EODHD Field | Maps To |
|---|---|
| `Highlights.MarketCapitalization` | `market_cap` |
| `Highlights.PERatio` | `pe_ratio` |
| `Highlights.PEGRatio` | `peg_ratio` |
| `Highlights.EarningsShare` | current diluted EPS |
| `Highlights.EPSEstimateCurrentYear` | forward EPS (for forward_pe calc) |
| `Highlights.ProfitMargin` | `net_margin` |
| `Highlights.OperatingMarginTTM` | `operating_margin` |
| `Highlights.ReturnOnEquityTTM` | quality context / ROIC proxy |
| `Highlights.RevenueTTM` | revenue context |
| `Highlights.RevenuePerShareTTM` | revenue per share |
| `Highlights.QuarterlyRevenueGrowthYOY` | recent revenue growth signal |
| `Highlights.QuarterlyEarningsGrowthYOY` | recent earnings growth signal |
| `Highlights.EBITDA` | EBITDA for EV/EBITDA and debt ratios |

### Valuation → key_metrics

| EODHD Field | Maps To |
|---|---|
| `Valuation.ForwardPE` | `forward_pe` |
| `Valuation.PriceSalesTTM` | `price_to_sales` |
| `Valuation.EnterpriseValueEbitda` | `ev_to_ebitda` |
| `Valuation.EnterpriseValue` | enterprise value for calculations |
| `Valuation.TrailingPE` | trailing P/E cross-check |

### SharesStats → dilution check

| EODHD Field | Maps To |
|---|---|
| `SharesStats.SharesOutstanding` | current shares |
| `SharesStats.PercentInsiders` | insider ownership % |
| `SharesStats.PercentInstitutions` | institutional ownership % |

### Financials.Income_Statement.yearly → growth, margins

Extract the last 4 years. Each year has:
- `totalRevenue` → revenue (compute YoY growth, 3Y CAGR)
- `grossProfit` → gross_margin = grossProfit / totalRevenue
- `operatingIncome` → operating margin confirmation
- `netIncome` → net margin confirmation, FCF/NI ratio
- `interestExpense` → interest_coverage = operatingIncome / interestExpense

### Financials.Balance_Sheet.yearly → balance sheet score

- `totalDebt` or `shortLongTermDebt` + `longTermDebt`
- `totalStockholderEquity` → debt_to_equity = totalDebt / equity
- `cash` or `cashAndShortTermInvestments` → for net debt calc
- `totalAssets` → for accruals check

### Financials.Cash_Flow.yearly → FCF, earnings quality

- `totalCashFromOperatingActivities` → operating cash flow
- `capitalExpenditures` → CapEx (usually negative in EODHD)
- **FCF** = totalCashFromOperatingActivities - |capitalExpenditures|
- **FCF yield** = FCF / market_cap
- **FCF/NI ratio** = FCF / netIncome

### outstandingShares.annual → dilution risk

Array of `{ date, shares }` objects. Compare latest vs 1Y ago and 3Y ago:
- Growing >3%/yr → dilution penalty
- Growing >5%/yr → severe dilution (buy blocker)
- Shrinking → buyback premium

### InsiderTransactions → sentiment

Array of transactions. Count net buys vs sells in last 12 months. Heavy net selling = negative signal.

### Holders → sentiment

Top institutional and fund holders with shares and weight. Note any significant changes.

### AnalystRatings → catalyst

`AnalystRatings.Rating` — consensus rating and target price. Check for recent estimate revisions.

---

## 9. Technical Calculations from EOD Prices

If you prefer computing indicators locally (avoids 5-API-call cost of `/technical/`), use the EOD prices array:

**50-day SMA:** average of last 50 `adjusted_close` values.
**200-day SMA:** average of last 200 `adjusted_close` values.
**price_vs_50dma:** `(current_price / sma_50 - 1) * 100` (percentage).
**price_vs_200dma:** `(current_price / sma_200 - 1) * 100` (percentage).

**14-day RSI:** standard Wilder RSI formula:
1. Calculate daily price changes from `adjusted_close`.
2. Separate gains and losses over first 14 days.
3. Average gain = sum(gains) / 14, average loss = sum(losses) / 14.
4. For subsequent days: avg_gain = (prev_avg_gain * 13 + current_gain) / 14.
5. RS = avg_gain / avg_loss. RSI = 100 - (100 / (1 + RS)).

**52-week high:** max `high` in the dataset.
**Drawdown from 52W high:** `(current_price / 52w_high - 1) * 100`.

The `scripts/metrics.py` module implements all of these calculations deterministically.
