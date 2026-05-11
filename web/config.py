#!/usr/bin/env python3

from dataclasses import dataclass
from typing import Dict, List, Any
import os
import sys
from pathlib import Path

# Add src to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings as load_base_settings

@dataclass
class AnalysisConfig:
    """Configuration for equity analysis parameters."""
    
    # Stock Selection
    max_stocks: int = 1000
    min_market_cap_millions: float = 100.0  # $100M minimum
    exclude_financials: bool = True  # Exclude banks, insurance
    exclude_utilities: bool = True   # Exclude utilities
    countries: List[str] = None  # None = all available
    
    # GARP Scoring Weights (must sum to 1.0)
    quality_weight: float = 0.25
    value_weight: float = 0.25
    growth_weight: float = 0.25
    safety_weight: float = 0.15
    momentum_weight: float = 0.10
    
    # Quality Metrics
    quality_metrics: Dict[str, float] = None
    
    # Value Metrics
    value_metrics: Dict[str, float] = None
    
    # Growth Metrics
    growth_metrics: Dict[str, float] = None
    
    # Safety Metrics
    safety_metrics: Dict[str, float] = None
    
    # Momentum Metrics
    momentum_metrics: Dict[str, float] = None
    
    def __post_init__(self):
        if self.countries is None:
            self.countries = ["USA"]
        
        # Default metric weights within each category
        if self.quality_metrics is None:
            self.quality_metrics = {
                "gross_margin": 0.25,
                "operating_margin": 0.25, 
                "roa": 0.25,
                "roe": 0.25
            }
        
        if self.value_metrics is None:
            self.value_metrics = {
                "fcf_yield": 0.5,
                "earnings_yield": 0.5
            }
        
        if self.growth_metrics is None:
            self.growth_metrics = {
                "revenue_growth_1y": 0.5,
                "fcf_growth_1y": 0.5
            }
        
        if self.safety_metrics is None:
            self.safety_metrics = {
                "net_debt_to_ebitda": 0.5,
                "debt_to_equity": 0.5
            }
        
        if self.momentum_metrics is None:
            self.momentum_metrics = {
                "distance_from_52w_high": 0.5,
                "momentum_12m_ex_1m": 0.5
            }
        
        # Validate weights sum to 1.0
        total_weight = (self.quality_weight + self.value_weight + 
                       self.growth_weight + self.safety_weight + self.momentum_weight)
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"GARP weights must sum to 1.0, got {total_weight}")

def get_default_configs() -> Dict[str, AnalysisConfig]:
    """Get predefined analysis configurations."""
    
    return {
        "conservative": AnalysisConfig(
            max_stocks=500,
            min_market_cap_millions=500.0,
            quality_weight=0.35,
            value_weight=0.35,
            growth_weight=0.15,
            safety_weight=0.15,
            momentum_weight=0.0,
        ),
        
        "balanced": AnalysisConfig(
            max_stocks=1000,
            min_market_cap_millions=100.0,
            quality_weight=0.25,
            value_weight=0.25,
            growth_weight=0.25,
            safety_weight=0.15,
            momentum_weight=0.10,
        ),
        
        "growth": AnalysisConfig(
            max_stocks=1500,
            min_market_cap_millions=50.0,
            quality_weight=0.20,
            value_weight=0.15,
            growth_weight=0.40,
            safety_weight=0.10,
            momentum_weight=0.15,
        ),
        
        "value": AnalysisConfig(
            max_stocks=800,
            min_market_cap_millions=200.0,
            quality_weight=0.25,
            value_weight=0.40,
            growth_weight=0.10,
            safety_weight=0.20,
            momentum_weight=0.05,
        ),
        
        "custom": AnalysisConfig(
            max_stocks=1000,
            min_market_cap_millions=100.0,
        )
    }

def get_stock_universe_info() -> Dict[str, Any]:
    """Get information about available stock universes."""
    base_settings = load_base_settings()
    
    info = {
        "eodhd_us": {
            "name": "EODHD US Market",
            "total_securities": 57439,
            "description": "All US securities from EODHD database",
            "data_sources": ["EODHD API"],
            "requires_api_key": True,
            "coverage": "Comprehensive US market including ETFs, ADRs, etc."
        },
        "free_demo": {
            "name": "Free Demo (3 Stocks)",
            "total_securities": 3,
            "description": "Demo set with Apple, Microsoft, Coca-Cola",
            "data_sources": ["SEC Edgar", "Nasdaq Trader", "Stooq"],
            "requires_api_key": False,
            "coverage": "Educational demo with well-known large caps"
        },
        "sec_public": {
            "name": "SEC Public Filers",
            "total_securities": "Variable",
            "description": "Companies with SEC public filings",
            "data_sources": ["SEC Edgar", "Local price files"],
            "requires_api_key": False,
            "coverage": "US public companies, limited by price data availability"
        }
    }
    
    return info

if __name__ == "__main__":
    # Test configuration
    configs = get_default_configs()
    for name, config in configs.items():
        print(f"{name}: max_stocks={config.max_stocks}, weights=Q:{config.quality_weight} V:{config.value_weight} G:{config.growth_weight} S:{config.safety_weight} M:{config.momentum_weight}")
