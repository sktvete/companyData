from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, List, Dict, Optional

from ..io_utils import read_json, read_jsonl, write_jsonl
from .comprehensive_metrics import calculate_comprehensive_metrics

SCORING_VERSION = "garp_v0_phase0"
FUNDAMENTALS_ONLY_SCORING_VERSION = "fundamentals_only_v1"
HYBRID_SCORING_VERSION = "hybrid_v1"


def build_factor_snapshot(
    as_of_date: str,
    companies: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    listings: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    sectors: dict[str, str] | None = None,
    source_lineage: str = "selected_sources",
) -> list[dict[str, Any]]:
    sectors = sectors or {}
    company_by_id = {row["company_id"]: row for row in companies}
    security_to_company = {row["security_id"]: row["company_id"] for row in securities}
    listing_by_security = {row["security_id"]: row for row in listings}
    latest_price = _latest_price_by_security(prices, as_of_date)
    fundamentals_by_security = _latest_four_quarters(fundamentals, as_of_date)

    rows: list[dict[str, Any]] = []
    for security_id, listing in listing_by_security.items():
        company_id = security_to_company.get(security_id)
        company = company_by_id.get(company_id, {})
        price_row = latest_price.get(security_id)
        quarter_rows = fundamentals_by_security.get(security_id, [])
        if not price_row or not quarter_rows:
            continue

        ttm_revenue = _sum_metric(quarter_rows, "revenue")
        ttm_ebit = _sum_metric(quarter_rows, "ebit")
        ttm_ocf = _sum_metric(quarter_rows, "operating_cash_flow")
        ttm_fcf = _sum_metric(quarter_rows, "free_cash_flow")
        latest_quarter = quarter_rows[-1]
        shares = latest_quarter.get("shares_basic")
        close = price_row.get("close") or price_row.get("adjusted_close")
        market_cap = close * shares if close is not None and shares is not None else None
        total_debt = latest_quarter.get("total_debt")
        cash = latest_quarter.get("cash_and_equivalents")
        enterprise_value = market_cap + total_debt - cash if None not in (market_cap, total_debt, cash) else None
        total_equity = latest_quarter.get("total_equity")
        total_assets = latest_quarter.get("total_assets")
        gross_profit = _sum_metric(quarter_rows, "gross_profit")
        operating_income = _sum_metric(quarter_rows, "operating_income")

        quality_inputs = {
            "gross_margin": _safe_div(gross_profit, ttm_revenue),
            "operating_margin": _safe_div(operating_income, ttm_revenue),
            "roa": _safe_div(ttm_ebit, total_assets),
            "roe": _safe_div(ttm_ebit, total_equity),
        }
        value_inputs = {
            "fcf_yield": _safe_div(ttm_fcf, market_cap),
            "earnings_yield": _safe_div(ttm_ebit, enterprise_value),
        }
        growth_inputs = {
            "revenue_growth_1y": _growth_from_quarters(quarter_rows, "revenue"),
            "fcf_growth_1y": _growth_from_quarters(quarter_rows, "free_cash_flow"),
        }
        safety_inputs = {
            "net_debt_to_ebitda": _safe_div((total_debt or 0.0) - (cash or 0.0), ttm_ebit),
            "debt_to_equity": _safe_div(total_debt, total_equity),
        }
        momentum_inputs = {
            "distance_from_52w_high": _distance_from_high(prices, security_id, as_of_date),
            "momentum_12m_ex_1m": _momentum_12m_ex_1m(prices, security_id, as_of_date),
        }

        completeness = _completeness_score({**quality_inputs, **value_inputs, **growth_inputs, **safety_inputs, **momentum_inputs})
        timing_confidence = _timing_confidence(quarter_rows)
        positive = []
        negative = []

        row = {
            "as_of_date": as_of_date,
            "security_id": security_id,
            "listing_id": listing["listing_id"],
            "company_id": company_id,
            "company_name": company.get("legal_name", listing["ticker"]),
            "ticker": listing["ticker"],
            "exchange": listing["exchange_code"],
            "country": listing.get("country"),
            "currency": listing.get("currency"),
            "sector": sectors.get(security_id),
            "market_cap_usd": market_cap,
            "price_data_status": price_row.get("price_data_status", "unknown"),
            "price_adjustment_method": price_row.get("provider_adjustment_method", "unknown"),
            "price_confidence": price_row.get("price_confidence", 0.5),
            "_quality_inputs": quality_inputs,
            "_value_inputs": value_inputs,
            "_growth_inputs": growth_inputs,
            "_safety_inputs": safety_inputs,
            "_momentum_inputs": momentum_inputs,
            "_metric_score_details": {},
            "_positive": positive,
            "_negative": negative,
            "_ttm_fcf": ttm_fcf,
            "data_completeness_score": completeness,
            "confidence_score": 0.0,
            "ranking_confidence": 0.0,
            "timing_confidence": timing_confidence,
            "source_lineage": source_lineage,
            "scoring_version": SCORING_VERSION,
        }
        rows.append(row)

    _score_bucket(rows, "quality_score", "_quality_inputs", higher_is_better={"gross_margin", "operating_margin", "roa", "roe"})
    _score_bucket(rows, "value_score", "_value_inputs", higher_is_better={"fcf_yield", "earnings_yield"})
    _score_bucket(rows, "growth_score", "_growth_inputs", higher_is_better={"revenue_growth_1y", "fcf_growth_1y"})
    _score_bucket(rows, "safety_score", "_safety_inputs", higher_is_better=set(), lower_is_better={"net_debt_to_ebitda", "debt_to_equity"})
    _score_bucket(rows, "momentum_score", "_momentum_inputs", higher_is_better={"momentum_12m_ex_1m"}, lower_is_better={"distance_from_52w_high"})

    for row in rows:
        row["total_garp_score"] = (
            0.25 * row["quality_score"]
            + 0.25 * row["value_score"]
            + 0.25 * row["growth_score"]
            + 0.15 * row["safety_score"]
            + 0.10 * row["momentum_score"]
        )
        row["red_flags"] = _red_flags(row)
        row["quality_explanation"] = _bucket_explanation(row, "_quality_inputs", "quality_score")
        row["value_explanation"] = _bucket_explanation(row, "_value_inputs", "value_score")
        row["growth_explanation"] = _bucket_explanation(row, "_growth_inputs", "growth_score")
        row["safety_explanation"] = _bucket_explanation(row, "_safety_inputs", "safety_score")
        row["momentum_explanation"] = _bucket_explanation(row, "_momentum_inputs", "momentum_score")
        row["top_positive_factors"] = _top_metric_contributors(row, positive=True)
        row["top_negative_factors"] = _top_metric_contributors(row, positive=False)
        row["confidence_score"] = round(_confidence_score(row["data_completeness_score"], row["timing_confidence"]), 4)
        row["ranking_confidence"] = round(row["confidence_score"] * float(row.get("price_confidence", 0.5)), 4)

    return sorted(rows, key=lambda row: row["total_garp_score"], reverse=True)


