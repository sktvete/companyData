# Free Source Inventory

## SEC EDGAR

- Role: primary US fundamentals and filing-timing source
- Surfaces:
  - `companyfacts`
  - `submissions`
  - filing archives
  - financial statement data sets
- Access pattern: public HTTP + downloadable bulk files
- Strengths:
  - official US filing provenance
  - filing dates and accession numbers
  - point-in-time timing support stronger than most free sources
- Weaknesses:
  - concept mapping and normalization are parsing-heavy
  - not all companies report every field cleanly
  - share counts and debt concepts may require interpretation
- Markets: US issuers

## SEC Financial Statement Data Sets

- Role: bulk/offline US fundamentals ingestion
- Access pattern: downloadable data sets
- Strengths:
  - offline-friendly
  - good for batch ingestion and reproducibility
- Weaknesses:
  - more engineering work than calling a paid normalized API
  - concept and dimensional mapping remain non-trivial

## Nasdaq Trader Symbol Directories

- Role: US listing and security-reference validation
- Access pattern: downloadable text files
- Strengths:
  - current listing metadata
  - useful for common-stock filtering and ETF exclusion
- Weaknesses:
  - current-state reference source, not a full historical identity system

## Stooq

- Role: free daily price prototype and cross-check source
- Access pattern: downloadable CSV-style historical data
- Strengths:
  - simple to ingest
  - good enough for early momentum and distance-from-high experiments
- Weaknesses:
  - adjustment semantics and licensing should be treated cautiously
  - weaker than institutional feeds for audit-grade historical claims

## OpenFIGI

- Role: identifier disambiguation and mapping experiments
- Access pattern: API
- Strengths:
  - helpful for cross-source identity matching
- Weaknesses:
  - live API dependency
  - not required for first offline proof

## yfinance

- Role: research and sanity-check source only
- Access pattern: library wrapper around Yahoo surfaces
- Weaknesses:
  - should not become a core dependency without explicit terms review

## ESEF / filings.xbrl.org

- Role: later European annual filing experiments
- Weaknesses:
  - parsing and coverage complexity
  - not suitable to block US-first Phase 0

## EDINET

- Role: later Japan official-filing experiment

## FRED / OECD / World Bank

- Role: future macro enrichment
- Status: not required for first sorter
