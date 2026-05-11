#!/usr/bin/env python3
"""
Re-score existing companies using fixed investment scoring.
Uses only reliable metrics from existing scaled_analysis.jsonl.
Produces corrected scores across all 88 companies.
"""

import sys, json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.io_utils import read_jsonl, write_jsonl, write_json

OUTPUT_DIR = PROJECT_ROOT / "outputs"


def reliable_rescore(company: dict) -> dict:
    """
    Re-derive investment scores using only verified reliable metrics.
    Skips fields that were broken by wrong field names (OCF, EPS, FCF from price).
    """
    m = company.get("financial_metrics", {})
    ci = company.get("company_info", {})

    # ── Helpers ──────────────────────────────────────────────────────────────
    def get(key, default=0.0):
        v = m.get(key, ci.get(key, default))
        return float(v) if v is not None else default

    def clamp(v, lo=0.0, hi=5.0):
        return max(lo, min(hi, v))

    # ── Reliable fields ───────────────────────────────────────────────────────
    roe              = get("roe")               # verified ✓
    roa              = get("roa")               # verified ✓
    roic             = get("roic")              # verified ✓
    rev_growth       = get("revenue_growth_1y") # verified ✓
    rev_cagr         = get("revenue_cagr_3y", get("revenue_cagr_4y"))  # verified ✓
    altman_z         = get("altman_z_score")    # verified ✓ (needs market cap which was synthetic but pattern holds)
    cr               = get("current_ratio")     # verified ✓
    dte              = get("debt_to_equity")     # verified ✓
    piotroski        = get("piotroski_score")    # partially verified (2/9 criteria broken)
    gross_margin     = get("gross_margin")       # verified ✓
    net_margin       = get("net_margin")         # verified ✓
    operating_margin = get("operating_margin")   # verified ✓
    ps_ratio         = get("ps_ratio")           # partially reliable (market_cap from EODHD Highlights)
    pb_ratio         = get("pb_ratio")           # market_cap from highlights / book value ✓
    red_flags        = get("red_flag_count")
    net_income       = get("net_income")
    revenue          = get("revenue")
    ocf              = get("operating_cash_flow")   # 0 for most — will skip
    fcf              = get("free_cash_flow")         # derived from OCF so 0 — skip

    # Use company_info PE which came from EODHD Highlights (correct)
    pe_ratio = float(ci.get("pe_ratio", 0) or 0)

    # ── Quality (0–5) ─────────────────────────────────────────────────────────
    q = 0.0
    if roe >= 0.30:    q += 2.0
    elif roe >= 0.20:  q += 1.5
    elif roe >= 0.12:  q += 1.0

    if gross_margin >= 0.60: q += 1.5
    elif gross_margin >= 0.40: q += 1.0
    elif gross_margin >= 0.25: q += 0.5

    # Piotroski is 0-9 but max reliable is 7/9 (OCF criteria broken)
    # Map 0-7 → 0-1.5
    q += min(piotroski / 7.0 * 1.5, 1.5)

    # Net margin quality bonus
    if net_margin >= 0.20: q += 0.5
    elif net_margin >= 0.10: q += 0.25

    quality_score = clamp(q)

    # ── Value (0–5) ───────────────────────────────────────────────────────────
    v = 0.0
    if 0 < pe_ratio <= 10:     v += 2.5
    elif 0 < pe_ratio <= 15:   v += 2.0
    elif 0 < pe_ratio <= 22:   v += 1.5
    elif 0 < pe_ratio <= 30:   v += 1.0
    elif 0 < pe_ratio <= 40:   v += 0.5

    if 0 < pb_ratio <= 1.0:    v += 1.5
    elif 0 < pb_ratio <= 2.0:  v += 1.0
    elif 0 < pb_ratio <= 4.0:  v += 0.5

    if 0 < ps_ratio <= 1.0:    v += 1.0
    elif 0 < ps_ratio <= 3.0:  v += 0.5

    value_score = clamp(v)

    # ── Growth (0–5) — Owner Earnings proxy ───────────────────────────────────
    # Without reliable OCF we approximate OEPS growth via revenue CAGR and ROIC
    g = 0.0

    if rev_cagr >= 0.25:      g += 2.0
    elif rev_cagr >= 0.15:    g += 1.5
    elif rev_cagr >= 0.08:    g += 1.0
    elif rev_cagr >= 0.03:    g += 0.5

    if rev_growth >= 0.25:    g += 1.0
    elif rev_growth >= 0.10:  g += 0.5

    if roic >= 0.25:          g += 1.5
    elif roic >= 0.15:        g += 1.0
    elif roic >= 0.08:        g += 0.5

    if operating_margin >= 0.25: g += 0.5
    elif operating_margin >= 0.15: g += 0.25

    growth_score = clamp(g)

    # ── Safety (0–5) ──────────────────────────────────────────────────────────
    s = 5.0
    if altman_z > 0:
        if altman_z < 1.8:    s -= 3.0
        elif altman_z < 3.0:  s -= 1.5

    if cr > 0:
        if cr < 1.0:          s -= 2.0
        elif cr < 1.5:        s -= 1.0

    if dte > 4.0:             s -= 2.0
    elif dte > 2.5:           s -= 1.0
    elif dte > 1.5:           s -= 0.5

    if net_income < 0:        s -= 1.5
    if revenue <= 0:          s -= 2.0

    s -= min(red_flags * 0.5, 2.0)
    safety_score = clamp(s)

    # ── Final ─────────────────────────────────────────────────────────────────
    overall = quality_score + value_score + growth_score + safety_score

    if overall >= 16:   cat = "EXCELLENT"
    elif overall >= 12: cat = "GOOD"
    elif overall >= 8:  cat = "FAIR"
    elif overall >= 5:  cat = "POOR"
    else:               cat = "RISKY"

    return {
        "quality_score":  round(quality_score, 2),
        "value_score":    round(value_score, 2),
        "growth_score":   round(growth_score, 2),
        "safety_score":   round(safety_score, 2),
        "overall_score":  round(overall, 2),
        "investment_category": cat,
        # Keep growth breakdown for dashboard
        "oeps_cagr_pct":       round(m.get("oeps_cagr", 0) * 100, 2),
        "roic_pct":            round(roic * 100, 2),
        "revenue_cagr_3y_pct": round(rev_cagr * 100, 2),
        "gross_margin_pct":    round(gross_margin * 100, 2),
    }


