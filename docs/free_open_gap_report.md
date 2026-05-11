# Free/Open Gap Report

## What works well in the current free-first design

1. US fundamentals can be anchored to official SEC filings.
2. Filing dates and accession-linked provenance can be preserved.
3. Current US listing metadata can be validated from Nasdaq Trader files.
4. Free daily prices are sufficient for a first momentum and drawdown prototype.
5. A reproducible bronze to silver to gold flow does not require paid APIs.

## What is weak or incomplete

1. Price adjustment semantics from free sources are often unclear.
2. Historical US listing state and delisting coverage are weaker than paid reference feeds.
3. Global non-US fundamentals are much harder to source cleanly for free.
4. XBRL concept mapping for debt, shares, and statement subtotals can be ambiguous.
5. Some factors need data that is sparse or noisy in free sources.

## What likely requires paid data later

1. broad global daily prices with clear licensing and adjustment semantics
2. broad global quarterly fundamentals with normalized identifiers
3. historical delisted coverage suitable for backtesting claims
4. institutional-grade point-in-time reference and constituent history
5. cross-market corporate actions and share-class mapping

## Fields not automatically point-in-time-safe

1. free price series with unclear revision behavior
2. derived market cap when shares are stale
3. any fundamental field lacking filing-date linkage
4. vendor-style adjusted data without explicit methodology

## Markets realistic for free-first support

1. US

## Markets worth researching later but not blocking Phase 0

1. Europe and Nordics via ESEF
2. Japan via EDINET

## Current recommendation

Use the free-first stack to prove the engine honestly. Add paid providers later for coverage, cleaner historical reference data, and stronger backtesting support.
