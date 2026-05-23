# EODHD MCP Tool Reference

All data is fetched via EODHD MCP tools. No API key handling required — the MCP server manages authentication. Pass ticker symbols in `SYMBOL.EXCHANGE` format (e.g., `AAPL.US`).

## MCP Tool Reference

### 1. Fundamentals

```
get_fundamentals_data(ticker="{TICKER}.{EXCHANGE}")
```

Returns: General, Highlights, Valuation, SharesStats, Technicals, SplitsDividends, AnalystRatings, Holders, InsiderTransactions, outstandingShares, Earnings, Financials (Balance_Sheet / Cash_Flow / Income_Statement — quarterly & yearly), ESGScores.

### 2. Historical Prices

```
get_historical_stock_prices(
  ticker="{TICKER}.{EXCHANGE}",
  start_date="{1Y_AGO}",   # YYYY-MM-DD
  end_date="{TODAY}",       # YYYY-MM-DD
  period="d"
)
```

Returns an array of `{ date, open, high, low, close, adjusted_close, volume }`. Use this array to compute SMA, RSI, 52-week high, and drawdown (see calculations below).

### 3. Live Price

```
get_live_price_data(ticker="{TICKER}.{EXCHANGE}")
```

Returns: `close` (last trade price), `change`, `change_p`, `volume`, `high`, `low`, `open`, `previousClose`, `timestamp`.

### 4. Earnings Trends

```
get_earnings_trends(symbols="{TICKER}.{EXCHANGE}")
```

Returns an array of trend records per fiscal period. Key fields for catalyst scoring:

| Field | Use |
|---|---|
| `earningsEstimate.avg` | Consensus EPS estimate |
| `revenueEstimate.avg` | Consensus revenue estimate |
| `earningsEstimate.growth` | Expected EPS growth |
| `revenueEstimate.growth` | Expected revenue growth |
| `epsTrend.current` | Current consensus EPS |
| `epsTrend.7daysAgo` / `30daysAgo` | Recent revision direction |
| `epsRevisions.upLast7days` | Analyst upgrades last 7 days |
| `epsRevisions.downLast7days` | Analyst downgrades last 7 days |
| `epsRevisions.upLast30days` | Analyst upgrades last 30 days |
| `epsRevisions.downLast30days` | Analyst downgrades last 30 days |

---

## Fundamentals Response — Field Mapping

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
- `capitalExpenditures` → CapEx (usually negative)
- **FCF** = totalCashFromOperatingActivities − |capitalExpenditures|
- **FCF yield** = FCF / market_cap
- **FCF/NI ratio** = FCF / netIncome

### outstandingShares.annual → dilution risk
Array of `{ date, shares }` objects. Compare latest vs 1Y ago and 3Y ago:
- Growing >3%/yr → dilution penalty
- Growing >5%/yr → severe dilution (buy blocker)
- Shrinking → buyback premium

### InsiderTransactions → sentiment
Array of transactions. Count net buys vs sells in last 12 months. Heavy net selling = negative signal.

### institutionalHolders → sentiment
Top holders and ownership percentages. Note any significant changes.

### AnalystRatings → catalyst
`AnalystRatings.Rating` — consensus rating and target price. Supplement with `get_earnings_trends` for revision direction.

---

## Historical Prices — Technical Calculations

From the daily price array returned by `get_historical_stock_prices`, compute:

**50-day SMA:** average of last 50 `adjusted_close` values.
**200-day SMA:** average of last 200 `adjusted_close` values.
**price_vs_50dma:** `(current_price / sma_50 - 1) * 100` (percentage).
**price_vs_200dma:** `(current_price / sma_200 - 1) * 100` (percentage).
**14-day RSI:** standard RSI formula using 14-day gains/losses on `adjusted_close`.
**52-week high:** max `high` in the dataset. Drawdown = `(current_price / 52w_high - 1) * 100`.

---

## Sources Array

Record each MCP tool call in the output `sources` array, e.g.:
```json
[
  "eodhd:get_fundamentals_data:{TICKER}.{EXCHANGE}",
  "eodhd:get_historical_stock_prices:{TICKER}.{EXCHANGE}",
  "eodhd:get_live_price_data:{TICKER}.{EXCHANGE}",
  "eodhd:get_earnings_trends:{TICKER}.{EXCHANGE}"
]
```
