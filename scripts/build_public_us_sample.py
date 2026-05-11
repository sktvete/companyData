from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.free_pipeline import build_free_us_quality_report, normalize_free_us_reference, normalize_free_us_security_payloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", required=True)
    args = parser.parse_args()

    settings = load_settings()
    normalize_free_us_reference(settings, args.bronze_date)
    normalize_free_us_security_payloads(settings, args.bronze_date)
    quality_path = build_free_us_quality_report(settings, args.bronze_date)
    print(quality_path)


if __name__ == "__main__":
    main()
