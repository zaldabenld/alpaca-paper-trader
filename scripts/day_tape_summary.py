from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def event_symbols(event: dict[str, Any]) -> set[str]:
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return set()
    symbol = str(payload.get("symbol") or "").strip().upper()
    if symbol:
        return {symbol}
    kind = str(event.get("kind") or "")
    rows = []
    if kind == "strategy_scan":
        rows = payload.get("strategy") or []
    elif kind == "top_volume_snapshot":
        rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("symbol") or "").strip().upper()
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def summarize_file(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    symbols: set[str] = set()
    first_time = ""
    last_time = ""
    lines = 0
    parse_errors = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            lines += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            kind = str(event.get("kind") or "")
            counts[kind] += 1
            event_time = str(event.get("time") or "")
            first_time = first_time or event_time
            last_time = event_time or last_time
            symbols.update(event_symbols(event))
    return {
        "name": path.name,
        "mb": path.stat().st_size / (1024 * 1024),
        "lines": lines,
        "parse_errors": parse_errors,
        "first_time": first_time,
        "last_time": last_time,
        "symbols": len(symbols),
        "counts": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Alpaca Paper Trader day-tape files.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Directory containing tape-YYYYMMDD.jsonl files.")
    parser.add_argument("--days", type=int, default=14, help="Maximum number of most-recent tape files to summarize.")
    args = parser.parse_args()

    tape_dir = args.path
    files = sorted(tape_dir.glob("tape-*.jsonl"), key=lambda item: item.name)[-max(1, args.days) :]
    if not files:
        print(f"No day-tape files found in {tape_dir}")
        return 0

    summaries = [summarize_file(path) for path in files]
    total_mb = sum(item["mb"] for item in summaries)
    total_lines = sum(item["lines"] for item in summaries)
    print(f"Day tape directory: {tape_dir}")
    print(f"Files: {len(summaries)}  Total: {total_mb:.2f} MB  Lines: {total_lines:,}")
    print()
    print(
        f"{'File':<20} {'MB':>8} {'Lines':>10} {'Bars':>9} {'Trades':>9} "
        f"{'Quotes':>9} {'Scans':>8} {'Orders':>8} {'Symbols':>8} {'Errors':>8}"
    )
    print("-" * 108)
    for item in summaries:
        counts = item["counts"]
        print(
            f"{item['name']:<20} "
            f"{item['mb']:>8.2f} "
            f"{item['lines']:>10,} "
            f"{counts.get('market_bar', 0):>9,} "
            f"{counts.get('market_trade', 0):>9,} "
            f"{counts.get('market_quote', 0):>9,} "
            f"{counts.get('strategy_scan', 0):>8,} "
            f"{counts.get('order_intent', 0):>8,} "
            f"{item['symbols']:>8,} "
            f"{item['parse_errors']:>8,}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
