# Scoring Methodology

Each category is scored 0–100. Apply the ranges below. If a required metric is `null`, score that sub-component at 40 (neutral-low) and note it in `missing_fields`.

## Growth Score (20% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Revenue growth YoY | 30% | >30% → 90–100, 15–30% → 70–89, 5–15% → 50–69, 0–5% → 30–49, negative → 0–29 |
| Revenue CAGR 3Y | 20% | >25% → 90–100, 12–25% → 70–89, 5–12% → 50–69, 0–5% → 30–49, negative → 0–29 |
| Revenue acceleration | 10% | Accelerating (latest YoY > prior YoY) → +15 bonus, decelerating → −10 penalty |
| EPS growth YoY | 20% | >25% → 90–100, 10–25% → 70–89, 0–10% → 50–69, negative → 0–29 |
| FCF growth YoY | 10% | >25% → 90–100, 10–25% → 70–89, 0–10% → 50–69, negative → 0–29 |
| FCF per share growth | 10% | >20% → 90–100, 10–20% → 70–89, 0–10% → 50–69, negative → 0–29 |

**Penalty:** If EPS grows >15% but FCF is flat or negative, apply −15 penalty to growth score (earnings quality concern).

## Quality Score (20% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Gross margin | 25% | >60% → 90–100, 40–60% → 70–89, 25–40% → 50–69, 15–25% → 30–49, <15% → 0–29 |
| Operating margin | 25% | >25% → 90–100, 15–25% → 70–89, 8–15% → 50–69, 0–8% → 30–49, negative → 0–29 |
| Net margin | 15% | >20% → 90–100, 10–20% → 70–89, 5–10% → 50–69, 0–5% → 30–49, negative → 0–29 |
| Margin trend | 15% | Expanding (YoY improvement in operating margin) → 80–100, stable → 50–70, contracting → 0–40 |
| ROIC | 20% | >25% → 90–100, 15–25% → 70–89, 8–15% → 50–69, 0–8% → 30–49, negative → 0–29 |

**Penalty:** If revenue grows but operating margin contracts >200bps YoY, apply −10 penalty.

## Valuation Score (20% weight)

Valuation is scored **relative to growth**. A high-growth company deserves a higher multiple.

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Forward P/E vs growth | 30% | PEG <1 → 90–100, 1–1.5 → 70–89, 1.5–2.5 → 50–69, 2.5–3.5 → 30–49, >3.5 → 0–29 |
| EV/EBITDA | 20% | <10 → 90–100, 10–15 → 70–89, 15–25 → 50–69, 25–40 → 30–49, >40 → 0–29 |
| FCF yield | 20% | >6% → 90–100, 4–6% → 70–89, 2–4% → 50–69, 0–2% → 30–49, negative → 0–29 |
| P/S vs growth | 15% | P/S-to-revenue-growth ratio <0.5 → 90–100, 0.5–1 → 70–89, 1–2 → 50–69, >2 → 30–49 |
| Trailing P/E context | 15% | Below 5Y avg → +10 bonus, above 5Y avg by >20% → −10 penalty |

**Important:** If forward P/E or EPS estimates are unavailable, cap the valuation score at 50 and note missing data. Do not recommend `buy` on trailing multiples alone.

## Balance Sheet Score (15% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Debt-to-equity | 25% | <0.3 → 90–100, 0.3–0.8 → 70–89, 0.8–1.5 → 50–69, 1.5–3 → 30–49, >3 → 0–29 |
| Net debt / EBITDA | 25% | <1 → 90–100, 1–2 → 70–89, 2–3 → 50–69, 3–5 → 30–49, >5 → 0–29 |
| Interest coverage | 20% | >15 → 90–100, 8–15 → 70–89, 4–8 → 50–69, 2–4 → 30–49, <2 → 0–29 |
| Dilution risk | 30% | Shares decreasing (buybacks) → 90–100, flat (±1%) → 70–80, growing 1–3% → 40–60, growing >3% → 0–30 |

