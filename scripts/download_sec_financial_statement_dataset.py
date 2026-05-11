from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings
from equity_sorter.providers.sec_edgar.financial_statement_data_sets import download_dataset, list_zip_members


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--quarter", type=int, required=True)
    args = parser.parse_args()

    settings = load_settings()
    destination = settings.data_dir / "bronze" / "provider=sec_edgar" / "dataset=financial_statement_data_sets" / f"year={args.year}" / f"quarter={args.quarter}" / f"{args.year}q{args.quarter}.zip"
    zip_path = download_dataset(args.year, args.quarter, destination, settings.sec_user_agent)
    members = list_zip_members(zip_path)
    print(zip_path)
    print("members:")
    for member in members[:20]:
        print(member)