_KNOWN_NAMES = {
    "AAPL":"Apple Inc","MSFT":"Microsoft Corporation","NVDA":"NVIDIA Corporation",
    "GOOGL":"Alphabet Inc","META":"Meta Platforms","AMZN":"Amazon.com",
    "TSLA":"Tesla Inc","V":"Visa Inc","MA":"Mastercard","JPM":"JPMorgan Chase",
    "JNJ":"Johnson & Johnson","UNH":"UnitedHealth Group","PG":"Procter & Gamble",
    "KO":"Coca-Cola Co","PEP":"PepsiCo","WMT":"Walmart","HD":"Home Depot",
    "MCD":"McDonald's","COST":"Costco","NKE":"Nike","DIS":"Walt Disney",
    "NFLX":"Netflix","ADBE":"Adobe","CRM":"Salesforce","ORCL":"Oracle",
    "IBM":"IBM","CSCO":"Cisco Systems","INTC":"Intel","AMD":"AMD",
    "TXN":"Texas Instruments","QCOM":"Qualcomm","AVGO":"Broadcom",
    "MU":"Micron Technology","ADI":"Analog Devices","PYPL":"PayPal",
    "SQ":"Block Inc","COIN":"Coinbase","GS":"Goldman Sachs","MS":"Morgan Stanley",
    "BAC":"Bank of America","WFC":"Wells Fargo","C":"Citigroup","AXP":"Amex",
    "BLK":"BlackRock","SPGI":"S&P Global","MMC":"Marsh McLennan","AIG":"AIG",
    "MET":"MetLife","PRU":"Prudential Financial","V":"Visa","MA":"Mastercard",
    "JNJ":"Johnson & Johnson","PFE":"Pfizer","ABBV":"AbbVie","TMO":"Thermo Fisher",
    "ABT":"Abbott","DHR":"Danaher","BMY":"Bristol-Myers","AMGN":"Amgen",
    "GILD":"Gilead Sciences","LLY":"Eli Lilly","MRK":"Merck","MDT":"Medtronic",
    "ISRG":"Intuitive Surgical","SYK":"Stryker","BIIB":"Biogen","HUM":"Humana",
    "CVS":"CVS Health","CI":"Cigna","CNC":"Centene","UNH":"UnitedHealth",
    "TGT":"Target","DG":"Dollar General","ROST":"Ross Stores","TJX":"TJX Cos",
    "BBY":"Best Buy","AAP":"Advance Auto Parts","LOW":"Lowe's","BKNG":"Booking Holdings",
    "EXPE":"Expedia","CMCSA":"Comcast","SBUX":"Starbucks","MKC":"McCormick",
    "GIS":"General Mills","K":"Kellogg","KMB":"Kimberly-Clark","CL":"Colgate-Palmolive",
    "CLX":"Clorox","CHD":"Church & Dwight","STZ":"Constellation Brands",
    "ADM":"Archer-Daniels","BGS":"B&G Foods","CAG":"Conagra","HRL":"Hormel",
    "MNST":"Monster Beverage","HSY":"Hershey","SYY":"Sysco","KR":"Kroger",
    "IBM":"IBM Corp",
}


