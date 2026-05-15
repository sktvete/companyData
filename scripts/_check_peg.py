import sys, json
sys.path.insert(0, r"c:\Users\sktve\Documents\projects\companyData\src")
sys.path.insert(0, r"c:\Users\sktve\Documents\projects\companyData\scripts")
from equity_sorter.cache import FundamentalsCache
from scale_analysis_1000 import extract_financial_data_correct
from equity_sorter.canonical.comprehensive_metrics import calculate_comprehensive_metrics
from pathlib import Path

db = FundamentalsCache(Path(r"c:\Users\sktve\Documents\projects\companyData\outputs\fundamentals.db"))

targets = ["GILD", "LRLCY", "SBGSF", "TT", "APH", "HESAF", "SCCO", "TJX", "GLAXF", "TSM",
           "MSFT", "NVDA", "META", "GOOGL"]
for sym in targets:
    data = db.get(sym)
    if not data:
        print(f"{sym}: NOT IN CACHE")
        continue
    financials = extract_financial_data_correct(data)
    highlights = data.get("Highlights", {})
    mcap = float(highlights.get("MarketCapitalization") or 1e12)
    price_data = [{"date": "2024-12-31", "close": mcap / 1e9, "market_cap": mcap, "enterprise_value": mcap * 1.2}]
    metrics = calculate_comprehensive_metrics(financials, price_data)
    if "error" in metrics:
        print(f"{sym}: ERROR - {metrics['error'][:60]}")
        continue
    peg = metrics.get("peg_ratio", 0)
    pe = metrics.get("pe_ratio", 0)
    oeps_cagr = metrics.get("oeps_cagr", 0)
    eps_g = metrics.get("eps_growth", 0)
    ni_g = metrics.get("net_income_growth", 0)
    rev_cagr3 = metrics.get("revenue_cagr_3y", 0)
    rev_1y = metrics.get("revenue_growth_1y", 0)
    fcf_yield = metrics.get("fcf_yield", 0)
    roic = metrics.get("roic", 0)
    roe = metrics.get("roe", 0)
    sector = data.get("General", {}).get("Sector", "?")
    industry = data.get("General", {}).get("Industry", "?")
    print(f"{sym:6s}  P/E:{pe:>5.1f}  PEG:{peg:>5.2f}  Rev1y:{rev_1y*100:>5.1f}%  RevCAGR3y:{rev_cagr3*100:>5.1f}%  EPS_g:{eps_g*100:>5.1f}%  NI_g:{ni_g*100:>5.1f}%  OEPS:{oeps_cagr*100:>5.1f}%  ROIC:{roic*100:>4.0f}%  Sector:{sector}")
