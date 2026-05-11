# US Free Phase 0 Plan

## Objective

Build a reproducible US stock-sorting prototype using no paid market-data provider.

## Baseline free sources

- SEC EDGAR
- SEC Financial Statement Data Sets
- Nasdaq Trader symbol files
- Stooq

## First deliverables

1. bronze raw storage for SEC, Nasdaq Trader, and Stooq inputs
2. normalized `companies`, `securities`, `listings`, `prices_daily`, `fundamentals_quarterly`
3. `source_candidates` provenance table
4. one month-end factor snapshot
5. one GARP ranking with explanation columns
6. free/open gap report

## First supported factors

- revenue_ttm
- net_income_ttm
- operating_income_ttm
- operating_cash_flow_ttm
- capex_ttm
- free_cash_flow_ttm
- cash
- debt
- equity
- shares_outstanding when available
- market_cap when derivable
- gross_margin
- operating_margin
- earnings_yield
- fcf_yield
- revenue_growth_1y
- momentum_12m_ex_1m
- distance_from_52w_high
