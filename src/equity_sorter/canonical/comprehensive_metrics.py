#!/usr/bin/env python3

"""
Comprehensive financial metrics calculation using correct EODHD field names.
Includes Owner Earnings growth scoring per Buffett/Munger methodology.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date
import math

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


# Short aliases used throughout this module
sg = safe_get
sd = safe_divide


def calculate_comprehensive_metrics(financial_data: Dict[str, Any],
                                    price_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate all comprehensive financial metrics from EODHD data."""

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

    # ── Income Statement ──────────────────────────────────────────────────────
    metrics['revenue']          = sg(latest_income, _I_REVENUE)
    metrics['gross_profit']     = sg(latest_income, _I_GROSS_PROFIT)
    metrics['operating_income'] = sg(latest_income, _I_OP_INCOME)
    metrics['ebit']             = sg(latest_income, _I_EBIT)   or sg(latest_income, _I_OP_INCOME)
    metrics['ebitda']           = sg(latest_income, _I_EBITDA)
    metrics['pretax_income']    = sg(latest_income, _I_PRETAX)
    metrics['net_income']       = sg(latest_income, _I_NET_INCOME)
    metrics['eps_basic']        = sg(latest_income, _I_EPS_BASIC)
    metrics['eps_diluted']      = sg(latest_income, _I_EPS_DILUTED)
    # diluted shares: not in quarterly income → use balance sheet shares outstanding
    metrics['diluted_shares']   = (sg(latest_balance, _B_SHARES_OUT)
                                   or sg(latest_income, _I_DILUTED_SHARES))
    # SBC lives in cash flow statement (confirmed for EODHD)
    metrics['sbc']              = sg(latest_cash, _I_SBC) or sg(latest_income, _I_SBC)

    # ── Cash Flow ─────────────────────────────────────────────────────────────
    metrics['operating_cash_flow'] = sg(latest_cash, _C_OCF)
    raw_capex                      = sg(latest_cash, _C_CAPEX)
    metrics['capital_expenditure'] = abs(raw_capex) if raw_capex else 0.0
    # FCF = reported or derived
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
        metrics['roe'] = sd(metrics['net_income'], eq)
    if metrics['total_assets'] > 0:
        metrics['roa'] = sd(metrics['net_income'], metrics['total_assets'])

    invested_capital = metrics['total_debt'] + eq
    if invested_capital > 0:
        nopat = metrics['operating_income'] * 0.79   # rough NOPAT (21% tax)
        metrics['roic'] = sd(nopat, invested_capital)

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
    if metrics['operating_cash_flow'] > 0:
        metrics['ocf_to_fcf'] = sd(metrics['free_cash_flow'], metrics['operating_cash_flow'])

    # ── Growth Rates ─────────────────────────────────────────────────────────
    prev_rev = sg(prev_income, _I_REVENUE)
    if prev_rev > 0 and rev > 0:
        metrics['revenue_growth_1y'] = sd(rev - prev_rev, prev_rev)

    if len(income_statement) >= 5:
        rev_4ya = sg(income_statement[4], _I_REVENUE)
        if rev_4ya > 0 and rev > 0:
            metrics['revenue_cagr_4y'] = (rev / rev_4ya) ** (1/4) - 1

    if len(income_statement) >= 13:
        rev_3ya = sg(income_statement[12], _I_REVENUE)
        if rev_3ya > 0 and rev > 0:
            metrics['revenue_cagr_3y'] = (rev / rev_3ya) ** (1/3) - 1

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

    # ── Gross Margin Expansion (trend over 4–8 quarters) ─────────────────────
    if len(income_statement) >= 8:
        def _gm(stmt): 
            r = sg(stmt, _I_REVENUE); gp = sg(stmt, _I_GROSS_PROFIT)
            return sd(gp, r) if r > 0 else None
        gm_now  = _gm(income_statement[0])
        gm_old  = _gm(income_statement[7])  # 2y back
        if gm_now is not None and gm_old is not None and gm_old > 0:
            metrics['gross_margin_expansion'] = gm_now - gm_old  # positive = expanding

    prev_ni = sg(prev_income, _I_NET_INCOME)
    if prev_ni > 0 and metrics['net_income'] > 0:
        metrics['net_income_growth'] = sd(metrics['net_income'] - prev_ni, prev_ni)

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

    # Final Growth Score  (0-1 continuous, then used in scoring)
    metrics['growth_score_raw'] = _calculate_growth_score(metrics)

    # ── Valuation ─────────────────────────────────────────────────────────────
    price = metrics['current_price']
    eps_d = metrics['eps_diluted']
    mktcap= metrics['market_cap']
    ev    = metrics['enterprise_value']

    if price > 0 and eps_d > 0:
        metrics['pe_ratio'] = sd(price, eps_d)
    # PEG = P/E ÷ growth_rate_pct; use best available growth rate
    pe = metrics.get('pe_ratio', 0)
    growth_for_peg = (metrics.get('oeps_cagr', 0) or
                      metrics.get('revenue_cagr_4y', 0) or
                      metrics.get('revenue_cagr_3y', 0)) * 100  # convert to %
    if pe > 0 and growth_for_peg > 0:
        metrics['peg_ratio'] = pe / growth_for_peg
    if mktcap > 0 and rev > 0:
        metrics['ps_ratio'] = sd(mktcap, rev)
    if mktcap > 0 and metrics['book_value'] > 0:
        metrics['pb_ratio'] = sd(mktcap, metrics['book_value'])
    if ev > 0 and metrics['ebitda'] > 0:
        metrics['ev_ebitda'] = sd(ev, metrics['ebitda'])
    if ev > 0 and metrics['ebit'] > 0:
        metrics['ev_ebit'] = sd(ev, metrics['ebit'])
    if ev > 0 and metrics['free_cash_flow'] > 0:
        metrics['ev_fcf'] = sd(ev, metrics['free_cash_flow'])
    if price > 0 and eps_d > 0:
        metrics['earnings_yield'] = sd(eps_d, price)
    fcfps = metrics['free_cash_flow_per_share']
    if price > 0 and fcfps > 0:
        metrics['fcf_yield'] = sd(fcfps, price)

    # ── Piotroski F-Score (9 pts) ─────────────────────────────────────────────
    ps = 0
    if metrics['net_income'] > 0:           ps += 1
    if metrics['roa'] > 0:                  ps += 1  # type: ignore[operator]
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
    Compute Owner Earnings Per Share CAGR over available history.
    oeps = (OCF - CapEx - SBC) / shares_outstanding
    SBC lives in cash flow statement; shares in balance sheet.
    cagr = (oeps_end / oeps_start) ** (1/years) - 1
    """
    if len(cash_stmts) < 8:
        return 0.0
    bal = balance_stmts or []

    def _oeps_at(i: int) -> float:
        cas = cash_stmts[i]   if i < len(cash_stmts)   else {}
        bs  = bal[i]          if i < len(bal)           else {}
        ocf   = sg(cas, _C_OCF)
        capex = abs(sg(cas, _C_CAPEX))
        # SBC is in cash flow statement (not income)
        sbc   = sg(cas, _I_SBC)
        # Shares from balance sheet; fall back to income statement
        inc   = income_stmts[i] if i < len(income_stmts) else {}
        shares = sg(bs, _B_SHARES_OUT) or sg(inc, _I_DILUTED_SHARES)
        oe = ocf - capex - sbc
        return sd(oe, shares) if shares > 0 else 0.0

    # Use most-recent quarter vs quarter 4 years back (16 quarters)
    years = 4
    lookback = min(len(income_stmts) - 1, years * 4)
    oeps_end   = _oeps_at(0)
    oeps_start = _oeps_at(lookback)

    if oeps_start <= 0 or oeps_end <= 0:
        return 0.0

    actual_years = lookback / 4.0
    try:
        cagr = (oeps_end / oeps_start) ** (1 / actual_years) - 1
        return max(-1.0, min(cagr, 5.0))   # clamp to [-100%, +500%]
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
    oeps_cagr  = m.get('oeps_cagr', 0.0)
    roic       = m.get('roic', 0.0)
    rev_cagr   = m.get('revenue_cagr_4y', m.get('revenue_cagr_3y', m.get('revenue_growth_1y', 0.0)))
    gm         = m.get('gross_margin', 0.0)
    gm_exp     = m.get('gross_margin_expansion', 0.0)   # pp gained over 2y
    rev_accel  = m.get('revenue_acceleration', 0.0)     # recent 4q growth - older 4q growth

    # Normalise each component to 0-1 range
    # Raised ceilings: 50% OEPS CAGR, 40% rev CAGR = perfect score (10x territory)
    oeps_norm  = min(max(oeps_cagr / 0.50, 0.0), 1.0)   # 50% CAGR = perfect
    roic_norm  = min(max(roic / 0.30, 0.0), 1.0)         # 30% ROIC = perfect
    rev_norm   = min(max(rev_cagr / 0.40, 0.0), 1.0)     # 40% rev CAGR = perfect
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

    # Debt penalty
    nd_ebitda = m.get('net_debt_to_ebitda', 0.0)
    debt_mult = max(0.5, 1.0 - max(0.0, nd_ebitda - 1.0) * 0.1)

    return min(raw * debt_mult, 1.0)
