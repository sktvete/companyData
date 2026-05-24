"""Validate stock analysis JSON output against the schema.

Usage:
    python -m scripts.validate_output --file output.json
    python -m scripts.validate_output --file batch_output.jsonl
    echo '{"ticker":"AAPL",...}' | python -m scripts.validate_output --stdin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "output-schema.json"


def load_schema() -> dict:
    if not SCHEMA_PATH.exists():
        print(f"ERROR: Schema file not found at {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_with_jsonschema(data: dict, schema: dict) -> list[str]:
    """Validate using jsonschema library. Returns list of error messages."""
    if jsonschema is None:
        return ["jsonschema library not installed — install with: pip install jsonschema"]
    errors = []
    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"  {path}: {error.message}")
    return errors


def validate_basic(data: dict, schema: dict) -> list[str]:
    """Basic structural validation without jsonschema library."""
    errors = []
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            errors.append(f"  Missing required field: {field}")

    rec = data.get("recommendation")
    if rec and rec not in ("buy", "watchlist", "no_buy"):
        errors.append(f"  Invalid recommendation: {rec}")

    conf = data.get("confidence")
    if conf and conf not in ("low", "medium", "high"):
        errors.append(f"  Invalid confidence: {conf}")

    overall = data.get("overall_score")
    if overall is not None and (not isinstance(overall, int) or overall < 0 or overall > 100):
        errors.append(f"  overall_score must be integer 0-100, got: {overall}")

    scores = data.get("scores", {})
    score_fields = [
        "quality_score", "growth_score", "valuation_score",
        "balance_sheet_score", "earnings_quality_score",
        "catalyst_score", "sentiment_score", "technical_score",
    ]
    for sf in score_fields:
        val = scores.get(sf)
        if val is not None and (not isinstance(val, int) or val < 0 or val > 100):
            errors.append(f"  scores.{sf} must be integer 0-100, got: {val}")

    rrfs = scores.get("risk_red_flag_score")
    if rrfs is not None and (not isinstance(rrfs, int) or rrfs < -40 or rrfs > 0):
        errors.append(f"  scores.risk_red_flag_score must be integer -40 to 0, got: {rrfs}")

    ds = data.get("decision_summary", {})
    for f in ("bull_case", "bear_case", "what_would_change_the_decision"):
        val = ds.get(f)
        if val is not None and (not isinstance(val, list) or not all(isinstance(x, str) for x in val)):
            errors.append(f"  decision_summary.{f} must be array of strings")

    red_flags = data.get("red_flags", [])
    if not isinstance(red_flags, list):
        errors.append("  red_flags must be an array")
    else:
        for i, rf in enumerate(red_flags):
            if not isinstance(rf, dict):
                errors.append(f"  red_flags[{i}] must be an object")
            elif not all(k in rf for k in ("type", "severity", "description")):
                errors.append(f"  red_flags[{i}] missing required fields (type, severity, description)")

    return errors


def validate_one(data: dict, schema: dict, label: str = "") -> bool:
    """Validate a single output object. Returns True if valid."""
    prefix = f"[{label}] " if label else ""
    ticker = data.get("ticker", "unknown")

    if jsonschema is not None:
        errors = validate_with_jsonschema(data, schema)
    else:
        errors = validate_basic(data, schema)

    if errors:
        print(f"{prefix}FAIL ({ticker}):")
        for e in errors:
            print(e)
        return False
    else:
        print(f"{prefix}PASS ({ticker})")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate stock analysis output against schema")
    parser.add_argument("--file", "-f", type=str, help="Path to JSON or JSONL file")
    parser.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
    args = parser.parse_args()

    schema = load_schema()
    total = 0
    passed = 0

    if args.stdin:
        data = json.loads(sys.stdin.read())
        total = 1
        if validate_one(data, schema):
            passed = 1
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"ERROR: File not found: {path}", file=sys.stderr)
            sys.exit(1)

        if path.suffix == ".jsonl":
            for i, line in enumerate(path.read_text(encoding="utf-8").strip().splitlines()):
                line = line.strip()
                if not line:
                    continue
                total += 1
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[line {i+1}] FAIL: Invalid JSON — {e}")
                    continue
                if validate_one(data, schema, label=f"line {i+1}"):
                    passed += 1
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for i, item in enumerate(data):
                    total += 1
                    if validate_one(item, schema, label=str(i)):
                        passed += 1
            else:
                total = 1
                if validate_one(data, schema):
                    passed = 1
    else:
        parser.print_help()
        sys.exit(1)

    print(f"\n{passed}/{total} passed validation")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
