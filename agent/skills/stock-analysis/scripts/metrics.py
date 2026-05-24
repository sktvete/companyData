"""Deterministic metric extraction and calculation from EODHD data.

All financial metrics are computed here from raw EODHD responses.
Every function is pure: same inputs always produce the same outputs.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None for non-numeric inputs."""
    if value is None:
        return None
    try:
        v = float(value)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Safe division returning None if either operand is None or denominator is zero."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Calculate percentage change: (current / previous) - 1."""
    if current is None or previous is None or previous == 0:
        return None
    return (current / previous) - 1.0


def cagr(end_value: float | None, start_value: float | None, years: int) -> float | None:
    """Compound annual growth rate."""
    if end_value is None or start_value is None or start_value <= 0 or years <= 0:
        return None
    if end_value <= 0:
        return None
    return (end_value / start_value) ** (1.0 / years) - 1.0


# ---------------------------------------------------------------------------
# Fundamentals extraction
# ---------------------------------------------------------------------------


def _normalize_roe(value: float | None) -> float | None:
    """EODHD's ReturnOnEquityTTM is a decimal ratio (1.4147 = 141.47%).
    We keep it as-is since the scoring layer multiplies by 100."""
    return value


def extract_highlights(fundamentals: dict[str, Any]) -> dict[str, float | None]:
    """Extract key metrics from Highlights section."""
    h = fundamentals.get("Highlights") or {}
    return {
        "market_cap": safe_float(h.get("MarketCapitalization")),
        "pe_ratio": safe_float(h.get("PERatio")),
        "peg_ratio": safe_float(h.get("PEGRatio")),
        "eps": safe_float(h.get("EarningsShare")),
        "eps_estimate_current_year": safe_float(h.get("EPSEstimateCurrentYear")),
        "net_margin": safe_float(h.get("ProfitMargin")),
        "operating_margin": safe_float(h.get("OperatingMarginTTM")),
        "roe_ttm": _normalize_roe(safe_float(h.get("ReturnOnEquityTTM"))),
        "revenue_ttm": safe_float(h.get("RevenueTTM")),
        "revenue_per_share_ttm": safe_float(h.get("RevenuePerShareTTM")),
        "quarterly_revenue_growth_yoy": safe_float(h.get("QuarterlyRevenueGrowthYOY")),
        "quarterly_earnings_growth_yoy": safe_float(h.get("QuarterlyEarningsGrowthYOY")),
        "ebitda": safe_float(h.get("EBITDA")),
        "dividend_yield": safe_float(h.get("DividendYield")),
    }


def extract_valuation(fundamentals: dict[str, Any]) -> dict[str, float | None]:
    """Extract valuation metrics."""
    v = fundamentals.get("Valuation") or {}
    return {
        "forward_pe": safe_float(v.get("ForwardPE")),
        "price_to_sales": safe_float(v.get("PriceSalesTTM")),
        "ev_to_ebitda": safe_float(v.get("EnterpriseValueEbitda")),
        "enterprise_value": safe_float(v.get("EnterpriseValue")),
        "trailing_pe": safe_float(v.get("TrailingPE")),
        "price_to_book": safe_float(v.get("PriceBookMRQ")),
    }


def extract_shares_stats(fundamentals: dict[str, Any]) -> dict[str, float | None]:
    """Extract share statistics."""
    s = fundamentals.get("SharesStats") or {}
    return {
        "shares_outstanding": safe_float(s.get("SharesOutstanding")),
        "shares_float": safe_float(s.get("SharesFloat")),
        "percent_insiders": safe_float(s.get("PercentInsiders")),
        "percent_institutions": safe_float(s.get("PercentInstitutions")),
    }


def _sorted_annual_statements(
    fundamentals: dict[str, Any],
    statement_type: str,
) -> list[tuple[str, dict[str, Any]]]:
    """Get yearly financial statements sorted by date descending (most recent first).

    statement_type: "Income_Statement", "Balance_Sheet", or "Cash_Flow"
    """
    financials = fundamentals.get("Financials") or {}
    section = financials.get(statement_type) or {}
    yearly = section.get("yearly") or {}
    items = [(k, v) for k, v in yearly.items() if isinstance(v, dict)]
    items.sort(key=lambda x: x[0], reverse=True)
    return items


