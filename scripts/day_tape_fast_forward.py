from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def selected_files(path: Path, days: int) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)[-max(1, days) :]


def parse_event_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def iter_tape_events(files: Iterable[Path], max_events: int = 0) -> Iterable[tuple[Path, int, dict[str, Any]]]:
    emitted = 0
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {
                        "kind": "parse_error",
                        "payload": {"file": path.name, "line": line_number},
                    }
                yield path, line_number, event
                emitted += 1
                if max_events and emitted >= max_events:
                    return


def collect_symbols(kind: str, payload: dict[str, Any]) -> set[str]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if symbol:
        return {symbol}
    symbols: set[str] = set()
    if kind == "strategy_scan":
        rows = payload.get("strategy") or []
        if isinstance(rows, list):
            symbols.update(
                str(row.get("symbol") or "").strip().upper()
                for row in rows
                if isinstance(row, dict) and row.get("symbol")
            )
    if kind == "top_volume_snapshot":
        rows = payload.get("rows") or []
        if isinstance(rows, list):
            symbols.update(
                str(row.get("symbol") or "").strip().upper()
                for row in rows
                if isinstance(row, dict) and row.get("symbol")
            )
    return {item for item in symbols if item}


def fast_forward(files: list[Path], speed: float, max_sleep: float, max_events: int, verbose: bool) -> int:
    counts: Counter[str] = Counter()
    order_statuses: Counter[str] = Counter()
    symbols: set[str] = set()
    first_time: datetime | None = None
    last_time: datetime | None = None
    parse_errors = 0
    start = time.perf_counter()

    for path, line_number, event in iter_tape_events(files, max_events=max_events):
        kind = str(event.get("kind") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_time = parse_event_time(event.get("time"))
        if event_time is not None:
            first_time = first_time or event_time
            if speed > 0 and last_time is not None and event_time > last_time:
                delay = min((event_time - last_time).total_seconds() / speed, max_sleep)
                if delay > 0:
                    time.sleep(delay)
            last_time = event_time

        counts[kind] += 1
        symbols.update(collect_symbols(kind, payload))
        if kind == "order_intent":
            order_statuses[str(payload.get("status") or "unknown")] += 1
        if kind == "parse_error":
            parse_errors += 1
        if verbose and kind in {"order_intent", "market_stream_error"}:
            print(f"{path.name}:{line_number} {kind}: {payload}")

    elapsed = max(time.perf_counter() - start, 0.000001)
    total = sum(counts.values())
    print(f"Files: {len(files)}")
    print(f"Events: {total:,} in {elapsed:.2f}s ({total / elapsed:,.0f} events/s)")
    if first_time and last_time:
        tape_seconds = max((last_time - first_time).total_seconds(), 0)
        print(f"Tape span: {first_time.isoformat()} -> {last_time.isoformat()} ({tape_seconds / 3600:.2f} hours)")
    print()
    print("Market data")
    print(f"  bars:     {counts.get('market_bar', 0):,}")
    print(f"  trades:   {counts.get('market_trade', 0):,}")
    print(f"  quotes:   {counts.get('market_quote', 0):,}")
    print(f"  statuses: {counts.get('market_status', 0):,}")
    print()
    print("App decisions")
    print(f"  strategy scans: {counts.get('strategy_scan', 0):,}")
    print(f"  order intents:  {counts.get('order_intent', 0):,}")
    if order_statuses:
        print("  order statuses: " + ", ".join(f"{key}={value:,}" for key, value in sorted(order_statuses.items())))
    print()
    print("Other app events")
    print(f"  top-volume snapshots: {counts.get('top_volume_snapshot', 0):,}")
    print(f"  lookups:              {counts.get('lookup_snapshot', 0):,}")
    print(f"  backfills:            {counts.get('market_backfill', 0):,}")
    print(f"  stream subscriptions: {counts.get('market_subscription', 0):,}")
    print(f"  stream errors:        {counts.get('market_stream_error', 0):,}")
    print(f"  parse errors:         {parse_errors:,}")
    print()
    print(f"Unique symbols seen: {len(symbols):,}")
    print("Mode: event-flow fast-forward. Use scripts/day_tape_backtest.py for app-engine replay decisions.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast-forward Alpaca Paper Trader day-tape files offline.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=7, help="Most-recent tape files to replay when --path is a directory.")
    parser.add_argument("--speed", type=float, default=0, help="0 means no waiting; 60 means one minute of tape per second.")
    parser.add_argument("--max-sleep", type=float, default=1.0, help="Cap per-event sleep when --speed is above 0.")
    parser.add_argument("--max-events", type=int, default=0, help="Stop after this many events. 0 means no limit.")
    parser.add_argument("--verbose", action="store_true", help="Print order intents and stream errors as they are replayed.")
    args = parser.parse_args()

    files = selected_files(args.path, args.days)
    if not files:
        print(f"No day-tape files found in {args.path}")
        return 0
    return fast_forward(files, max(0, args.speed), max(0, args.max_sleep), max(0, args.max_events), args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