def build_fundamentals_only_snapshot(
    as_of_date: str,
    companies: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    listings: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    sectors: dict[str, str] | None = None,
    source_lineage: str = "sec_edgar",
) -> list[dict[str, Any]]:
    sectors = sectors or {}
    company_by_id = {row["company_id"]: row for row in companies}
    security_to_company = {row["security_id"]: row["company_id"] for row in securities}
    listing_by_security = {row["security_id"]: row for row in listings}
    fundamentals_by_security = _latest_four_quarters(fundamentals, as_of_date)
    rows: list[dict[str, Any]] = []

    for security_id, listing in listing_by_security.items():
        quarter_rows = fundamentals_by_security.get(security_id, [])
        if not quarter_rows:
            continue
        company_id = security_to_company.get(security_id)
        company = company_by_id.get(company_id, {})
        latest_quarter = quarter_rows[-1]
        ttm_revenue = _sum_metric(quarter_rows, "revenue")
        ttm_operating_income = _sum_metric(quarter_rows, "operating_income")
        ttm_net_income = _sum_metric(quarter_rows, "net_income")
        ttm_fcf = _sum_metric(quarter_rows, "free_cash_flow")
        total_assets = latest_quarter.get("total_assets")
        total_equity = latest_quarter.get("total_equity")
        total_debt = latest_quarter.get("total_debt")
        cash = latest_quarter.get("cash_and_equivalents")
        gross_profit = _sum_metric(quarter_rows, "gross_profit")
        quality_inputs = {
            "gross_margin": _safe_div(gross_profit, ttm_revenue),
            "operating_margin": _safe_div(ttm_operating_income, ttm_revenue),
            "roa": _safe_div(ttm_net_income, total_assets),
            "roe": _safe_div(ttm_net_income, total_equity),
            "fcf_margin": _safe_div(ttm_fcf, ttm_revenue),
        }
        growth_inputs = {
            "revenue_growth_1y": _growth_from_quarters(quarter_rows, "revenue"),
            "operating_income_growth_1y": _growth_from_quarters(quarter_rows, "operating_income"),
            "net_income_growth_1y": _growth_from_quarters(quarter_rows, "net_income"),
            "fcf_growth_1y": _growth_from_quarters(quarter_rows, "free_cash_flow"),
        }
        safety_inputs = {
            "debt_to_equity": _safe_div(total_debt, total_equity),
            "debt_to_cash": _safe_div(total_debt, cash),
            "cash_to_debt": _safe_div(cash, total_debt),
        }
        completeness = _completeness_score({**quality_inputs, **growth_inputs, **safety_inputs})
        row = {
            "as_of_date": as_of_date,
            "security_id": security_id,
            "listing_id": listing["listing_id"],
            "company_id": company_id,
            "company_name": company.get("legal_name", listing["ticker"]),
            "ticker": listing["ticker"],
            "exchange": listing["exchange_code"],
            "country": listing.get("country"),
            "currency": listing.get("currency"),
            "sector": sectors.get(security_id),
            "market_cap_usd": None,
            "price_data_status": "missing",
            "price_adjustment_method": "missing",
            "price_confidence": 0.0,
            "_quality_inputs": quality_inputs,
            "_value_inputs": {},
            "_growth_inputs": growth_inputs,
            "_safety_inputs": safety_inputs,
            "_momentum_inputs": {},
            "_metric_score_details": {},
            "_ttm_fcf": ttm_fcf,
            "data_completeness_score": completeness,
            "confidence_score": 0.0,
            "ranking_confidence": 0.0,
            "timing_confidence": _timing_confidence(quarter_rows),
            "source_lineage": source_lineage,
            "scoring_version": FUNDAMENTALS_ONLY_SCORING_VERSION,
            "ranking_mode": "fundamentals_only",
        }
        rows.append(row)

    _score_bucket(rows, "quality_score", "_quality_inputs", higher_is_better={"gross_margin", "operating_margin", "roa", "roe", "fcf_margin"})
    _score_bucket(rows, "growth_score", "_growth_inputs", higher_is_better={"revenue_growth_1y", "operating_income_growth_1y", "net_income_growth_1y", "fcf_growth_1y"})
    _score_bucket(rows, "safety_score", "_safety_inputs", higher_is_better={"cash_to_debt"}, lower_is_better={"debt_to_equity", "debt_to_cash"})

    for row in rows:
        row["value_score"] = 0.0
        row["momentum_score"] = 0.0
        row["total_garp_score"] = 0.0
        row["total_score"] = 0.45 * row["quality_score"] + 0.35 * row["growth_score"] + 0.20 * row["safety_score"]
        row["red_flags"] = _red_flags(row)
        row["quality_explanation"] = _bucket_explanation(row, "_quality_inputs", "quality_score")
        row["value_explanation"] = "price_dependent_metrics_unavailable"
        row["growth_explanation"] = _bucket_explanation(row, "_growth_inputs", "growth_score")
        row["safety_explanation"] = _bucket_explanation(row, "_safety_inputs", "safety_score")
        row["momentum_explanation"] = "price_dependent_metrics_unavailable"
        row["top_positive_factors"] = _top_metric_contributors(row, positive=True)
        row["top_negative_factors"] = _top_metric_contributors(row, positive=False)
        row["confidence_score"] = round(_confidence_score(row["data_completeness_score"], row["timing_confidence"]), 4)
        row["ranking_confidence"] = row["confidence_score"]

    return sorted(rows, key=lambda row: row["total_score"], reverse=True)


