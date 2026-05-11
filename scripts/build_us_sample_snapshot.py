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
    parser.add_argument("--snapshot-name", default="us_sample")
    args = parser.parse_args()

    settings = load_settings()
    paths = build_us_sample_snapshot(settings, args.as_of_date, snapshot_name=args.snapshot_name)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
