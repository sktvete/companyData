from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    project_root: Path = _default_root()
    data_dir: Path = Path(os.getenv("EQUITY_SORTER_DATA_DIR", _default_root() / "data"))
    output_dir: Path = Path(os.getenv("EQUITY_SORTER_OUTPUT_DIR", _default_root() / "outputs"))
    eodhd_api_key: str | None = os.getenv("EODHD_API_KEY")
    stooq_api_key: str | None = os.getenv("STOOQ_API_KEY")
    default_country: str = "US"
    default_exchange: str = "US"
    provider_name: str = "eodhd"
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "equity-sorter research@example.com")
    free_us_sample_tickers: tuple[str, ...] = tuple(
        ticker.strip().upper() for ticker in os.getenv("EQUITY_SORTER_FREE_US_TICKERS", "AAPL,MSFT,KO").split(",") if ticker.strip()
    )
    pilot_us_limit: int = int(os.getenv("EQUITY_SORTER_PILOT_US_LIMIT", "1000"))
    timing_quarterly_lag_days: int = int(os.getenv("EQUITY_SORTER_Q_LAG_DAYS", "45"))
    timing_annual_lag_days: int = int(os.getenv("EQUITY_SORTER_Y_LAG_DAYS", "90"))


def load_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return settings
