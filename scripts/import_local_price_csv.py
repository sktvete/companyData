from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_sorter.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bronze-date", required=True)
    parser.add_argument("--csv-path", required=True)
    parser.add_argument("--name", default=None, help="Optional output file name")
    parser.add_argument("--mapping-path", default=None, help="Optional JSON mapping file")
    parser.add_argument("--price-reality", default="real_imported", choices=["real_imported", "synthetic_demo", "unknown"])
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--adjustment-method", default="unknown", help="e.g. adjusted_close_present, unadjusted, unknown")
    args = parser.parse_args()

    settings = load_settings()
    source_path = Path(args.csv_path).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    destination_name = args.name or source_path.name
    destination = settings.data_dir / "bronze" / "provider=local_csv" / "dataset=prices_daily" / f"date={args.bronze_date}" / destination_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)
    manifest = {
        "price_reality": args.price_reality,
        "currency": args.currency,
        "adjustment_method": args.adjustment_method,
        "required_fields": ["ticker", "date", "close"],
        "column_map": None,
    }
    if args.mapping_path:
        mapping_path = Path(args.mapping_path).resolve()
        manifest["column_map"] = json.loads(mapping_path.read_text(encoding="utf-8"))
    destination.with_suffix(destination.suffix + ".meta.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
