from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def selected_files(path: Path, days: int) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)[-max(1, days) :]


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def iter_events(files: Iterable[Path]) -> Iterable[tuple[Path, int, dict[str, Any] | None]]:
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    yield path, line_number, json.loads(line)
                except json.JSONDecodeError:
                    yield path, line_number, None


def payload_dict(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def normalize_hold(action: Any) -> str:
    text = re.sub(r"\s+", " ", str(action or "").strip())
    if not text:
        return "missing decision"
    match = re.match(r"(?i)^hold\s*\((.*)\)$", text)
    if match:
        text = match.group(1).strip()
    text = re.sub(r"(?i)^hold\s*[:\-]?\s*", "", text).strip()
    return text or "hold"


def scan_bucket(payload: dict[str, Any]) -> str:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    profile = str(config.get("profile") or "unknown")
    top_volume = str(config.get("use_top_volume_symbols"))
    dry_run = str(config.get("dry_run"))
    return f"profile={profile}, top_volume={top_volume}, dry_run={dry_run}"


def scan_source_sizing(payload: dict[str, Any]) -> str:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    max_trade = str(config.get("max_trade_notional") or "?")
    max_trade_percent = str(config.get("max_trade_percent") or "?")
    max_positions = str(config.get("max_open_positions") or "?")
    exposure = str(config.get("max_total_exposure_percent") or "?")
    return (
        f"max_trade={max_trade}, max_trade_percent={max_trade_percent}, "
        f"max_positions={max_positions}, exposure={exposure}"
    )


def is_market_open(payload: dict[str, Any]) -> bool:
    clock = payload.get("market_clock") if isinstance(payload.get("market_clock"), dict) else {}
    return bool(clock.get("is_open"))


def event_symbols(kind: str, payload: dict[str, Any]) -> set[str]:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if symbol:
        return {symbol}
    rows_key = "strategy" if kind == "strategy_scan" else "rows"
    rows = as_list(payload.get(rows_key))
    return {
        str(row.get("symbol") or "").strip().upper()
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }


def top_items(counter: Counter[str], limit: int = 5) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{name} ({count})" for name, count in counter.most_common(limit))


def latest_top_volume_summary(rows: list[Any]) -> tuple[int, int, int, list[str]]:
    symbols: list[str] = []
    priced = 0
    sub_five = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            symbols.append(symbol)
        price = parse_float(row.get("last_price_raw") if row.get("last_price_raw") not in (None, "") else row.get("last_price"))
        if price is None:
            continue
        priced += 1
        if price < 5:
            sub_five += 1
    return len(rows), priced, sub_five, symbols


def review(files: list[Path]) -> int:
    counts: Counter[str] = Counter()
    parse_errors = 0
    first_time: datetime | None = None
    last_time: datetime | None = None
    symbols: set[str] = set()
    order_statuses: Counter[str] = Counter()
    order_roles: Counter[str] = Counter()
    stream_errors: Counter[str] = Counter()
    top_volume_errors: Counter[str] = Counter()
    latest_top_volume_rows: list[Any] = []
    latest_top_volume_source = ""
    latest_top_volume_time = ""

    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "scans": 0,
            "open_scans": 0,
            "trading_open_scans": 0,
            "flat_trading_open_scans": 0,
            "entries_allowed": 0,
            "entry_guard": Counter(),
            "holds": Counter(),
            "symbols": Counter(),
            "candidate_rows": 0,
            "source_sizing": Counter(),
            "latest": {},
            "latest_holds": Counter(),
        }
    )

    for path, _line_number, event in iter_events(files):
        if event is None:
            parse_errors += 1
            continue
        kind = str(event.get("kind") or "")
        payload = payload_dict(event)
        counts[kind] += 1
        symbols.update(event_symbols(kind, payload))
        event_time = parse_time(event.get("time"))
        if event_time:
            first_time = first_time or event_time
            last_time = event_time

        if kind == "order_intent":
            order_statuses[str(payload.get("status") or "unknown")] += 1
            order_roles[str(payload.get("role") or "unknown")] += 1
        elif kind == "market_stream_error":
            detail = str(payload.get("detail") or payload.get("error") or "stream error").strip()
            stream_errors[detail[:120]] += 1
        elif kind == "top_volume_error":
            detail = str(payload.get("error") or "top-volume error").strip()
            top_volume_errors[detail[:120]] += 1
        elif kind == "top_volume_snapshot":
            latest_top_volume_rows = as_list(payload.get("rows"))
            latest_top_volume_source = str(payload.get("source") or "")
            latest_top_volume_time = str(event.get("time") or "")
        elif kind == "strategy_scan":
            key = scan_bucket(payload)
            bucket = buckets[key]
            bucket["scans"] += 1
            bucket["source_sizing"][scan_source_sizing(payload)] += 1
            market_open = is_market_open(payload)
            trading_enabled = bool(payload.get("trading_enabled"))
            entries_allowed = bool(payload.get("entries_allowed"))
            positions = as_list(payload.get("positions"))
            open_orders = as_list(payload.get("open_orders"))
            rows = as_list(payload.get("strategy"))
            if market_open:
                bucket["open_scans"] += 1
            if market_open and trading_enabled:
                bucket["trading_open_scans"] += 1
            if market_open and trading_enabled and not positions and not open_orders:
                bucket["flat_trading_open_scans"] += 1
            if entries_allowed:
                bucket["entries_allowed"] += 1
            else:
                detail = str(payload.get("entry_guard_detail") or "entry guard").strip() or "entry guard"
                bucket["entry_guard"][detail[:120]] += 1

            latest_holds: Counter[str] = Counter()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                if symbol:
                    bucket["symbols"][symbol] += 1
                action = str(row.get("last_action") or "")
                if action and not action.lower().startswith("hold"):
                    bucket["candidate_rows"] += 1
                reason = normalize_hold(action)
                bucket["holds"][reason] += 1
                latest_holds[reason] += 1
            bucket["latest"] = {
                "market_open": market_open,
                "trading_enabled": trading_enabled,
                "entries_allowed": entries_allowed,
                "positions": len(positions),
                "open_orders": len(open_orders),
                "rows": len(rows),
            }
            bucket["latest_holds"] = latest_holds

    total_mb = sum(path.stat().st_size for path in files) / (1024 * 1024)
    total_events = sum(counts.values())
    latest_count, priced_count, sub_five_count, latest_symbols = latest_top_volume_summary(latest_top_volume_rows)

    findings: list[str] = []
    if parse_errors:
        findings.append(f"WARN: {parse_errors:,} JSON parse errors were found.")
    if counts.get("strategy_scan", 0) == 0:
        findings.append("WARN: no strategy scans were recorded, so trading behavior cannot be reviewed.")
    if counts.get("market_bar", 0) == 0:
        findings.append("WARN: no market bars were recorded.")
    if counts.get("top_volume_snapshot", 0) == 0:
        findings.append("WARN: no top-volume snapshots were recorded.")
    if latest_count and sub_five_count >= max(5, latest_count // 4):
        findings.append(
            f"WARN: latest top-volume snapshot still contains {sub_five_count}/{latest_count} symbols priced below $5."
        )
    if stream_errors:
        findings.append(f"WARN: stream errors recorded: {top_items(stream_errors, 3)}.")
    if top_volume_errors:
        findings.append(f"WARN: top-volume errors recorded: {top_items(top_volume_errors, 3)}.")

    for key, bucket in buckets.items():
        trading_open = int(bucket["trading_open_scans"])
        flat_open = int(bucket["flat_trading_open_scans"])
        candidate_rows = int(bucket["candidate_rows"])
        if trading_open and flat_open == trading_open and candidate_rows == 0:
            findings.append(
                f"WARN: {key} was flat for every open-market trading scan and produced no candidate rows."
            )

    if not findings:
        findings.append("OK: tape has strategy scans, market data, no parse errors, and no obvious stream/top-volume faults.")

    print("Day Tape Review")
    print(f"Files: {len(files)}  Size: {total_mb:.2f} MB  Events: {total_events:,}  Unique symbols: {len(symbols):,}")
    if first_time and last_time:
        span_hours = max((last_time - first_time).total_seconds(), 0) / 3600
        print(f"Span: {first_time.isoformat()} -> {last_time.isoformat()} ({span_hours:.2f} hours)")
    print()

    print("Event Counts")
    for kind, count in counts.most_common():
        print(f"  {kind}: {count:,}")
    print(f"  parse_errors: {parse_errors:,}")
    print()

    print("Order Intents")
    print(f"  total: {counts.get('order_intent', 0):,}")
    print(f"  statuses: {top_items(order_statuses)}")
    print(f"  roles: {top_items(order_roles)}")
    print()

    print("Top-Volume Snapshot")
    if latest_count:
        print(f"  latest_source: {latest_top_volume_source or 'unknown'}")
        print(f"  latest_time: {latest_top_volume_time or 'unknown'}")
        print(f"  rows: {latest_count}  priced_rows: {priced_count}  below_$5: {sub_five_count}")
        print(f"  first_symbols: {', '.join(latest_symbols[:15])}")
    else:
        print("  none")
    print()

    print("Strategy Source Buckets")
    print("  sizing/capacity is shown as source metadata, not strategy identity")
    for key, bucket in sorted(buckets.items()):
        latest = bucket["latest"]
        print(f"  {key}")
        print(
            "    "
            f"scans={bucket['scans']:,} open_scans={bucket['open_scans']:,} "
            f"trading_open_scans={bucket['trading_open_scans']:,} "
            f"flat_trading_open_scans={bucket['flat_trading_open_scans']:,} "
            f"candidate_rows={bucket['candidate_rows']:,}"
        )
        if latest:
            print(
                "    "
                f"latest: market_open={latest['market_open']} trading={latest['trading_enabled']} "
                f"entries_allowed={latest['entries_allowed']} positions={latest['positions']} "
                f"open_orders={latest['open_orders']} rows={latest['rows']}"
            )
        print(f"    latest_holds: {top_items(bucket['latest_holds'])}")
        print(f"    all_day_holds: {top_items(bucket['holds'])}")
        print(f"    active_symbols: {top_items(bucket['symbols'], 10)}")
        print(f"    source_sizing: {top_items(bucket['source_sizing'], 5)}")
    print()

    print("Findings")
    for finding in findings:
        print(f"  {finding}")
    print()

    print("Follow-Ups")
    follow_up_count = 0
    if any("flat for every open-market" in item for item in findings):
        print("  Review the strategy gates for the flat bucket and compare against order intent timing.")
        follow_up_count += 1
    if latest_count and sub_five_count >= max(5, latest_count // 4):
        print("  Investigate top-volume universe selection before trusting candidate quality.")
        follow_up_count += 1
    if counts.get("order_intent", 0) == 0 and counts.get("strategy_scan", 0) > 0:
        print("  Treat the day as a no-entry strategy day and inspect dominant hold reasons.")
        follow_up_count += 1
    if follow_up_count == 0:
        print("  Use these findings to choose the next strategy or data-quality fix; no trades are simulated here.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Review Alpaca Paper Trader day-tape quality and strategy behavior.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=1, help="Most-recent tape files to review when --path is a directory.")
    args = parser.parse_args()

    files = selected_files(args.path, args.days)
    if not files:
        print(f"No day-tape files found in {args.path}")
        return 0
    return review(files)


if __name__ == "__main__":
    raise SystemExit(main())
