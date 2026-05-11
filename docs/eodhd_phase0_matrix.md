# EODHD Phase 0 Matrix

Purpose: define the first provider boundary without leaking EODHD assumptions into canonical tables.

## Endpoints

| Domain | EODHD endpoint shape | Phase 0 use | Canonical target | Notes |
| --- | --- | --- | --- | --- |
| Exchange listings | `exchange-symbol-list/{EXCHANGE}` | Required | `companies`, `securities`, `listings`, `identifiers` | Use dynamic exchange lists; do not hard-code coverage. |
| Daily prices | `eod/{SYMBOL}.{EXCHANGE}` | Required | `prices_daily` | Keep close and adjusted close separate. |
| Fundamentals | `fundamentals/{SYMBOL}.{EXCHANGE}` | Required | `fundamentals_quarterly`, `sector_classification` | Filing date quality may vary. |
| Splits | `splits/{SYMBOL}.{EXCHANGE}` | Phase 0 optional | `corporate_actions` | Use when available to validate price continuity. |
| Dividends | `div/{SYMBOL}.{EXCHANGE}` | Phase 0 optional | `corporate_actions` | Separate from split logic. |
| Bulk fundamentals | provider bulk endpoint | Investigate entitlement | bronze batch ingest | Log plan dependency before relying on it. |

## Core field mapping

| Provider field | Canonical field | Rule | Nullable | Notes |
| --- | --- | --- | --- | --- |
| `Code` | `ticker` | direct | no | Local listing symbol only. |
| `Name` | `legal_name` | direct | no | Fallback to ticker if missing. |
| `Country` | `country` | direct | yes | Keep provider value as-is in Phase 0. |
| `Currency` | `currency` | direct | yes | FX normalization later. |
| `ISIN` | `identifiers.id_value` | map to `isin` | yes | Optional evidence, not primary identity. |
| `Type` | `security_type` | direct | yes | Provider-specific naming isolated at adapter boundary. |
| `date` | `prices_daily.date` | direct | no | ISO date expected. |
| `close` | `prices_daily.close` | numeric cast | yes | Raw close. |
| `adjusted_close` | `prices_daily.adjusted_close` | numeric cast | yes | Provider adjustment method must stay labeled. |
| `totalRevenue` | `fundamentals_quarterly.revenue` | numeric cast | yes | Internal factors should use canonical fields only. |
| `grossProfit` | `fundamentals_quarterly.gross_profit` | numeric cast | yes | |
| `operatingIncome` | `fundamentals_quarterly.operating_income` | numeric cast | yes | |
| `ebit` | `fundamentals_quarterly.ebit` | numeric cast | yes | |
| `netIncome` | `fundamentals_quarterly.net_income` | numeric cast | yes | |
| `filing_date` | `fundamentals_quarterly.filing_date` | direct | yes | Phase 0 timing confidence depends on this. |
| `accepted_date` | `fundamentals_quarterly.accepted_timestamp` | direct | yes | Useful when present. |

## Known Phase 0 risks

1. Filing and acceptance timestamps may be incomplete outside some markets.
2. Bulk fundamentals may depend on plan entitlement.
3. Sector and industry labels may be sparse or provider-shaped.
4. Adjusted price methodology needs explicit lineage before backtest claims.
5. Delisted coverage should be treated as exploratory until validated.
