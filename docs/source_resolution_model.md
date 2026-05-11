# Source Resolution Model

The engine is not a vendor wrapper. Every canonical field can preserve multiple source candidates.

## Candidate record shape

Each candidate stores:

- `table_name`
- `entity_id`
- `field_name`
- `value`
- `source`
- `source_record_id`
- `period`
- `report_date`
- `filing_date`
- `ingestion_timestamp`
- `confidence`
- `pit_safe`
- `license_class`
- `method`
- `selected_flag`
- `selection_reason`

## Default source priority

Fundamentals:

1. official filing source
2. exchange or regulator source
3. paid provider
4. free market-data source
5. internally derived estimate

Prices:

1. paid provider with clear license and adjustment semantics
2. official or exchange source where practically accessible
3. public free validation source
4. derived or approximate series

## Phase 0 free-first baseline

- `sec_edgar` for US fundamentals and filing timing
- `nasdaq_trader` for US listing reference validation
- `stooq` for free price-history experiments
- optional `openfigi` for mapping experiments

## Selection rule

Selection should be explicit and reversible. Candidate rows are never silently overwritten by a later source.
