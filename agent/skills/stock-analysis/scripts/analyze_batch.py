"""Batch stock analysis CLI.

Analyzes multiple tickers from a file or command-line list.
Outputs JSONL (one JSON object per line) for streaming-friendly consumption.

Usage:
    python -m scripts.analyze_batch --symbols AAPL.US NVDA.US TSLA.US --output results.jsonl
    python -m scripts.analyze_batch --symbols-file symbols.txt --output results.jsonl
    python -m scripts.analyze_batch --symbols-file symbols.txt --pretty

symbols.txt format (one ticker per line):
    AAPL.US
    NVDA.US
    TSLA.US
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import TextIO

from .analyze_stock import analyze_single
from .eodhd_client import EodhdClient, normalize_ticker


def load_symbols_file(path: str) -> list[str]:
    """Load tickers from a text file, one per line."""
    p = Path(path)
    if not p.exists():
        print(f"ERROR: Symbols file not found: {path}", file=sys.stderr)
        sys.exit(1)
    symbols = []
    for line in p.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            symbols.append(normalize_ticker(line))
    if not symbols:
        print(f"ERROR: No symbols found in {path}", file=sys.stderr)
        sys.exit(1)
    return symbols


def analyze_batch(
    symbols: list[str],
    client: EodhdClient,
    output_stream: TextIO | None = None,
    pretty: bool = False,
) -> list[dict]:
    """Analyze a batch of tickers. Returns list of results.

    If output_stream is provided, writes JSONL as each result completes
    (streaming output).
    """
    results = []
    total = len(symbols)

    for i, ticker in enumerate(symbols, 1):
        print(f"[{i}/{total}] Analyzing {ticker}...", file=sys.stderr)
        start = time.time()

        try:
            result = analyze_single(ticker, client)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            result = {
                "ticker": ticker.split(".")[0],
                "exchange": ticker.split(".")[-1] if "." in ticker else "US",
                "error": str(e),
            }

        elapsed = time.time() - start
        rec = result.get("recommendation", "error")
        score = result.get("overall_score", "?")
        print(f"  → {rec} (score: {score}) [{elapsed:.1f}s]", file=sys.stderr)

        results.append(result)

        if output_stream:
            line = json.dumps(result, default=str)
            output_stream.write(line + "\n")
            output_stream.flush()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch stock analysis")
    parser.add_argument("--symbols", nargs="+", help="Tickers to analyze (space-separated)")
    parser.add_argument("--symbols-file", type=str, help="Path to file with tickers (one per line)")
    parser.add_argument("--output", "-o", type=str, help="Output file path (.jsonl)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print each JSON result to stdout")
    parser.add_argument("--cache-ttl", type=int, default=21600, help="Cache TTL in seconds (default: 6h)")
    args = parser.parse_args()

    if not args.symbols and not args.symbols_file:
        parser.error("Provide --symbols or --symbols-file")

    symbols = []
    if args.symbols_file:
        symbols = load_symbols_file(args.symbols_file)
    if args.symbols:
        symbols.extend(normalize_ticker(s) for s in args.symbols)

    symbols = list(dict.fromkeys(symbols))

    client = EodhdClient(cache_ttl=args.cache_ttl)

    output_stream: TextIO | None = None
    output_path = None
    if args.output:
        output_path = Path(args.output)
        output_stream = open(output_path, "w", encoding="utf-8")

    try:
        results = analyze_batch(symbols, client, output_stream, args.pretty)
    finally:
        if output_stream and output_stream is not sys.stdout:
            output_stream.close()

    if args.pretty:
        for r in results:
            print(json.dumps(r, indent=2, default=str))
            print()
    elif not args.output:
        for r in results:
            print(json.dumps(r, default=str))

    # Summary
    total = len(results)
    buys = sum(1 for r in results if r.get("recommendation") == "buy")
    watchlist = sum(1 for r in results if r.get("recommendation") == "watchlist")
    no_buys = sum(1 for r in results if r.get("recommendation") == "no_buy")
    errors = sum(1 for r in results if "error" in r)

    print(f"\n--- Batch Summary ---", file=sys.stderr)
    print(f"Total: {total} | Buy: {buys} | Watchlist: {watchlist} | No Buy: {no_buys} | Errors: {errors}", file=sys.stderr)

    if output_path:
        print(f"Results written to: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
