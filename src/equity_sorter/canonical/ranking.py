from __future__ import annotations

from typing import Any


def add_ranks(rows: list[dict[str, Any]], score_field: str = "total_garp_score") -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda row: row[score_field], reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def select_ranking_output(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = [
        "rank",
        "mode_rank",
        "company_name",
        "ticker",
        "exchange",
        "country",
        "currency",
        "sector",
        "market_cap_usd",
        "price_data_status",
        "price_adjustment_method",
        "price_confidence",
        "quality_score",
        "quality_explanation",
        "value_score",
        "value_explanation",
        "growth_score",
        "growth_explanation",
        "safety_score",
        "safety_explanation",
        "momentum_score",
        "momentum_explanation",
        "ranking_mode",
        "hybrid_score",
        "total_score",
        "total_garp_score",
        "top_positive_factors",
        "top_negative_factors",
        "red_flags",
        "data_completeness_score",
        "confidence_score",
        "ranking_confidence",
        "timing_confidence",
        "source_lineage",
        "scoring_version",
    ]
    return [{column: row.get(column) for column in columns} for row in rows]