def build_hybrid_snapshot(
    as_of_date: str,
    companies: list[dict[str, Any]],
    securities: list[dict[str, Any]],
    listings: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    sectors: dict[str, str] | None = None,
    source_lineage: str = "selected_sources",
) -> list[dict[str, Any]]:
    price_backed_rows = build_factor_snapshot(
        as_of_date,
        companies,
        securities,
        listings,
        prices,
        fundamentals,
        sectors=sectors,
        source_lineage=source_lineage,
    )
    fundamentals_only_rows = build_fundamentals_only_snapshot(
        as_of_date,
        companies,
        securities,
        listings,
        fundamentals,
        sectors=sectors,
        source_lineage="sec_edgar+nasdaq_trader",
    )
    price_backed_ids = {row["security_id"] for row in price_backed_rows}
    combined: list[dict[str, Any]] = []

    for row in price_backed_rows:
        row["ranking_mode"] = "hybrid_price_backed"
        row["total_score"] = row["total_garp_score"]
        row["hybrid_score"] = row["total_garp_score"]
        row["scoring_version"] = HYBRID_SCORING_VERSION
        combined.append(row)

    for row in fundamentals_only_rows:
        if row["security_id"] in price_backed_ids:
            continue
        row["ranking_mode"] = "hybrid_fundamentals_only"
        row["hybrid_score"] = row["total_score"]
        row["scoring_version"] = HYBRID_SCORING_VERSION
        combined.append(row)

    combined.sort(key=lambda row: (0 if row["ranking_mode"] == "hybrid_price_backed" else 1, row["hybrid_score"]), reverse=False)
    combined.sort(key=lambda row: (0 if row["ranking_mode"] == "hybrid_price_backed" else 1, -row["hybrid_score"]))
    return combined