def _extract_name(company: dict) -> str:
    """Extract company name: known map → description parse → symbol."""
    sym = company.get("symbol", "")
    if sym in _KNOWN_NAMES:
        return _KNOWN_NAMES[sym]
    desc = company.get("company_info", {}).get("description", "")
    if desc and len(desc) > 10:
        # First sentence usually starts with company name before a verb
        import re
        m = re.match(r'^([A-Z][^.]{3,60}?)\s+(is |operates|provides|engages|manufactures|develops|designs|offers)', desc)
        if m:
            return m.group(1).strip()
        # Fallback: first 4 words
        words = desc.split()[:4]
        candidate = " ".join(words)
        if len(candidate) > 3:
            return candidate
    return sym


def enrich_company(company: dict) -> dict:
    """Re-compute scores and ensure proper company name."""
    new_scores = reliable_rescore(company)
    company["investment_scores"] = new_scores
    company["name"] = _extract_name(company)

    ci = company.get("company_info", {})
    if ci.get("pe_ratio") and not company.get("financial_metrics", {}).get("pe_ratio"):
        company["financial_metrics"]["pe_ratio"] = ci["pe_ratio"]

    return company


def run():
    output_dir = OUTPUT_DIR
    # Find most recent scaled_analysis (has real company data)
    scaled_dir = output_dir / "scaled_analysis"
    files = sorted(scaled_dir.glob("scaled_analysis_*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)

    # Skip empty files from failed runs (today's 0-company run)
    src_file = None
    for f in files:
        data = read_jsonl(f)
        if data:
            src_file = f
            break

    if not src_file:
        print("❌ No valid scaled_analysis file found")
        return

    companies = read_jsonl(src_file)
    print(f"📊 Re-scoring {len(companies)} companies from {src_file.name}")

    rescored = []
    for c in companies:
        enriched = enrich_company(c)
        s = enriched["investment_scores"]
        print(f"  {c['symbol']:6s}  {s['overall_score']:5.1f}/20  {s['investment_category']:9s}  "
              f"Q={s['quality_score']:.1f} V={s['value_score']:.1f} G={s['growth_score']:.1f} S={s['safety_score']:.1f}")
        rescored.append(enriched)

    # Sort by overall score desc
    rescored.sort(key=lambda x: x["investment_scores"]["overall_score"], reverse=True)

    # Save
    rescored_dir = output_dir / "rescored_analysis"
    rescored_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = rescored_dir / f"rescored_{ts}.jsonl"
    write_jsonl(out_file, rescored)

    # Summary
    cats = {}
    for c in rescored:
        cat = c["investment_scores"]["investment_category"]
        cats[cat] = cats.get(cat, 0) + 1

    scores = [c["investment_scores"]["overall_score"] for c in rescored]
    summary = {
        "timestamp": ts,
        "total_companies": len(rescored),
        "average_score": sum(scores) / len(scores),
        "max_score": max(scores),
        "min_score": min(scores),
        "categories": cats,
        "top_10": [
            {"rank": i+1, "symbol": c["symbol"], "name": c["name"],
             "sector": c["sector"], "score": c["investment_scores"]["overall_score"],
             "category": c["investment_scores"]["investment_category"]}
            for i, c in enumerate(rescored[:10])
        ]
    }
    write_json(rescored_dir / f"rescored_summary_{ts}.json", summary)

    print(f"\n✅ Saved {len(rescored)} companies → {out_file}")
    print(f"\n🏆 TOP 10:")
    for r in summary["top_10"]:
        print(f"  {r['rank']:2d}. {r['symbol']:8s} {r['score']:5.1f}/20  {r['category']:9s}  {r['sector']}")

    print(f"\n📊 Category breakdown:")
    for cat in ["EXCELLENT","GOOD","FAIR","POOR","RISKY"]:
        print(f"  {cat:9s}: {cats.get(cat,0)}")

    return rescored_dir, ts


if __name__ == "__main__":
    run()
