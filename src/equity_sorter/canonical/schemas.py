from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


class AsDictMixin:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Company(AsDictMixin):
    company_id: str
    legal_name: str
    normalized_name: str
    country_of_incorporation: str | None
    cik: str | None
    lei: str | None
    active_from: str | None
    active_to: str | None
    source_provider: str


@dataclass(frozen=True)
class Security(AsDictMixin):
    security_id: str
    company_id: str
    security_type: str | None
    share_class: str | None
    primary_listing_id: str
    active_from: str | None
    active_to: str | None
    is_active: bool
    delisting_date: str | None
    delisting_reason: str | None
    source_provider: str


@dataclass(frozen=True)
class Listing(AsDictMixin):
    listing_id: str
    security_id: str
    exchange_code: str
    ticker: str
    local_ticker: str
    currency: str | None
    country: str | None
    primary_listing_flag: bool
    valid_from: str | None
    valid_to: str | None
    source_provider: str


@dataclass(frozen=True)
class Identifier(AsDictMixin):
    identifier_id: str
    company_id: str
    security_id: str
    listing_id: str
    id_type: str
    id_value: str
    valid_from: str | None
    valid_to: str | None
    source_provider: str


@dataclass(frozen=True)
class PriceDaily(AsDictMixin):
    security_id: str
    listing_id: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    adjusted_close: float | None
    currency: str | None
    provider: str
    provider_adjustment_method: str
    ingestion_timestamp: str
    data_quality_score: float | None


@dataclass(frozen=True)
class CorporateAction(AsDictMixin):
    security_id: str
    listing_id: str
    action_date: str
    action_type: str
    split_ratio: str | None
    cash_dividend: float | None
    source_provider: str
    confidence_score: float | None


@dataclass(frozen=True)
class FundamentalsQuarterly(AsDictMixin):
    security_id: str
    company_id: str
    fiscal_period: str
    fiscal_period_end_date: str | None
    fiscal_year: int | None
    fiscal_quarter: int | None
    report_date: str | None
    filing_date: str | None
    accepted_timestamp: str | None
    currency: str | None
    accounting_standard: str | None
    restatement_type: str | None
    provider: str
    revenue: float | None
    gross_profit: float | None
    operating_income: float | None
    ebit: float | None
    ebitda: float | None
    net_income: float | None
    eps_basic: float | None
    cash_and_equivalents: float | None
    total_assets: float | None
    total_debt: float | None
    total_equity: float | None
    shares_basic: float | None
    operating_cash_flow: float | None
    capex: float | None
    free_cash_flow: float | None


@dataclass(frozen=True)
class DataQualityEvent(AsDictMixin):
    event_id: str
    table_name: str
    entity_id: str
    rule_name: str
    severity: str
    message: str
    provider: str
    event_timestamp: str


@dataclass(frozen=True)
class FactorSnapshot(AsDictMixin):
    as_of_date: str
    security_id: str
    listing_id: str
    company_id: str
    company_name: str
    ticker: str
    exchange: str
    country: str | None
    currency: str | None
    sector: str | None
    market_cap_usd: float | None
    quality_score: float
    value_score: float
    growth_score: float
    safety_score: float
    momentum_score: float
    total_garp_score: float
    top_positive_factors: str
    top_negative_factors: str
    red_flags: str
    data_completeness_score: float
    confidence_score: float
    timing_confidence: str
    source_lineage: str
    scoring_version: str


@dataclass(frozen=True)
class SourceCandidate(AsDictMixin):
    candidate_id: str
    table_name: str
    entity_id: str
    field_name: str
    value: str | None
    source: str
    source_record_id: str | None
    period: str | None
    report_date: str | None
    filing_date: str | None
    ingestion_timestamp: str
    confidence: float
    pit_safe: bool
    license_class: str
    method: str
    selected_flag: bool
    selection_reason: str
