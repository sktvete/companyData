"""Extract analyst consensus from EODHD fundamentals and optional Yahoo Finance fallback."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_YF_CACHE_DIR = _PROJECT_ROOT / "outputs" / "analyst_yf_cache"
_YF_CACHE_TTL = 24 * 3600
_yf_mem: dict[str, tuple[float, dict | None]] = {}


def _sf(x: Any, default: float = 0.0) -> float:
    if x is None or x == "":
        return default
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return default


def has_consensus_votes(ar: dict | None) -> bool:
    """True when we have a numeric rating or at least one buy/hold/sell vote."""
    if not ar:
        return False
    r = ar.get("Rating") if ar.get("Rating") is not None else ar.get("rating")
    if r is not None and str(r).strip() not in ("", "0", "0.0"):
        return True
    total = sum(
        int(ar.get(k) or ar.get(k.lower()) or 0)
        for k in ("StrongBuy", "Buy", "Hold", "Sell", "StrongSell")
    )
    return total > 0


def _votes_from_eodhd(ar_raw: dict) -> dict | None:
    rating = ar_raw.get("Rating")
    if rating is not None and str(rating).strip() not in ("", "0", "0.0"):
        return {
            "Rating": float(rating),
            "TargetPrice": _sf(ar_raw.get("TargetPrice")),
            "StrongBuy": int(_sf(ar_raw.get("StrongBuy"))),
            "Buy": int(_sf(ar_raw.get("Buy"))),
            "Hold": int(_sf(ar_raw.get("Hold"))),
            "Sell": int(_sf(ar_raw.get("Sell"))),
            "StrongSell": int(_sf(ar_raw.get("StrongSell"))),
            "partial": False,
            "source": "eodhd",
        }
    sb = int(_sf(ar_raw.get("StrongBuy")))
    b = int(_sf(ar_raw.get("Buy")))
    h = int(_sf(ar_raw.get("Hold")))
    s = int(_sf(ar_raw.get("Sell")))
    ss = int(_sf(ar_raw.get("StrongSell")))
    if sb + b + h + s + ss < 1:
        return None
    # Derive 1–5 score from vote mix when Rating missing.
    weighted = (5 * sb + 4 * b + 3 * h + 2 * s + 1 * ss) / max(sb + b + h + s + ss, 1)
    return {
        "Rating": round(weighted, 2),
        "TargetPrice": _sf(ar_raw.get("TargetPrice")),
        "StrongBuy": sb,
        "Buy": b,
        "Hold": h,
        "Sell": s,
        "StrongSell": ss,
        "partial": False,
        "source": "eodhd",
    }


def extract_analyst_ratings(fundamentals: dict | None) -> dict | None:
    """EODHD AnalystRatings only (buy/hold/sell). Does not return estimate-only coverage."""
    if not fundamentals or not isinstance(fundamentals, dict):
        return None
    ar_raw = fundamentals.get("AnalystRatings") or {}
    return _votes_from_eodhd(ar_raw)


def _estimate_coverage_count(fundamentals: dict) -> int:
    trend = (fundamentals.get("Earnings") or {}).get("Trend") or {}
    now_year = datetime.now().year
    max_analysts = 0
    for date_key, t in trend.items():
        if not isinstance(t, dict) or "y" not in str(t.get("period", "")):
            continue
        try:
            fy_year = int(str(date_key)[:4])
        except (ValueError, TypeError):
            continue
        if fy_year < now_year:
            continue
        n = int(
            max(
                _sf(t.get("earningsEstimateNumberOfAnalysts")),
                _sf(t.get("revenueEstimateNumberOfAnalysts")),
            )
        )
        max_analysts = max(max_analysts, n)
    return max_analysts


def _yf_cache_path(ticker: str) -> Path:
    safe = ticker.replace(".", "_").replace("/", "_").upper()
    return _YF_CACHE_DIR / f"{safe}.json"


def _read_yf_cache(ticker: str) -> dict | None:
    now = time.time()
    if ticker in _yf_mem:
        ts, data = _yf_mem[ticker]
        if now - ts < _YF_CACHE_TTL:
            return data
    fp = _yf_cache_path(ticker)
    if fp.is_file():
        try:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            if now - float(payload.get("_cached_at", 0)) < _YF_CACHE_TTL:
                data = payload.get("data")
                _yf_mem[ticker] = (now, data)
                return data
        except Exception:
            pass
    return None


def _write_yf_cache(ticker: str, data: dict | None) -> None:
    now = time.time()
    _yf_mem[ticker] = (now, data)
    if data is None:
        return
    try:
        _YF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _yf_cache_path(ticker).write_text(
            json.dumps({"_cached_at": now, "data": data}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def fetch_yfinance_consensus(tickers: list[str]) -> dict | None:
    """Yahoo Finance buy/hold/sell counts (useful when EODHD lacks AnalystRatings on ADRs)."""
    try:
        import yfinance as yf
    except ImportError:
        return None

    seen: set[str] = set()
    for raw in tickers:
        t = (raw or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)

        cached = _read_yf_cache(t)
        if cached is not None:
            if has_consensus_votes(cached):
                return cached
            continue

        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
            rec = getattr(tk, "recommendations", None)
        except Exception:
            _write_yf_cache(t, None)
            continue

        sb = b = h = s = ss = 0
        if rec is not None and len(rec) > 0:
            try:
                row = rec.iloc[0]
                sb = int(row.get("strongBuy", 0) or 0)
                b = int(row.get("buy", 0) or 0)
                h = int(row.get("hold", 0) or 0)
                s = int(row.get("sell", 0) or 0)
                ss = int(row.get("strongSell", 0) or 0)
            except Exception:
                pass

        yahoo_mean = _sf(info.get("recommendationMean"), 0.0) or None
        if yahoo_mean == 0:
            yahoo_mean = None
        target = _sf(info.get("targetMeanPrice")) or _sf(info.get("targetHighPrice"))
        total_votes = sb + b + h + s + ss

        if total_votes < 1 and not yahoo_mean:
            _write_yf_cache(t, None)
            continue

        # Yahoo: 1=Strong Buy … 5=Strong Sell. EODHD-style: 5=Strong Buy … 1=Strong Sell.
        if total_votes > 0:
            rating = round((5 * sb + 4 * b + 3 * h + 2 * s + 1 * ss) / total_votes, 2)
        elif yahoo_mean is not None:
            rating = round(6.0 - yahoo_mean, 2)
        else:
            rating = None

        out = {
            "Rating": rating,
            "TargetPrice": target,
            "StrongBuy": sb,
            "Buy": b,
            "Hold": h,
            "Sell": s,
            "StrongSell": ss,
            "partial": False,
            "source": "yfinance",
            "yf_ticker": t,
        }
        _write_yf_cache(t, out)
        return out

    return None


def resolve_consensus_analyst_ratings(
    symbol: str,
    fundamentals: dict | None = None,
    stored: dict | None = None,
) -> dict | None:
    """Best available buy/hold/sell consensus for a company row."""
    if stored and has_consensus_votes(stored):
        return stored

    if fundamentals:
        ar = extract_analyst_ratings(fundamentals)
        if has_consensus_votes(ar):
            return ar

    sym = (symbol or "").strip().upper()
    tickers: list[str] = []
    gen = (fundamentals or {}).get("General") or {}
    primary = (gen.get("PrimaryTicker") or "").strip()
    if primary:
        tickers.append(primary)
    ex = (gen.get("Exchange") or "").strip().upper()
    if sym:
        tickers.append(sym)
        if ex in ("PA", "XETRA", "F", "L", "AS", "BRU", "SW") and "." not in sym:
            tickers.append(f"{sym}.{ex}")
        if sym.endswith(("F", "Y")) and len(sym) > 1:
            tickers.append(sym[:-1])

    yf = fetch_yfinance_consensus(tickers)
    if has_consensus_votes(yf):
        return yf

    return None
