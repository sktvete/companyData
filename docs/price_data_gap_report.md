# Price Data Gap Report

## Current state

The system can rank on non-synthetic imported prices for small samples, but a broad free/public US daily price universe remains the main coverage blocker.

## What worked

1. Generic local CSV import with explicit mapping and manifests.
2. Non-synthetic imported monthly close data from an open dataset for a small sample.
3. Honest propagation of price status, adjustment status, and price confidence into ranking rows.

## What did not scale cleanly

1. `Stooq` historical CSV access now requires API key or captcha in this environment.
2. Direct Yahoo historical downloads returned authentication errors.
3. Open datasets accessible without friction were narrow or low-frequency.

## Current tradeoff decision

Because free price coverage is weaker than free official fundamentals, the next scaled milestone is `Fundamentals-Only US Ranking v1` plus this gap report rather than a misleading 100+ name price-backed rank.

## Required properties for the eventual price source

1. legal to store locally
2. enough universe breadth for 100+ US names
3. at least close history, preferably daily OHLCV
4. explicit adjustment semantics
5. automation possible without interactive captcha

## Current supported price statuses

- `real_imported_adjusted`
- `real_imported_unadjusted_or_unknown`
- `synthetic_demo`
- `missing`