def extract_revenue_series(fundamentals: dict[str, Any]) -> list[tuple[str, float | None]]:
    """Extract yearly revenue sorted by date descending."""
    items = _sorted_annual_statements(fundamentals, "Income_Statement")
    return [(dt, safe_float(row.get("totalRevenue"))) for dt, row in items]


def extract_income_data(fundamentals: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract multi-year income statement data, most recent first."""
    items = _sorted_annual_statements(fundamentals, "Income_Statement")
    result = []
    for dt, row in items:
        result.append({
            "date": dt,
            "total_revenue": safe_float(row.get("totalRevenue")),
            "gross_profit": safe_float(row.get("grossProfit")),
            "operating_income": safe_float(row.get("operatingIncome")),
            "net_income": safe_float(row.get("netIncome")),
            "interest_expense": safe_float(row.get("interestExpense")),
        })
    return result


def extract_balance_sheet_data(fundamentals: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract multi-year balance sheet data, most recent first."""
    items = _sorted_annual_statements(fundamentals, "Balance_Sheet")
    result = []
    for dt, row in items:
        total_debt = safe_float(row.get("totalDebt"))
        if total_debt is None:
            short = safe_float(row.get("shortLongTermDebt")) or 0
            long = safe_float(row.get("longTermDebt")) or 0
            total_debt = (short + long) if (short or long) else None

        cash = safe_float(row.get("cashAndShortTermInvestments"))
        if cash is None:
            cash = safe_float(row.get("cash"))

        result.append({
            "date": dt,
            "total_debt": total_debt,
            "total_stockholder_equity": safe_float(row.get("totalStockholderEquity")),
            "cash": cash,
            "total_assets": safe_float(row.get("totalAssets")),
        })
    return result


def extract_cash_flow_data(fundamentals: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract multi-year cash flow data, most recent first."""
    items = _sorted_annual_statements(fundamentals, "Cash_Flow")
    result = []
    for dt, row in items:
        ocf = safe_float(row.get("totalCashFromOperatingActivities"))
        capex = safe_float(row.get("capitalExpenditures"))
        fcf = None
        if ocf is not None and capex is not None:
            fcf = ocf - abs(capex)
        result.append({
            "date": dt,
            "operating_cash_flow": ocf,
            "capital_expenditures": capex,
            "free_cash_flow": fcf,
        })
    return result


def extract_outstanding_shares(fundamentals: dict[str, Any]) -> list[tuple[str, float | None]]:
    """Extract annual outstanding shares sorted by date descending."""
    section = fundamentals.get("outstandingShares") or {}
    annual = section.get("annual") or []
    if isinstance(annual, dict):
        annual = list(annual.values())
    items = []
    for entry in annual:
        if isinstance(entry, dict):
            dt = entry.get("date") or entry.get("dateFormatted") or ""
            shares = safe_float(entry.get("shares") or entry.get("sharesMln"))
            items.append((str(dt), shares))
    items.sort(key=lambda x: x[0], reverse=True)
    return items


# ---------------------------------------------------------------------------
# Derived metric calculations
# ---------------------------------------------------------------------------


def compute_growth_metrics(
    income_data: list[dict[str, Any]],
    cash_flow_data: list[dict[str, Any]],
    shares_series: list[tuple[str, float | None]],
) -> dict[str, float | None]:
    """Compute growth metrics from multi-year financial data."""
    result: dict[str, float | None] = {
        "revenue_growth_yoy": None,
        "revenue_cagr_3y": None,
        "revenue_acceleration": None,
        "eps_growth_yoy": None,
        "fcf_growth_yoy": None,
        "fcf_per_share_growth": None,
    }

    revenues = [(d["date"], d["total_revenue"]) for d in income_data if d["total_revenue"] is not None]
    if len(revenues) >= 2:
        result["revenue_growth_yoy"] = pct_change(revenues[0][1], revenues[1][1])
    if len(revenues) >= 4:
        result["revenue_cagr_3y"] = cagr(revenues[0][1], revenues[3][1], 3)
    if len(revenues) >= 3:
        growth_latest = pct_change(revenues[0][1], revenues[1][1])
        growth_prior = pct_change(revenues[1][1], revenues[2][1])
        if growth_latest is not None and growth_prior is not None:
            result["revenue_acceleration"] = growth_latest - growth_prior

    net_incomes = [(d["date"], d["net_income"]) for d in income_data if d["net_income"] is not None]
    if len(net_incomes) >= 2:
        latest_shares = shares_series[0][1] if shares_series else None
        prior_shares = shares_series[1][1] if len(shares_series) >= 2 else latest_shares
        if latest_shares and prior_shares and latest_shares > 0 and prior_shares > 0:
            eps_latest = net_incomes[0][1] / latest_shares
            eps_prior = net_incomes[1][1] / prior_shares
            result["eps_growth_yoy"] = pct_change(eps_latest, eps_prior)

    fcfs = [(d["date"], d["free_cash_flow"]) for d in cash_flow_data if d["free_cash_flow"] is not None]
    if len(fcfs) >= 2:
        if fcfs[1][1] and fcfs[1][1] > 0:
            result["fcf_growth_yoy"] = pct_change(fcfs[0][1], fcfs[1][1])

        latest_shares = shares_series[0][1] if shares_series else None
        prior_shares = shares_series[1][1] if len(shares_series) >= 2 else latest_shares
        if latest_shares and prior_shares and latest_shares > 0 and prior_shares > 0:
            fcf_per_share_latest = fcfs[0][1] / latest_shares
            fcf_per_share_prior = fcfs[1][1] / prior_shares
            if fcf_per_share_prior > 0:
                result["fcf_per_share_growth"] = pct_change(fcf_per_share_latest, fcf_per_share_prior)

    return result


def compute_quality_metrics(income_data: list[dict[str, Any]]) -> dict[str, float | None]:
    """Compute margin and quality metrics from income data."""
    result: dict[str, float | None] = {
        "gross_margin": None,
        "operating_margin": None,
        "net_margin": None,
        "margin_trend": None,
    }
    if not income_data:
        return result

    latest = income_data[0]
    rev = latest["total_revenue"]
    if rev and rev > 0:
        result["gross_margin"] = safe_div(latest["gross_profit"], rev)
        result["operating_margin"] = safe_div(latest["operating_income"], rev)
        result["net_margin"] = safe_div(latest["net_income"], rev)

    if len(income_data) >= 2:
        prior = income_data[1]
        prior_rev = prior["total_revenue"]
        if rev and rev > 0 and prior_rev and prior_rev > 0:
            om_latest = safe_div(latest["operating_income"], rev)
            om_prior = safe_div(prior["operating_income"], prior_rev)
            if om_latest is not None and om_prior is not None:
                result["margin_trend"] = om_latest - om_prior

    return result


def compute_balance_sheet_metrics(
    balance_data: list[dict[str, Any]],
    ebitda: float | None,
    operating_income: float | None,
    interest_expense: float | None,
) -> dict[str, float | None]:
    """Compute balance sheet health metrics."""
    result: dict[str, float | None] = {
        "debt_to_equity": None,
        "net_debt_to_ebitda": None,
        "interest_coverage": None,
    }
    if not balance_data:
        return result

    latest = balance_data[0]
    result["debt_to_equity"] = safe_div(latest["total_debt"], latest["total_stockholder_equity"])

    if latest["total_debt"] is not None and latest["cash"] is not None and ebitda:
        net_debt = latest["total_debt"] - latest["cash"]
        result["net_debt_to_ebitda"] = safe_div(net_debt, ebitda)

    if operating_income is not None and interest_expense is not None:
        abs_ie = abs(interest_expense)
        if abs_ie < 1.0:
            # Near-zero interest expense means effectively no debt cost;
            # if operating_income is positive, coverage is extremely high
            if operating_income > 0:
                result["interest_coverage"] = 999.0
            else:
                result["interest_coverage"] = 0.0
        else:
            result["interest_coverage"] = abs(operating_income / abs_ie)

    return result


def compute_earnings_quality(
    cash_flow_data: list[dict[str, Any]],
    income_data: list[dict[str, Any]],
    balance_data: list[dict[str, Any]],
) -> dict[str, float | None]:
    """Compute earnings quality metrics."""
    result: dict[str, float | None] = {
        "fcf_to_net_income": None,
        "accruals_ratio": None,
    }
    if not cash_flow_data or not income_data:
        return result

    fcf = cash_flow_data[0].get("free_cash_flow")
    ni = income_data[0].get("net_income")
    result["fcf_to_net_income"] = safe_div(fcf, ni) if ni and ni > 0 else None

    if balance_data and ni is not None and fcf is not None:
        ta = balance_data[0].get("total_assets")
        if ta and ta > 0:
            result["accruals_ratio"] = (ni - fcf) / ta

    return result


def compute_dilution(shares_series: list[tuple[str, float | None]]) -> dict[str, float | None]:
    """Compute share dilution metrics."""
    result: dict[str, float | None] = {
        "dilution_1y": None,
        "dilution_3y_annualized": None,
    }
    valid = [(dt, s) for dt, s in shares_series if s is not None and s > 0]
    if len(valid) >= 2:
        result["dilution_1y"] = pct_change(valid[0][1], valid[1][1])
    if len(valid) >= 4:
        result["dilution_3y_annualized"] = cagr(valid[0][1], valid[3][1], 3)
    elif len(valid) >= 3:
        result["dilution_3y_annualized"] = cagr(valid[0][1], valid[2][1], 2)
    return result


def compute_fcf_yield(fcf: float | None, market_cap: float | None) -> float | None:
    return safe_div(fcf, market_cap)


# ---------------------------------------------------------------------------
# Technical indicator calculations from EOD prices
# ---------------------------------------------------------------------------


def compute_sma(prices: list[float], period: int) -> float | None:
    """Simple moving average of the last N values."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """Wilder RSI from a series of prices (oldest first)."""
    if len(prices) < period + 1:
        return None
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(0, c) for c in changes[:period]]
    losses = [max(0, -c) for c in changes[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for c in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(0, c)) / period
        avg_loss = (avg_loss * (period - 1) + max(0, -c)) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_technicals_from_eod(
    eod_prices: list[dict[str, Any]],
    current_price: float | None = None,
) -> dict[str, float | None]:
    """Compute all technical indicators from raw EOD price data."""
    result: dict[str, float | None] = {
        "sma_50": None,
        "sma_200": None,
        "rsi_14": None,
        "price_vs_50dma": None,
        "price_vs_200dma": None,
        "week_52_high": None,
        "drawdown_from_52w_high": None,
    }

    if not eod_prices:
        return result

    adj_closes = [
        safe_float(p.get("adjusted_close") or p.get("close"))
        for p in eod_prices
        if safe_float(p.get("adjusted_close") or p.get("close")) is not None
    ]

    highs = [
        safe_float(p.get("high"))
        for p in eod_prices
        if safe_float(p.get("high")) is not None
    ]

    if not adj_closes:
        return result

    if current_price is None:
        current_price = adj_closes[-1]

    result["sma_50"] = compute_sma(adj_closes, 50)
    result["sma_200"] = compute_sma(adj_closes, 200)
    result["rsi_14"] = compute_rsi(adj_closes, 14)

    if result["sma_50"]:
        result["price_vs_50dma"] = (current_price / result["sma_50"] - 1) * 100
    if result["sma_200"]:
        result["price_vs_200dma"] = (current_price / result["sma_200"] - 1) * 100

    if highs:
        result["week_52_high"] = max(highs)
        result["drawdown_from_52w_high"] = (current_price / result["week_52_high"] - 1) * 100

    return result


# ---------------------------------------------------------------------------
# Full metric assembly
# ---------------------------------------------------------------------------


def compute_all_metrics(raw_data: dict[str, Any]) -> dict[str, Any]:
    """Compute all metrics from raw EODHD data bundle.

    Args:
        raw_data: dict with keys "fundamentals", "eod_prices", "live_price", "news"

    Returns:
        dict with all computed metrics and a "missing_fields" list.
    """
    fundamentals = raw_data.get("fundamentals") or {}
    eod_prices = raw_data.get("eod_prices") or []
    live_price_data = raw_data.get("live_price") or {}

    highlights = extract_highlights(fundamentals)
    valuation = extract_valuation(fundamentals)
    shares_stats = extract_shares_stats(fundamentals)

    income_data = extract_income_data(fundamentals)
    balance_data = extract_balance_sheet_data(fundamentals)
    cash_flow_data = extract_cash_flow_data(fundamentals)
    shares_series = extract_outstanding_shares(fundamentals)

    growth = compute_growth_metrics(income_data, cash_flow_data, shares_series)
    quality = compute_quality_metrics(income_data)
    # For interest coverage, try the latest year first, then fall back to prior years
    op_income_for_ic = None
    int_expense_for_ic = None
    if income_data:
        op_income_for_ic = income_data[0]["operating_income"]
        int_expense_for_ic = income_data[0]["interest_expense"]
        # Fall back to prior year if latest has no interest_expense data
        if int_expense_for_ic is None and len(income_data) >= 2:
            int_expense_for_ic = income_data[1]["interest_expense"]
            if int_expense_for_ic is not None and op_income_for_ic is None:
                op_income_for_ic = income_data[1]["operating_income"]

    bs_metrics = compute_balance_sheet_metrics(
        balance_data,
        highlights["ebitda"],
        op_income_for_ic,
        int_expense_for_ic,
    )
    eq = compute_earnings_quality(cash_flow_data, income_data, balance_data)
    dilution = compute_dilution(shares_series)

    current_price = safe_float(live_price_data.get("close"))
    technicals = compute_technicals_from_eod(eod_prices, current_price)

    fcf = cash_flow_data[0]["free_cash_flow"] if cash_flow_data else None
    fcf_yield = compute_fcf_yield(fcf, highlights["market_cap"])

    key_metrics = {
        "market_cap": highlights["market_cap"],
        "revenue_growth_yoy": growth["revenue_growth_yoy"],
        "revenue_cagr_3y": growth["revenue_cagr_3y"],
        "eps_growth_yoy": growth["eps_growth_yoy"],
        "fcf_growth_yoy": growth["fcf_growth_yoy"],
        "fcf_per_share_growth": growth["fcf_per_share_growth"],
        "gross_margin": quality["gross_margin"],
        "operating_margin": quality["operating_margin"] or highlights["operating_margin"],
        "net_margin": quality["net_margin"] or highlights["net_margin"],
        "roic": highlights["roe_ttm"],  # already normalized by _normalize_pct
        "debt_to_equity": bs_metrics["debt_to_equity"],
        "net_debt_to_ebitda": bs_metrics["net_debt_to_ebitda"],
        "interest_coverage": bs_metrics["interest_coverage"],
        "pe_ratio": highlights["pe_ratio"],
        "forward_pe": valuation["forward_pe"],
        "peg_ratio": highlights["peg_ratio"],
        "ev_to_ebitda": valuation["ev_to_ebitda"],
        "fcf_yield": fcf_yield,
        "price_to_sales": valuation["price_to_sales"],
        "rsi": technicals["rsi_14"],
        "price_vs_50dma": technicals["price_vs_50dma"],
        "price_vs_200dma": technicals["price_vs_200dma"],
    }

    missing_fields = [k for k, v in key_metrics.items() if v is None]

    return {
        "key_metrics": key_metrics,
        "highlights": highlights,
        "valuation": valuation,
        "shares_stats": shares_stats,
        "income_data": income_data,
        "balance_data": balance_data,
        "cash_flow_data": cash_flow_data,
        "shares_series": shares_series,
        "growth": growth,
        "quality": quality,
        "balance_sheet_metrics": bs_metrics,
        "earnings_quality": eq,
        "dilution": dilution,
        "technicals": technicals,
        "current_price": current_price,
        "missing_fields": missing_fields,
    }