**Net cash companies:** If net debt is negative (net cash position), award 95+ for the debt sub-metrics.

## Earnings Quality Score (10% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| FCF / Net Income ratio | 40% | >1.0 → 90–100, 0.8–1.0 → 70–89, 0.5–0.8 → 50–69, 0.2–0.5 → 30–49, <0.2 → 0–29 |
| FCF per diluted share trend | 30% | Growing consistently → 80–100, mixed → 50–70, declining → 0–40 |
| Accruals check | 15% | (Net Income − FCF) / Total Assets <5% → 80–100, 5–10% → 50–79, >10% → 0–49 |
| One-time items | 15% | No significant one-time gains → 80–100, one-time items >10% of net income → 0–49 |

## Catalyst Score (10% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Analyst estimate revisions | 30% | Upward revisions (last 90 days) → 80–100, stable → 50–60, downward → 0–40 |
| Product/market catalysts | 25% | Strong identifiable catalysts with financial impact → 80–100, moderate → 50–70, none → 30–50 |
| Sector/macro tailwind | 25% | Structural tailwind → 80–100, neutral → 50, headwind → 0–40 |
| Insider/institutional signals | 20% | Net insider buying → 80–100, neutral → 50, net selling → 20–40 |

**Rule:** Pure hype without financial connection scores 30 max. "AI play" without revenue proof = hype.

## Technical Score (5% weight)

| Sub-metric | Weight within category | Scoring |
|---|---|---|
| Price vs 200 DMA | 35% | Above, trending up → 80–100, above flat → 60–70, below → 30–50, well below (>20%) → 0–29 |
| Price vs 50 DMA | 25% | Above → 70–100, below → 30–60 |
| RSI (14-day) | 20% | 40–60 → 70–80 (neutral), 30–40 → 80–90 (oversold opportunity), 60–70 → 60–70, >70 → 40–50 (overbought risk), <30 → check if distressed |
| Drawdown from 52W high | 20% | <10% → 70–80, 10–20% → 60–70, 20–40% → 50–60 (potential value), >40% → investigate why |

**Rule:** Technical score never overrides fundamentals. Max +5 to overall for strong technicals, max −5 for weak.

## Risk / Red Flag Score (Penalty)

This is a **penalty deducted from overall_score**. Start at 0. Subtract points for each flag found.

| Red Flag | Severity | Penalty |
|---|---|---|
| Severe dilution (shares growing >5% YoY) | high | −10 |
| FCF negative for 2+ consecutive years | high | −10 |
| Declining revenue 2+ consecutive years | high | −8 |
| Operating margin contracting 3+ years | high | −8 |
| Net debt / EBITDA > 5 | high | −8 |
| Interest coverage < 2 | high | −7 |
| Accounting restatements or SEC investigation | high | −15 |
| EPS growth driven entirely by buybacks, not revenue | medium | −5 |
| Customer concentration >30% single customer | medium | −5 |
| Revenue growth but negative FCF | medium | −5 |
| High stock-based compensation (>10% of revenue) | medium | −5 |
| Legal/regulatory risk with material exposure | medium | −5 |
| One-time earnings spikes (>20% of net income) | medium | −4 |
| Management turnover (CEO/CFO change) | low | −3 |
| Insider selling >$10M in 90 days with no buying | low | −3 |

Cap total penalty at −40. The overall score cannot go below 0.

## Overall Score Calculation

```
weighted_score = (growth_score × 0.20)
              + (quality_score × 0.20)
              + (valuation_score × 0.20)
              + (balance_sheet_score × 0.15)
              + (earnings_quality_score × 0.10)
              + (catalyst_score × 0.10)
              + (technical_score × 0.05)

overall_score = clamp(weighted_score + risk_red_flag_score, 0, 100)
```

Round all scores to the nearest integer.
