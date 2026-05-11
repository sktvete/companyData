from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.pipeline import build_us_sample_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of-date", required=True)
    args = parser.parse_args()

    settings = load_settings()
    outputs = build_us_sample_snapshot(settings, args.as_of_date, snapshot_name="us_garp")
    print(outputs["csv"])


if __name__ == "__main__":
    main()