def _latest_price_by_security(prices: list[dict[str, Any]], as_of_date: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in prices:
        if row["date"] <= as_of_date:
            current = result.get(row["security_id"])
            if current is None or current["date"] < row["date"]:
                result[row["security_id"]] = row
    return result


def _latest_four_quarters(fundamentals: list[dict[str, Any]], as_of_date: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fundamentals:
        effective_date = row.get("filing_date") or row.get("report_date") or row.get("fiscal_period_end_date")
        if effective_date and effective_date <= as_of_date:
            grouped[row["security_id"]].append(row)
    for security_id in grouped:
        grouped[security_id].sort(key=lambda row: row.get("fiscal_period_end_date") or "")
        grouped[security_id] = grouped[security_id][-4:]
    return grouped


def _sum_metric(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return float(sum(values))


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _growth_from_quarters(rows: list[dict[str, Any]], field: str) -> float | None:
    if len(rows) < 4:
        return None
    recent = rows[-1].get(field)
    base = rows[0].get(field)
    if recent is None or base in (None, 0):
        return None
    return (recent - base) / abs(base)


def _momentum_12m_ex_1m(prices: list[dict[str, Any]], security_id: str, as_of_date: str) -> float | None:
    price_rows = [row for row in prices if row["security_id"] == security_id and row["date"] <= as_of_date]
    if len(price_rows) < 252:
        return None
    price_rows.sort(key=lambda row: row["date"])
    current = price_rows[-22].get("close")
    prior = price_rows[-252].get("close")
    if current in (None,) or prior in (None, 0):
        return None
    return (current - prior) / prior


def _distance_from_high(prices: list[dict[str, Any]], security_id: str, as_of_date: str) -> float | None:
    cutoff = date.fromisoformat(as_of_date) - timedelta(days=365)
    price_rows = [
        row for row in prices
        if row["security_id"] == security_id and cutoff.isoformat() <= row["date"] <= as_of_date and row.get("close") is not None
    ]
    if not price_rows:
        return None
    current = price_rows[-1]["close"]
    high = max(row["close"] for row in price_rows)
    if current in (None,) or high == 0:
        return None
    return (high - current) / high


def _score_bucket(
    rows: list[dict[str, Any]],
    bucket_name: str,
    input_field: str,
    higher_is_better: set[str],
    lower_is_better: set[str] | None = None,
) -> None:
    lower_is_better = lower_is_better or set()
    metrics = sorted({metric for row in rows for metric in row[input_field].keys()})
    metric_scores: dict[str, dict[str, float]] = {metric: {} for metric in metrics}

    for metric in metrics:
        values = [(row["security_id"], row[input_field].get(metric)) for row in rows if row[input_field].get(metric) is not None]
        values.sort(key=lambda item: item[1])
        count = len(values)
        if count == 0:
            continue
        for index, (security_id, value) in enumerate(values):
            pct = index / max(count - 1, 1)
            if metric in higher_is_better:
                metric_scores[metric][security_id] = pct
            elif metric in lower_is_better:
                metric_scores[metric][security_id] = 1 - pct
            else:
                metric_scores[metric][security_id] = pct

    for row in rows:
        scores = [metric_scores[metric][row["security_id"]] for metric in metrics if row["security_id"] in metric_scores[metric]]
        row[bucket_name] = round(sum(scores) / len(scores), 6) if scores else 0.0
        details = row.setdefault("_metric_score_details", {})
        details[bucket_name] = {
            metric: metric_scores[metric][row["security_id"]]
            for metric in metrics
            if row["security_id"] in metric_scores[metric]
        }


def _completeness_score(values: dict[str, float | None]) -> float:
    total = len(values)
    present = sum(1 for value in values.values() if value is not None)
    return round(present / total, 4) if total else 0.0


def _timing_confidence(quarter_rows: list[dict[str, Any]]) -> str:
    if quarter_rows and all(row.get("filing_date") for row in quarter_rows):
        return "high"
    if quarter_rows and any(row.get("report_date") for row in quarter_rows):
        return "medium"
    return "low"


def _bucket_explanation(row: dict[str, Any], input_key: str, bucket_name: str) -> str:
    inputs = row[input_key]
    metric_scores = row.get("_metric_score_details", {}).get(bucket_name, {})
    parts: list[str] = []
    for metric in sorted(inputs.keys()):
        raw_value = inputs.get(metric)
        score_value = metric_scores.get(metric)
        if raw_value is None:
            parts.append(f"{metric}=missing")
        else:
            parts.append(f"{metric}={round(raw_value, 4)}|pct={round(score_value, 3) if score_value is not None else 'na'}")
    return "; ".join(parts)


def _top_metric_contributors(row: dict[str, Any], positive: bool) -> str:
    contributions: list[tuple[str, float]] = []
    for bucket_name, metric_scores in row.get("_metric_score_details", {}).items():
        for metric, value in metric_scores.items():
            contributions.append((f"{bucket_name}:{metric}", value))
    ranked = sorted(contributions, key=lambda item: item[1], reverse=positive)
    return ", ".join(name for name, _score in ranked[:3])


def _red_flags(row: dict[str, Any]) -> str:
    flags: list[str] = []
    if row["data_completeness_score"] < 0.7:
        flags.append("low_completeness")
    safety_inputs = row["_safety_inputs"]
    if (safety_inputs.get("net_debt_to_ebitda") or 0) > 5:
        flags.append("high_leverage")
    if (row.get("_ttm_fcf") or 0) < 0:
        flags.append("negative_fcf")
    return ", ".join(flags)


def _confidence_score(completeness: float, timing_confidence: str) -> float:
    timing_weight = {"high": 1.0, "medium": 0.75, "low": 0.5}.get(timing_confidence, 0.5)
    return completeness * timing_weight
