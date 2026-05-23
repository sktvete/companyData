# Hard Decision Rules

These rules **override** the numeric score. Apply them after scoring, before setting the recommendation.

## Buy Blockers

If any of these conditions are true, the recommendation **cannot** be `buy`. Downgrade to `watchlist` or `no_buy`.

1. **Missing valuation data.** If forward P/E, EPS estimates, and EV/EBITDA are all unavailable or clearly unreliable, do not recommend `buy`.

2. **Incomplete fundamental data.** If revenue, EPS, and FCF data are too sparse to judge the business (fewer than 2 years of data or all three are null), do not recommend `buy`.

3. **Severe dilution.** If diluted shares outstanding are growing >5% annualized with no clear path to reversal (e.g., pre-revenue biotech), do not recommend `buy`.

4. **Weak balance sheet.** If net debt / EBITDA > 4 and interest coverage < 3, do not recommend `buy` unless there is a very specific, quantified reason (e.g., recent acquisition with clear deleveraging timeline and strong FCF). State the reason explicitly.

5. **Hype-only thesis.** If the bull case relies on narrative (AI, metaverse, disruption) without visible revenue contribution or financial proof, do not recommend `buy`. Score the catalyst as hype (max 30).

6. **Momentum-only thesis.** If the stock is up >50% in 6 months but fundamentals (revenue, EPS, FCF) have not improved proportionally, do not recommend `buy` based on price action alone.

7. **Low P/E trap.** If P/E is low but revenue is declining, margins are contracting, or there are structural headwinds, do not recommend `buy` just because P/E is low. Flag it as a potential value trap.

## Mandatory Penalties

Apply these scoring adjustments before the final recommendation:

1. **Per-share dilution penalty.** If total revenue or earnings grow but per-share metrics (EPS, FCF/share) are flat or declining due to dilution, subtract 10 from `growth_score` and note in `bear_case`.

2. **Cash flow disconnect.** If EPS growth exceeds FCF growth by >20 percentage points, subtract 10 from `earnings_quality_score` and flag the disconnect.

3. **Margin deterioration.** If revenue grows >10% but operating margin contracts >200bps, subtract 10 from `quality_score`.

4. **SBC dilution.** If stock-based compensation exceeds 10% of revenue, subtract 5 from `balance_sheet_score` and add a red flag.

## Classification Logic

### "Great company but too expensive" → `watchlist`
- Quality score ≥ 70 AND growth score ≥ 60, BUT valuation score < 40
- The business is sound but the price does not offer margin of safety
- Explicitly state: "Business quality is strong but valuation is stretched"

### "Cheap for a real reason" → `no_buy`
- Valuation score ≥ 70 (looks cheap) BUT quality score < 40 OR growth score < 30
- The low price reflects deteriorating fundamentals
- Explicitly state: "Valuation appears attractive but reflects declining business quality"

### "Genuinely mispriced" → `buy`
- Quality score ≥ 60 AND growth score ≥ 55 AND valuation score ≥ 55
- No buy blockers triggered
- The market undervalues a business with solid or improving fundamentals

### "Broken business" → `no_buy`
- Multiple red flags (total penalty ≥ −15)
- Quality score < 35 OR growth score < 25
- Regardless of valuation

## Stale and Missing Data Rules

1. If fundamental data is more than 6 months old, mark affected fields in `stale_fields` and set `data_confidence` to `medium` at best.

2. If more than 5 key metrics are null, set `data_confidence` to `low`.

3. If `data_confidence` is `low`, the recommendation cannot be `buy`. Maximum is `watchlist` with explicit caveat.

4. Always prefer the most recent annual data. Use TTM (trailing twelve months) when available. Use quarterly data only to check for recent trend changes.

## Red Flag Taxonomy

### Financial Red Flags
- Declining revenue for 2+ years
- Negative FCF for 2+ years
- Gross margin below industry average and declining
- Accounting restatements
- Auditor changes or qualified opinions
- Unusual revenue recognition patterns

### Structural Red Flags
- Customer concentration (>30% of revenue from one customer)
- Single-product dependency with no pipeline
- Regulatory risk that could eliminate the business model
- Patent cliffs (pharma/biotech)

### Governance Red Flags
- Excessive executive compensation relative to company size
- Dual-class share structure that limits shareholder rights
- Related-party transactions
- Frequent C-suite turnover

### Market Red Flags
- Stock price >100% above 200 DMA (potential bubble)
- Trading volume spike without fundamental catalyst
- Short interest >20% of float
- Retail hype on social media without institutional support
