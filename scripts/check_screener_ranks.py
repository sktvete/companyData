"""Print screener ranks for a watchlist after load_data()."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))
import app_enhanced as ae  # noqa: E402

WATCH = [
    "NVDA", "TSM", "MSFT", "AAPL", "GOOGL", "META", "SBGSF", "GFI",
    "DEO", "INTU", "ADP", "NOVO-B", "LIFCO-B", "SAAB-B", "ORSTED",
]


def main() -> None:
    ae.load_data()
    ranked = ae.screener_rank_by_symbol or {
        c["symbol"]: i + 1 for i, c in enumerate(ae.companies)
    }
    print("symbol  rank  listing  value  growth  overall  peg")
    for sym in WATCH:
        c = ae.company_lookup.get(sym)
        if not c:
            print(f"{sym:<8}    —   (not in universe)")
            continue
        s = c.get("investment_scores", {})
        ls = ae._compounder_list_score(c)
        print(
            f"{sym:<8} {ranked[sym]:>5}  {ls:>6.2f}  "
            f"{s.get('value_score')!s:>5}  {s.get('growth_score')!s:>5}  "
            f"{s.get('overall_score')!s:>5}  {s.get('peg_ratio')!s:>5}"
        )
    print("\n--- top 20 screener (listing_score) ---")
    for i, c in enumerate(ae.companies[:20], 1):
        s = c.get("investment_scores", {})
        print(
            f"{i:>2} {c['symbol']:<8} list={ae._compounder_list_score(c):.2f} "
            f"V={s.get('value_score')} G={s.get('growth_score')} "
            f"cat={s.get('investment_category')}"
        )


if __name__ == "__main__":
    main()
