#!/usr/bin/env python3

"""
Comprehensive financial metrics calculation using correct EODHD field names.
Includes Owner Earnings growth scoring per Buffett/Munger methodology.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date
import math
import statistics

from .ttm_periods import ttm_flow_period_count

# EODHD quarterly field name mappings (actual API response keys)
# Income Statement
_I_REVENUE         = "totalRevenue"
_I_GROSS_PROFIT    = "grossProfit"
_I_OP_INCOME       = "operatingIncome"
_I_EBIT            = "ebit"
_I_EBITDA          = "ebitda"
_I_PRETAX          = "incomeBeforeTax"
_I_NET_INCOME      = "netIncome"
_I_EPS_BASIC       = "basicEPS"
_I_EPS_DILUTED     = "dilutedEPS"
_I_COST_REVENUE    = "costOfRevenue"
_I_INTEREST_EXP    = "interestExpense"
_I_SBC             = "stockBasedCompensation"
_I_DILUTED_SHARES  = "dilutedAverageShares"

# Cash Flow
_C_OCF   = "totalCashFromOperatingActivities"
_C_CAPEX = "capitalExpenditures"
_C_FCF   = "freeCashFlow"

# Balance Sheet
_B_CASH            = "cash"
_B_TOTAL_ASSETS    = "totalAssets"
_B_CURR_ASSETS     = "totalCurrentAssets"
_B_INVENTORY       = "inventory"
_B_RECEIVABLES     = "netReceivables"
_B_PAYABLES        = "accountPayables"
_B_CURR_LIAB       = "totalCurrentLiabilities"
_B_TOTAL_LIAB      = "totalLiab"
_B_ST_DEBT         = "shortLongTermDebt"
_B_LT_DEBT         = "longTermDebt"
_B_EQUITY          = "totalStockholderEquity"
_B_RETAINED        = "retainedEarnings"
_B_SHARES_OUT      = "commonStockSharesOutstanding"


def safe_get(data: Dict[str, Any], key: str) -> float:
    """Safely get a numeric value from a dict."""
    value = data.get(key, 0)
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            clean = value.replace(',', '').replace('$', '').replace('(', '-').replace(')', '').strip()
            return float(clean) if clean not in ('', 'None', 'nan', 'N/A') else 0.0
        except ValueError:
            return 0.0
    return 0.0


def safe_divide(numerator: float, denominator: float) -> float:
    """Safely divide, returning 0 on zero denominator."""
    if not denominator or not isinstance(denominator, (int, float)):
        return 0.0
    return numerator / denominator


def rate_as_decimal(x: float) -> float:
    """Return a return rate as a decimal (0.18 = 18%). Some feeds store 18.0 instead of 0.18."""
    if not isinstance(x, (int, float)) or x == 0:
        return 0.0
    ax = abs(float(x))
    if ax > 1.25:
        return float(x) / 100.0
    return float(x)


# Short aliases used throughout this module
sg = safe_get
sd = safe_divide


def _adjusted_gross_profit(stmt: Dict[str, Any]) -> float:
    """EODHD sometimes sets grossProfit == totalRevenue while costOfRevenue is non-zero."""
    rev = sg(stmt, _I_REVENUE)
    gp = sg(stmt, _I_GROSS_PROFIT)
    cor = sg(stmt, _I_COST_REVENUE)
    if rev > 0 and cor > 0 and gp >= rev * 0.999:
        return rev - cor
    return gp


def calculate_comprehensive_metrics(financial_data: Dict[str, Any],
                                    price_data: List[Dict[str, Any]],
                                    highlights: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calculate all comprehensive financial metrics from EODHD data.

    ``highlights`` — raw EODHD ``Highlights`` dict.  When provided, its
    currency-correct P/E and PEG override our calculated ratios (which can
    be wrong for non-USD reporting currencies).
    """

    metrics: Dict[str, Any] = {}

    income_statement = financial_data.get('income_statement', [])
    balance_sheet    = financial_data.get('balance_sheet', [])
    cash_flow        = financial_data.get('cash_flow', [])

    if not income_statement or not balance_sheet or not cash_flow:
        return {"error": "Insufficient financial data for comprehensive analysis"}

    latest_income  = income_statement[0] if income_statement else {}
    latest_balance = balance_sheet[0]    if balance_sheet    else {}
    latest_cash    = cash_flow[0]        if cash_flow        else {}

    prev_income    = income_statement[1] if len(income_statement) > 1 else {}
    prev_balance   = balance_sheet[1]    if len(balance_sheet)    > 1 else {}

    # ── TTM (Trailing Twelve Months) aggregation ──────────────────────────────
    # Flow periods: 4 quarters, 2 semi-annual halves, or 1 fiscal year (EODHD mix).
    def _ttm_sum(stmts: list, key: str, n: int) -> float:
        """Sum a field across the last n flow periods (most recent first)."""
        total = 0.0
        for stmt in stmts[:n]:
            total += sg(stmt, key)
        return total

    inc_dates = [str(s.get("date") or "")[:10] for s in income_statement if s.get("date")]
    cf_dates = [str(s.get("date") or "")[:10] for s in cash_flow if s.get("date")]
    n_inc = ttm_flow_period_count(inc_dates)
    n_cf = ttm_flow_period_count(cf_dates) if cf_dates else n_inc
    n_flow = min(n_inc, n_cf) if cf_dates else n_inc

    have_flow_income = len(income_statement) >= n_flow and n_flow > 0
    have_flow_cf = len(cash_flow) >= n_flow and n_flow > 0

    # ── Income Statement (TTM) ────────────────────────────────────────────────
    if have_flow_income:
        metrics['revenue']          = _ttm_sum(income_statement, _I_REVENUE, n_flow)
        metrics['gross_profit']     = sum(
            _adjusted_gross_profit(income_statement[i]) for i in range(n_flow)
        )
        metrics['operating_income'] = _ttm_sum(income_statement, _I_OP_INCOME, n_flow)
        metrics['ebit']             = _ttm_sum(income_statement, _I_EBIT, n_flow) or _ttm_sum(income_statement, _I_OP_INCOME, n_flow)
        metrics['ebitda']           = _ttm_sum(income_statement, _I_EBITDA, n_flow)
        metrics['pretax_income']    = _ttm_sum(income_statement, _I_PRETAX, n_flow)
        metrics['net_income']       = _ttm_sum(income_statement, _I_NET_INCOME, n_flow)
    else:
        metrics['revenue']          = sg(latest_income, _I_REVENUE)
        metrics['gross_profit']     = _adjusted_gross_profit(latest_income)
        metrics['operating_income'] = sg(latest_income, _I_OP_INCOME)
        metrics['ebit']             = sg(latest_income, _I_EBIT) or sg(latest_income, _I_OP_INCOME)
        metrics['ebitda']           = sg(latest_income, _I_EBITDA)
        metrics['pretax_income']    = sg(latest_income, _I_PRETAX)
        metrics['net_income']       = sg(latest_income, _I_NET_INCOME)

    hl_eps = 0.0
    if highlights:
        hl_eps = sg(highlights, "DilutedEpsTTM") or sg(highlights, "EarningsShare")

    def _stmt_has_diluted_eps(stmt: Dict[str, Any]) -> bool:
        v = stmt.get(_I_EPS_DILUTED) if isinstance(stmt, dict) else None
        if v is None:
            return False
        if isinstance(v, str):
            t = v.strip().lower()
            if t in ("", "none", "n/a", "nan"):
                return False
        return True

    # EPS: full quarterly TTM sum when every period reports dilutedEPS; else Highlights TTM; else NI/shares.
    if have_flow_income:
        metrics['eps_basic'] = _ttm_sum(income_statement, _I_EPS_BASIC, n_flow)
        ttm_eps_sum = _ttm_sum(income_statement, _I_EPS_DILUTED, n_flow)
        q_with_eps = sum(1 for i in range(n_flow) if _stmt_has_diluted_eps(income_statement[i]))
        eps_complete = q_with_eps == n_flow and ttm_eps_sum > 0
        if eps_complete:
            metrics['eps_diluted'] = ttm_eps_sum
        elif hl_eps > 0:
            metrics['eps_diluted'] = hl_eps
        else:
            metrics['eps_diluted'] = 0.0
    else:
        metrics['eps_basic'] = sg(latest_income, _I_EPS_BASIC)
        leps = sg(latest_income, _I_EPS_DILUTED)
        if _stmt_has_diluted_eps(latest_income) and leps > 0:
            metrics['eps_diluted'] = leps
        elif hl_eps > 0:
            metrics['eps_diluted'] = hl_eps
        else:
            metrics['eps_diluted'] = 0.0

    metrics['diluted_shares']   = (sg(latest_balance, _B_SHARES_OUT)
                                   or sg(latest_income, _I_DILUTED_SHARES))
    # SBC: TTM sum from cash flow (where EODHD reports it)
    if have_flow_cf:
        metrics['sbc'] = _ttm_sum(cash_flow, _I_SBC, n_flow) or _ttm_sum(income_statement, _I_SBC, n_flow)
    else:
        metrics['sbc'] = sg(latest_cash, _I_SBC) or sg(latest_income, _I_SBC)

    # ── Cash Flow (TTM) ───────────────────────────────────────────────────────
    if have_flow_cf:
        metrics['operating_cash_flow'] = _ttm_sum(cash_flow, _C_OCF, n_flow)
        raw_capex = _ttm_sum(cash_flow, _C_CAPEX, n_flow)
        metrics['capital_expenditure'] = abs(raw_capex) if raw_capex else 0.0
        reported_fcf = _ttm_sum(cash_flow, _C_FCF, n_flow)
    else:
        metrics['operating_cash_flow'] = sg(latest_cash, _C_OCF)
        raw_capex = sg(latest_cash, _C_CAPEX)
        metrics['capital_expenditure'] = abs(raw_capex) if raw_capex else 0.0
        reported_fcf = sg(latest_cash, _C_FCF)

    if reported_fcf:
        metrics['free_cash_flow'] = reported_fcf
    else:
        metrics['free_cash_flow'] = metrics['operating_cash_flow'] - metrics['capital_expenditure']

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    metrics['cash']               = sg(latest_balance, _B_CASH)
    metrics['total_assets']       = sg(latest_balance, _B_TOTAL_ASSETS)
    metrics['current_assets']     = sg(latest_balance, _B_CURR_ASSETS)
    metrics['inventory']          = sg(latest_balance, _B_INVENTORY)
    metrics['accounts_receivable']= sg(latest_balance, _B_RECEIVABLES)
    metrics['accounts_payable']   = sg(latest_balance, _B_PAYABLES)
    metrics['current_liabilities']= sg(latest_balance, _B_CURR_LIAB)
    metrics['total_liabilities']  = sg(latest_balance, _B_TOTAL_LIAB)
    metrics['short_term_debt']    = sg(latest_balance, _B_ST_DEBT)
    metrics['long_term_debt']     = sg(latest_balance, _B_LT_DEBT)
    metrics['total_debt']         = metrics['short_term_debt'] + metrics['long_term_debt']
    metrics['shareholders_equity']= sg(latest_balance, _B_EQUITY)
    metrics['retained_earnings']  = sg(latest_balance, _B_RETAINED)
    metrics['book_value']         = metrics['shareholders_equity']
    shares_bs                     = sg(latest_balance, _B_SHARES_OUT)
    metrics['shares_outstanding'] = shares_bs or metrics['diluted_shares'] or 0

    # ── Market Data ───────────────────────────────────────────────────────────
    metrics['current_price']     = 0.0
    metrics['market_cap']        = 0.0
    metrics['enterprise_value']  = 0.0
    if price_data:
        lp = price_data[-1]
        metrics['current_price']    = sg(lp, 'close') or sg(lp, 'adjusted_close')
        metrics['market_cap']       = sg(lp, 'market_cap')
        metrics['enterprise_value'] = sg(lp, 'enterprise_value')

    shares = metrics['shares_outstanding']
    if shares > 0:
        metrics['free_cash_flow_per_share'] = sd(metrics['free_cash_flow'], shares)
        metrics['eps_diluted'] = metrics['eps_diluted'] or sd(metrics['net_income'], shares)
    else:
        metrics['free_cash_flow_per_share'] = 0.0

    rev = metrics['revenue']

    # ── Profitability Ratios ──────────────────────────────────────────────────
    if rev > 0:
        metrics['gross_margin']    = sd(metrics['gross_profit'],     rev)
        metrics['operating_margin']= sd(metrics['operating_income'], rev)
        metrics['net_margin']      = sd(metrics['net_income'],        rev)
        metrics['ebit_margin']     = sd(metrics['ebit'],              rev)
        metrics['ebitda_margin']   = sd(metrics['ebitda'],            rev)
        metrics['ocf_margin']      = sd(metrics['operating_cash_flow'], rev)
        metrics['fcf_margin']      = sd(metrics['free_cash_flow'],    rev)

    # ── Return Metrics ────────────────────────────────────────────────────────
    eq = metrics['shareholders_equity']
    if eq > 0:
        metrics['roe'] = rate_as_decimal(sd(metrics['net_income'], eq))
    if metrics['total_assets'] > 0:
        metrics['roa'] = rate_as_decimal(sd(metrics['net_income'], metrics['total_assets']))

    invested_capital = metrics['total_debt'] + eq
    if invested_capital > 0:
        nopat = metrics['operating_income'] * 0.79   # rough NOPAT (21% tax)
        metrics['roic'] = rate_as_decimal(sd(nopat, invested_capital))

    # ── Leverage Ratios ───────────────────────────────────────────────────────
    metrics['debt_to_equity'] = sd(metrics['total_debt'], eq) if eq > 0 else 0.0
    if metrics['total_assets'] > 0:
        metrics['debt_to_assets'] = sd(metrics['total_debt'], metrics['total_assets'])
    if metrics['ebitda'] > 0:
        net_debt = metrics['total_debt'] - metrics['cash']
        metrics['net_debt_to_ebitda'] = sd(net_debt, metrics['ebitda'])
    if metrics['free_cash_flow'] > 0:
        net_debt = metrics['total_debt'] - metrics['cash']
        metrics['net_debt_to_fcf'] = sd(net_debt, metrics['free_cash_flow'])

    interest = abs(sg(latest_income, _I_INTEREST_EXP))
    if interest > 0:
        metrics['interest_coverage'] = sd(metrics['operating_income'], interest)

    # ── Liquidity ─────────────────────────────────────────────────────────────
    cl = metrics['current_liabilities']
    if cl > 0:
        metrics['current_ratio'] = sd(metrics['current_assets'], cl)
        metrics['quick_ratio']   = sd(metrics['current_assets'] - metrics['inventory'], cl)
    if metrics['total_debt'] > 0:
        metrics['cash_to_debt']  = sd(metrics['cash'], metrics['total_debt'])

    # ── Efficiency ────────────────────────────────────────────────────────────
    if metrics['total_assets'] > 0 and rev > 0:
        metrics['asset_turnover'] = sd(rev, metrics['total_assets'])

    cogs = sg(latest_income, _I_COST_REVENUE)
    if metrics['inventory'] > 0 and cogs > 0:
        metrics['inventory_turnover'] = sd(cogs, metrics['inventory'])
    else:
        metrics['inventory_turnover'] = 0.0

    if metrics['accounts_payable'] > 0 and cogs > 0:
        metrics['payables_turnover'] = sd(cogs, metrics['accounts_payable'])
    else:
        metrics['payables_turnover'] = 0.0

    if metrics['accounts_receivable'] > 0 and rev > 0:
        metrics['receivables_turnover'] = sd(rev, metrics['accounts_receivable'])
    else:
        metrics['receivables_turnover'] = 0.0

    inv_days = sd(365.0, metrics['inventory_turnover'])    if metrics['inventory_turnover']    > 0 else 0.0
    rec_days = sd(365.0, metrics['receivables_turnover'])  if metrics['receivables_turnover']  > 0 else 0.0
    pay_days = sd(365.0, metrics['payables_turnover'])     if metrics['payables_turnover']     > 0 else 0.0
    metrics['cash_conversion_cycle'] = inv_days + rec_days - pay_days

    if metrics['net_income'] > 0:
        metrics['fcf_conversion'] = sd(metrics['free_cash_flow'], metrics['net_income'])
        # Mixed units / restatements can produce absurd FCF > NI; do not leak into scoring.
        if metrics['fcf_conversion'] > 1.15:
            metrics['fcf_conversion'] = 0.0
    if metrics['operating_cash_flow'] > 0:
        metrics['ocf_to_fcf'] = sd(metrics['free_cash_flow'], metrics['operating_cash_flow'])

    # ── Growth Rates ─────────────────────────────────────────────────────────
    # Use TTM revenue for growth comparisons (sum of last 4Q vs sum of prior 4Q, etc.)
    ttm_rev = rev  # already TTM from above

    # YoY: TTM now vs TTM one year ago (quarters 4-7)
    if len(income_statement) >= 8:
        rev_1ya_ttm = sum(sg(income_statement[i], _I_REVENUE) for i in range(4, 8))
        if rev_1ya_ttm > 0 and ttm_rev > 0:
            metrics['revenue_growth_1y'] = sd(ttm_rev - rev_1ya_ttm, rev_1ya_ttm)
    elif len(income_statement) >= 2:
        prev_rev = sg(prev_income, _I_REVENUE)
        if prev_rev > 0 and ttm_rev > 0:
            metrics['revenue_growth_1y'] = sd(ttm_rev - prev_rev, prev_rev)

    # 4-year CAGR: TTM now vs TTM 4 years ago (quarters 16-19)
    if len(income_statement) >= 20:
        rev_4ya_ttm = sum(sg(income_statement[i], _I_REVENUE) for i in range(16, 20))
        if rev_4ya_ttm > 0 and ttm_rev > 0:
            metrics['revenue_cagr_4y'] = (ttm_rev / rev_4ya_ttm) ** (1/4) - 1
    elif len(income_statement) >= 5:
        rev_4ya = sg(income_statement[4], _I_REVENUE)
        if rev_4ya > 0 and ttm_rev > 0:
            metrics['revenue_cagr_4y'] = (ttm_rev / (rev_4ya * 4)) ** (1/4) - 1 if rev_4ya > 0 else 0.0

    # 3-year CAGR: TTM now vs TTM 3 years ago (quarters 12-15)
    if len(income_statement) >= 16:
        rev_3ya_ttm = sum(sg(income_statement[i], _I_REVENUE) for i in range(12, 16))
        if rev_3ya_ttm > 0 and ttm_rev > 0:
            metrics['revenue_cagr_3y'] = (ttm_rev / rev_3ya_ttm) ** (1/3) - 1
    elif len(income_statement) >= 13:
        rev_3ya = sg(income_statement[12], _I_REVENUE)
        if rev_3ya > 0 and ttm_rev > 0:
            metrics['revenue_cagr_3y'] = (ttm_rev / (rev_3ya * 4)) ** (1/3) - 1 if rev_3ya > 0 else 0.0

    # ── Revenue Acceleration (QoQ trend) ─────────────────────────────────────
    # Compare last 4q growth vs prior 4q growth — positive = accelerating
    if len(income_statement) >= 8:
        rev_4q   = sum(sg(income_statement[i], _I_REVENUE) for i in range(4))
        rev_prev4 = sum(sg(income_statement[i], _I_REVENUE) for i in range(4, 8))
        if rev_prev4 > 0 and rev_4q > 0:
            recent_growth = (rev_4q - rev_prev4) / rev_prev4
            if len(income_statement) >= 12:
                rev_8q = sum(sg(income_statement[i], _I_REVENUE) for i in range(8, 12))
                if rev_8q > 0:
                    older_growth = (rev_prev4 - rev_8q) / rev_8q
                    metrics['revenue_acceleration'] = recent_growth - older_growth
                else:
                    metrics['revenue_acceleration'] = 0.0
            else:
                metrics['revenue_acceleration'] = 0.0

    # ── Revenue Growth Consistency ───────────────────────────────────────────
    # Compute rolling annual (TTM) revenue growth rates across available years.
    # A low coefficient of variation (stddev / |mean|) signals stable compounders;
    # high CoV signals cyclical or lumpy businesses.  Output: 0.0 (no data) to 1.0
    # (perfectly stable).  Inversely related to CoV.
    if len(income_statement) >= 12:
        annual_growths = []
        n_windows = min((len(income_statement) - 4) // 4, 4)  # up to 4 annual growth observations
        for w in range(n_windows):
            start = w * 4
            ttm_cur = sum(sg(income_statement[i], _I_REVENUE) for i in range(start, start + 4))
            ttm_prev = sum(sg(income_statement[i], _I_REVENUE) for i in range(start + 4, start + 8))
            if ttm_prev > 0 and ttm_cur > 0:
                annual_growths.append((ttm_cur - ttm_prev) / ttm_prev)
        if len(annual_growths) >= 2:
            mean_g = statistics.mean(annual_growths)
            std_g = statistics.stdev(annual_growths)
            if abs(mean_g) > 0.01:
                cov = std_g / abs(mean_g)
            else:
                cov = std_g / 0.01
            # Convert CoV to 0–1 consistency score: CoV=0 → 1.0, CoV>=2 → 0.0
            metrics['revenue_growth_consistency'] = max(0.0, min(1.0, 1.0 - cov / 2.0))
            # Also flag if growth is consistently positive (all windows > 0)
            metrics['growth_all_positive'] = all(g > 0 for g in annual_growths)
        else:
            metrics['revenue_growth_consistency'] = 0.5  # neutral with insufficient data

    # ── Gross Margin Expansion (trend over 4–8 quarters) ─────────────────────
    if len(income_statement) >= 8:
        def _gm(stmt):
            r = sg(stmt, _I_REVENUE)
            gp = _adjusted_gross_profit(stmt)
            return sd(gp, r) if r > 0 else None
        gm_now  = _gm(income_statement[0])
        gm_old  = _gm(income_statement[7])  # 2y back
        if gm_now is not None and gm_old is not None and gm_old > 0:
            metrics['gross_margin_expansion'] = gm_now - gm_old  # positive = expanding

    # Net income growth: TTM vs prior TTM
    if len(income_statement) >= 8:
        ni_1ya_ttm = sum(sg(income_statement[i], _I_NET_INCOME) for i in range(4, 8))
        if ni_1ya_ttm > 0 and metrics['net_income'] > 0:
            metrics['net_income_growth'] = sd(metrics['net_income'] - ni_1ya_ttm, ni_1ya_ttm)
    else:
        prev_ni = sg(prev_income, _I_NET_INCOME)
        if prev_ni > 0 and metrics['net_income'] > 0:
            metrics['net_income_growth'] = sd(metrics['net_income'] - prev_ni, prev_ni)

    # EPS growth: TTM vs prior TTM
    if len(income_statement) >= 8:
        eps_1ya_ttm = sum(sg(income_statement[i], _I_EPS_DILUTED) for i in range(4, 8))
        if eps_1ya_ttm > 0 and metrics['eps_diluted'] > 0:
            metrics['eps_growth'] = sd(metrics['eps_diluted'] - eps_1ya_ttm, eps_1ya_ttm)
    else:
        prev_eps = sg(prev_income, _I_EPS_DILUTED)
        if prev_eps > 0 and metrics['eps_diluted'] > 0:
            metrics['eps_growth'] = sd(metrics['eps_diluted'] - prev_eps, prev_eps)

    # ── Owner Earnings (Buffett) ───────────────────────────────────────────────
    # owner_earnings = OCF - CapEx - SBC
    oe = metrics['operating_cash_flow'] - metrics['capital_expenditure'] - metrics['sbc']
    metrics['owner_earnings'] = oe

    diluted_shares_now = metrics['diluted_shares'] or shares
    if diluted_shares_now > 0:
        oeps = sd(oe, diluted_shares_now)
        metrics['owner_earnings_per_share'] = oeps
    else:
        oeps = 0.0
        metrics['owner_earnings_per_share'] = 0.0

    # Owner Earnings CAGR — needs historical data (quarterly → annualise)
    metrics['oeps_cagr'] = _calculate_oeps_cagr(income_statement, cash_flow, balance_sheet)

    # ── Reinvestment Rate (how fast can it compound at current ROIC) ──────────
    # reinvestment_rate = sustainable_growth_rate / ROIC  (approx via RE growth)
    if metrics.get('roic', 0) > 0 and metrics.get('revenue_cagr_4y', 0) > 0:
        metrics['reinvestment_rate'] = metrics['revenue_cagr_4y'] / metrics['roic']

    # Inject EPS growth from Highlights BEFORE computing growth_score_raw
    # (EODHD quarterly data doesn't have per-share EPS, so our computed value is always 0).
    hl = highlights or {}
    _hl_eps_g_raw = hl.get("QuarterlyEarningsGrowthYOY")
    if _hl_eps_g_raw is not None and _hl_eps_g_raw != "":
        _hl_eps_g = float(_hl_eps_g_raw) if isinstance(_hl_eps_g_raw, (int, float)) else 0.0
        if _hl_eps_g != 0.0 or not metrics.get('eps_growth'):
            metrics['eps_growth'] = _hl_eps_g

    # Final Growth Score  (0-1 continuous, then used in scoring)
    metrics['growth_score_raw'] = _calculate_growth_score(metrics)

    # If last-quote price disagrees wildly with market_cap / diluted shares, trust the
    # latter for USD mega-caps (bad close scale or stale feed otherwise blows up P/E).
    mktcap_hint = float(metrics.get("market_cap") or 0.0)
    sh_hint = float(
        metrics.get("diluted_shares")
        or metrics.get("shares_outstanding")
        or 0.0
    )
    raw_px = float(metrics.get("current_price") or 0.0)
    if mktcap_hint > 0 and sh_hint > 0 and raw_px > 0:
        implied_px = mktcap_hint / sh_hint
        if implied_px > 0:
            ratio = raw_px / implied_px
            if ratio > 4.0 or ratio < 0.25:
                metrics["current_price"] = implied_px

    # ── Valuation ─────────────────────────────────────────────────────────────
    price = metrics['current_price']
    eps_d = metrics['eps_diluted']
    mktcap= metrics['market_cap']
    ev    = metrics['enterprise_value']

    if price > 0 and eps_d > 0:
        metrics['pe_ratio'] = sd(price, eps_d)
    # PEG = P/E ÷ growth_rate_pct; use BEST positive growth rate available.
    # OEPS CAGR can be depressed by CapEx/SBC surges (MSFT, META), so also consider
    # EPS growth and revenue CAGR — pick whichever is highest and positive.
    pe = metrics.get('pe_ratio', 0)
    _oeps_g = metrics.get('oeps_cagr', 0) or 0
    _eps_g  = metrics.get('eps_growth', 0) or 0
    _ni_g   = metrics.get('net_income_growth', 0) or 0
    _rev4   = metrics.get('revenue_cagr_4y', 0) or 0
    _rev3   = metrics.get('revenue_cagr_3y', 0) or 0

    # Gate: if revenue is flat (<5% CAGR) but NI growth is extreme, the NI
    # spike is likely one-time (asset sale, tax reversal).  Exclude NI growth
    # from PEG candidates so PEG reflects durable growth only.
    _rev_best = max(_rev4, _rev3)
    _peg_candidates = [_oeps_g, _eps_g, _rev4, _rev3]
    if _rev_best >= 0.05 or _ni_g <= 0.22:
        _peg_candidates.append(_ni_g)

    growth_for_peg = max((g for g in _peg_candidates if g > 0), default=0) * 100
    if pe > 0 and growth_for_peg > 0:
        metrics['peg_ratio'] = pe / growth_for_peg
    if mktcap > 0 and rev > 0:
        metrics['ps_ratio'] = sd(mktcap, rev)
    if mktcap > 0 and metrics['book_value'] > 0:
        metrics['pb_ratio'] = sd(mktcap, metrics['book_value'])
    if ev > 0 and metrics['ebitda'] > 0:
        metrics['ev_ebitda'] = sd(ev, metrics['ebitda'])
        # Tiny EV/EBITDA ratios are usually scale/units artifacts, not deep value.
        ev_e = metrics['ev_ebitda']
        if 0 < ev_e < 0.5 or ev_e > 120:
            metrics['ev_ebitda'] = 0.0
    if ev > 0 and metrics['ebit'] > 0:
        metrics['ev_ebit'] = sd(ev, metrics['ebit'])
    if ev > 0 and metrics['free_cash_flow'] > 0:
        metrics['ev_fcf'] = sd(ev, metrics['free_cash_flow'])
    if price > 0 and eps_d > 0:
        metrics['earnings_yield'] = sd(eps_d, price)
    fcfps = metrics['free_cash_flow_per_share']
    if price > 0 and fcfps > 0:
        metrics['fcf_yield'] = sd(fcfps, price)
        # Per-share FCF vs price should sit in single digits for almost all liquid names.
        if metrics['fcf_yield'] > 0.35:
            metrics['fcf_yield'] = 0.0

    # ── Prefer EODHD Highlights ratios (currency-correct) ───────────────────
    # For non-USD reporters our computed P/E and PEG are USD÷local-currency
    # nonsense.  EODHD already handles the conversion, so trust their numbers.
    hl = highlights or {}
    _hl_pe = safe_get(hl, "PERatio")
    _hl_peg = safe_get(hl, "PEGRatio")

    if _hl_pe and _hl_pe > 0:
        our_pe = metrics.get('pe_ratio', 0)
        if our_pe > 0:
            ratio = our_pe / _hl_pe
            # If our P/E is wildly different (>3x or <0.33x), trust Highlights
            if ratio > 3.0 or ratio < 0.33:
                metrics['pe_ratio'] = _hl_pe
                metrics['earnings_yield'] = sd(1.0, _hl_pe)
        else:
            metrics['pe_ratio'] = _hl_pe
            metrics['earnings_yield'] = sd(1.0, _hl_pe)

    if _hl_peg and 0 < _hl_peg < 10:
        our_peg = metrics.get('peg_ratio', 0)
        if our_peg <= 0 or our_peg > 10:
            metrics['peg_ratio'] = _hl_peg
        else:
            ratio = our_peg / _hl_peg
            if ratio > 3.0 or ratio < 0.33:
                metrics['peg_ratio'] = _hl_peg

    # Revenue growth fallback from Highlights (if quarterly-computed value is missing)
    _hl_rev_g_raw = hl.get("QuarterlyRevenueGrowthYOY")
    if _hl_rev_g_raw is not None and _hl_rev_g_raw != "":
        _hl_rev_g = float(_hl_rev_g_raw) if isinstance(_hl_rev_g_raw, (int, float)) else 0.0
        if _hl_rev_g != 0.0 and not metrics.get('revenue_growth_1y'):
            metrics['revenue_growth_1y'] = _hl_rev_g

    # ── Piotroski F-Score (9 pts) ─────────────────────────────────────────────
    ps = 0
    roa = metrics.get('roa', 0.0)
    if metrics['net_income'] > 0:           ps += 1
    if roa > 0:                             ps += 1
    if metrics['operating_cash_flow'] > 0:  ps += 1
    if metrics['operating_cash_flow'] > metrics['net_income']: ps += 1  # accruals
    prev_td = sg(prev_balance, _B_ST_DEBT) + sg(prev_balance, _B_LT_DEBT)
    if prev_td > 0 and metrics['total_debt'] < prev_td: ps += 1
    prev_cr = sd(sg(prev_balance, _B_CURR_ASSETS), sg(prev_balance, _B_CURR_LIAB)) if sg(prev_balance, _B_CURR_LIAB) > 0 else 0
    if metrics.get('current_ratio', 0) > prev_cr:       ps += 1
    prev_sh = sg(prev_balance, _B_SHARES_OUT)
    if prev_sh > 0 and metrics['shares_outstanding'] <= prev_sh: ps += 1  # no dilution
    prev_gm = sd(sg(prev_income, _I_GROSS_PROFIT), sg(prev_income, _I_REVENUE)) if sg(prev_income, _I_REVENUE) > 0 else 0
    if metrics.get('gross_margin', 0) > prev_gm:        ps += 1
    prev_at = sd(sg(prev_income, _I_REVENUE), sg(prev_balance, _B_TOTAL_ASSETS)) if sg(prev_balance, _B_TOTAL_ASSETS) > 0 else 0
    if metrics.get('asset_turnover', 0) > prev_at:      ps += 1
    metrics['piotroski_score'] = ps

    # ── Altman Z-Score ────────────────────────────────────────────────────────
    ta = metrics['total_assets']
    if ta > 0:
        wc  = metrics['current_assets'] - cl
        z1  = sd(wc,  ta) * 1.2
        z2  = sd(metrics['retained_earnings'], ta) * 1.4
        z3  = sd(metrics['ebit'], ta) * 3.3
        z4  = sd(mktcap, metrics['total_liabilities']) * 0.6 if metrics['total_liabilities'] > 0 else 0
        z5  = sd(rev, ta) * 0.999
        metrics['altman_z_score'] = z1 + z2 + z3 + z4 + z5

    # ── Momentum (price history) ──────────────────────────────────────────────
    close_prices = [p.get('close') or p.get('adjusted_close', 0) for p in price_data if p.get('close') or p.get('adjusted_close')]
    if len(close_prices) >= 252:
        metrics['momentum_12m']        = sd(close_prices[-1] - close_prices[-252], close_prices[-252])
        metrics['52_week_high']        = max(close_prices[-252:])
        metrics['52_week_low']         = min(close_prices[-252:])
        metrics['distance_from_52w_high'] = sd(close_prices[-1] - metrics['52_week_high'], metrics['52_week_high'])

    # ── Red Flags ─────────────────────────────────────────────────────────────
    red_flags = []
    prev_rev2 = sg(prev_income, _I_REVENUE)
    if metrics['inventory'] > 0 and prev_rev2 > 0:
        inv_g = sd(metrics['inventory'] - sg(prev_balance, _B_INVENTORY), sg(prev_balance, _B_INVENTORY)) if sg(prev_balance, _B_INVENTORY) > 0 else 0
        rev_g = sd(rev - prev_rev2, prev_rev2)
        if inv_g > rev_g + 0.1:
            red_flags.append("Inventory growing faster than revenue")

    if metrics['accounts_receivable'] > 0 and prev_rev2 > 0:
        rec_g = sd(metrics['accounts_receivable'] - sg(prev_balance, _B_RECEIVABLES), sg(prev_balance, _B_RECEIVABLES)) if sg(prev_balance, _B_RECEIVABLES) > 0 else 0
        rev_g = sd(rev - prev_rev2, prev_rev2)
        if rec_g > rev_g + 0.1:
            red_flags.append("Receivables growing faster than revenue")

    if metrics['operating_cash_flow'] > 0 and metrics['net_income'] > 0:
        if metrics['operating_cash_flow'] < metrics['net_income'] * 0.7:
            red_flags.append("Cash flow significantly weaker than earnings")

    if metrics.get('debt_to_equity', 0) > 2.5:
        red_flags.append("High debt-to-equity ratio")
    if metrics['net_income'] < 0:
        red_flags.append("Negative net income")
    if metrics['free_cash_flow'] < 0:
        red_flags.append("Negative free cash flow")

    metrics['red_flags']     = red_flags
    metrics['red_flag_count']= len(red_flags)

    return metrics


# ─── Owner Earnings helpers ───────────────────────────────────────────────────

def _annualise_quarters(statement: List[Dict], value_key: str, n_quarters: int = 4) -> float:
    """Sum n most-recent quarters as a proxy for TTM."""
    total = 0.0
    for i, q in enumerate(statement[:n_quarters]):
        total += sg(q, value_key)
    return total


def _calculate_oeps_cagr(income_stmts: List[Dict], cash_stmts: List[Dict],
                         balance_stmts: List[Dict] | None = None) -> float:
    """
    Compute Owner Earnings Per Share CAGR over available history (TTM-based).
    oeps = (OCF - CapEx - SBC) / shares_outstanding  (all TTM annualized)
    cagr = (oeps_end / oeps_start) ** (1/years) - 1
    """
    if len(cash_stmts) < 8:
        return 0.0
    bal = balance_stmts or []

    def _oeps_ttm(start_idx: int) -> float:
        """Compute annualized OEPS from 4 quarters starting at start_idx."""
        if start_idx + 4 > len(cash_stmts):
            return 0.0
        ocf = sum(sg(cash_stmts[start_idx + j], _C_OCF) for j in range(4))
        capex = abs(sum(sg(cash_stmts[start_idx + j], _C_CAPEX) for j in range(4)))
        sbc = sum(sg(cash_stmts[start_idx + j], _I_SBC) for j in range(4))
        # Shares from latest balance sheet in the window
        bs = bal[start_idx] if start_idx < len(bal) else {}
        inc = income_stmts[start_idx] if start_idx < len(income_stmts) else {}
        shares = sg(bs, _B_SHARES_OUT) or sg(inc, _I_DILUTED_SHARES)
        oe = ocf - capex - sbc
        return sd(oe, shares) if shares > 0 else 0.0

    # TTM now (quarters 0-3) vs TTM N years ago
    oeps_end = _oeps_ttm(0)

    # Try 4-year lookback first (quarters 16-19), fall back to 3-year (12-15)
    lookback_q = 16
    if lookback_q + 4 > len(cash_stmts):
        lookback_q = 12
    if lookback_q + 4 > len(cash_stmts):
        lookback_q = 8
    if lookback_q + 4 > len(cash_stmts):
        return 0.0

    oeps_start = _oeps_ttm(lookback_q)

    if oeps_start <= 0 or oeps_end <= 0:
        return 0.0

    actual_years = lookback_q / 4.0
    try:
        cagr = (oeps_end / oeps_start) ** (1 / actual_years) - 1
        return max(-1.0, min(cagr, 5.0))
    except (ZeroDivisionError, ValueError):
        return 0.0


def _calculate_growth_score(m: Dict[str, Any]) -> float:
    """
    Composite growth score (0-1) combining:
      - OEPS CAGR             (35%) — capped at 50% CAGR for perfect
      - ROIC                  (20%) — capped at 30% ROIC
      - Revenue CAGR 4y       (20%) — capped at 40% (raised from 20%)
      - Gross margin level    (10%)
      - Gross margin expansion (8%) — trend, not just level
      - Revenue acceleration   (7%) — is growth speeding up?

    Multipliers (penalty factors):
      - debt: net debt / EBITDA high penalises
    """
    oeps_cagr  = float(m.get('oeps_cagr', 0.0) or 0.0)
    # For CapEx/SBC-heavy compounders (MSFT, META), OEPS CAGR understates true
    # earnings power growth. Use the best of OEPS, EPS growth, and NI growth.
    eps_g      = float(m.get('eps_growth', 0.0) or 0.0)
    ni_g       = float(m.get('net_income_growth', 0.0) or 0.0)
    earnings_growth = max(oeps_cagr, eps_g, ni_g)
    roic       = float(m.get('roic', 0.0) or 0.0)
    rev_4y     = float(m.get('revenue_cagr_4y', 0.0) or 0.0)
    rev_3y     = float(m.get('revenue_cagr_3y', 0.0) or 0.0)
    rev_1y     = float(m.get('revenue_growth_1y', 0.0) or 0.0)
    # Prefer a durable top-line signal: do not let a weak 4y print erase a healthy 3y trend.
    rev_cagr   = max(rev_4y, rev_3y, rev_1y)
    gm         = m.get('gross_margin', 0.0)
    gm_exp     = m.get('gross_margin_expansion', 0.0)   # pp gained over 2y
    rev_accel  = m.get('revenue_acceleration', 0.0)     # recent 4q growth - older 4q growth

    # Gross margin from filings is not comparable for many banks / specialty finance /
    # some biotech (gross profit vs revenue can exceed 100% or be meaningless). Do not
    # let that dominate the growth composite.
    if gm > 0.85 or gm < 0.0:
        gm = 0.36
        gm_exp = 0.0
    else:
        gm_exp = max(-0.18, min(0.18, gm_exp))

    # If revenue is flat but NI growth is extreme, the spike is likely one-time
    # (asset sale, tax reversal, litigation win).  Hard-cap the earnings_growth
    # contribution so it can't dominate the growth score or game PEG.
    rev_lo = min(rev_4y, rev_3y) if (rev_4y or rev_3y) and (rev_3y or rev_4y) else rev_cagr
    if rev_lo < 0.035 and earnings_growth > 0.22:
        earnings_growth = min(0.12, rev_lo * 3 + 0.05)

    # Normalise each component to 0-1 range
    # Raised ceilings: 50% earnings growth, 40% rev CAGR = perfect score (10x territory)
    oeps_norm  = min(max(earnings_growth / 0.50, 0.0), 1.0)   # 50% growth = perfect
    roic_norm  = min(max(roic / 0.30, 0.0), 1.0)         # 30% ROIC = perfect
    rev_norm   = min(max(rev_cagr / 0.40, 0.0), 1.0)     # 40% rev CAGR = perfect
    # Modest lift for "boring" durable growers: healthy mid‑single‑digit+ revenue with ROIC.
    rev_head = max(rev_4y, rev_3y)
    if 0.055 <= rev_head <= 0.30 and roic >= 0.12:
        rev_norm = min(1.0, rev_norm + 0.10)
    gm_norm    = min(max(gm / 0.60, 0.0), 1.0)           # 60% GM = perfect
    # Margin expansion: +10pp over 2y = perfect; negative = small penalty
    gm_exp_norm = min(max((gm_exp + 0.05) / 0.15, 0.0), 1.0)
    # Revenue acceleration: +15pp acceleration = perfect
    accel_norm  = min(max((rev_accel + 0.05) / 0.20, 0.0), 1.0)

    raw = (oeps_norm  * 0.35 +
           roic_norm  * 0.20 +
           rev_norm   * 0.20 +
           gm_norm    * 0.10 +
           gm_exp_norm* 0.08 +
           accel_norm * 0.07)

    # Stability multiplier: reward consistent growers, penalize volatile ones.
    # consistency=1.0 → +12% bonus; consistency=0.5 → neutral; consistency=0 → -15% penalty.
    _raw_con = m.get('revenue_growth_consistency')
    consistency = float(_raw_con) if _raw_con is not None else 0.5
    all_positive = m.get('growth_all_positive', False)
    stability_mult = 0.85 + 0.27 * consistency  # range: 0.85 (CoV=high) to 1.12 (CoV=0)
    if all_positive and consistency >= 0.7 and rev_cagr >= 0.08:
        stability_mult += 0.05  # extra reward for never-negative revenue growth + decent rate

    # Debt penalty
    nd_ebitda = m.get('net_debt_to_ebitda', 0.0)
    debt_mult = max(0.5, 1.0 - max(0.0, nd_ebitda - 1.0) * 0.1)

    return min(raw * debt_mult * stability_mult, 1.0)
