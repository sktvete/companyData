from __future__ import annotations

import re

from equity_sorter.io_utils import stable_hash


def normalize_name(value: str | None) -> str:
    if not value:
        return "unknown"
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip() or "unknown"


def make_company_id(name: str | None, country: str | None) -> str:
    normalized = normalize_name(name)
    return "cmp_" + stable_hash(f"{normalized}|{country or 'unknown'}")[:16]


def make_security_id(company_id: str, security_type: str | None, share_class: str | None = None) -> str:
    return "sec_" + stable_hash(f"{company_id}|{security_type or 'unknown'}|{share_class or 'default'}")[:16]


def make_listing_id(security_id: str, exchange_code: str, ticker: str) -> str:
    return "lst_" + stable_hash(f"{security_id}|{exchange_code}|{ticker.upper()}")[:16]


def make_identifier_id(listing_id: str, id_type: str, id_value: str) -> str:
    return "id_" + stable_hash(f"{listing_id}|{id_type}|{id_value}")[:16]


def make_quality_event_id(table_name: str, entity_id: str, rule_name: str, message: str) -> str:
    return "dq_" + stable_hash(f"{table_name}|{entity_id}|{rule_name}|{message}")[:16]
