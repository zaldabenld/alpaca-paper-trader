from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from day_tape_strategy_sweep import (
    ZERO,
    candidate_payload,
    candidates_for_mode,
    compact_scan_events,
    decimal_payload,
    default_tape_dir,
    events_for_bucket,
    load_tape,
    matching_fold_profile,
    metric_line,
    metrics_payload,
    selected_sweep_files,
    simulate_candidate,
    tape_file_date,
)


def find_bucket(profiles: dict[str, Any], bucket_contains: str) -> tuple[str, Any]:
    needle = bucket_contains.lower()
    matches = [
        (key, profile)
        for key, profile in profiles.items()
        if not needle or needle in profile.label.lower()
    ]
    if not matches:
        labels = "\n".join(f"- {profile.label}" for profile in profiles.values())
        raise SystemExit(f"No bucket matched {bucket_contains!r}. Available:\n{labels}")
    if len(matches) > 1 and bucket_contains:
        labels = "\n".join(f"- {profile.label}" for _key, profile in matches)
        raise SystemExit(f"Bucket filter matched multiple buckets:\n{labels}")
    return matches[0]


def find_candidate(candidates: list[Any], name: str) -> Any:
    wanted = name.lower()
    matches = [candidate for candidate in candidates if candidate.name.lower() == wanted]
    if not matches:
        names = "\n".join(f"- {candidate.name}" for candidate in candidates)
        raise SystemExit(f"No candidate matched {name!r}. Available:\n{names}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit trade-level diagnostics for one day-tape candidate.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--end-date", default="")
    parser.add_argument("--bucket-contains", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--candidate-mode", choices=("standard", "broad", "research", "impulse", "riskbox", "pricebox", "pricebox_session", "conservative_bridge"), default="broad")
    parser.add_argument("--exit-mode", choices=("fixed", "adaptive", "all"), default="adaptive")
    parser.add_argument("--price-source", choices=("bars", "trades"), default="trades")
    parser.add_argument("--scan-interval-seconds", type=int, default=60)
    parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("5"))
    parser.add_argument("--no-liquidate-at-end", action="store_true")
    parser.add_argument("--liquidate-on-close", action="store_true")
    parser.add_argument("--max-hold-minutes", type=int, default=0)
    parser.add_argument("--min-stop-hold-minutes", type=int, default=0)
    parser.add_argument("--entry-open-guard-minutes", type=int, default=0)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    files = selected_sweep_files(args.path, args.days, str(args.end_date or ""))
    report: dict[str, Any] = {
        "files": [path.name for path in files],
        "settings": {
            "bucket_contains": args.bucket_contains,
            "candidate": args.candidate,
            "candidate_mode": args.candidate_mode,
            "exit_mode": args.exit_mode,
            "price_source": args.price_source,
            "scan_interval_seconds": max(0, args.scan_interval_seconds),
            "slippage_bps": decimal_payload(max(ZERO, args.slippage_bps)),
            "liquidate_at_end": not args.no_liquidate_at_end,
            "liquidate_on_close": bool(args.liquidate_on_close),
            "max_hold_minutes": max(0, args.max_hold_minutes),
            "min_stop_hold_minutes": max(0, args.min_stop_hold_minutes),
            "entry_open_guard_minutes": max(0, args.entry_open_guard_minutes),
        },
        "folds": [],
    }

    print("Day Tape Trade Diagnostics")
    print(f"Candidate: {args.candidate}")
    print(f"Price source: {args.price_source}; slippage={max(ZERO, args.slippage_bps)} bps")
    print()

    combined_events, combined_profiles = load_tape(files, price_source=args.price_source)
    combined_events, _combined_dropped = compact_scan_events(combined_events, max(0, args.scan_interval_seconds))
    combined_bucket_key, combined_profile = find_bucket(combined_profiles, args.bucket_contains)
    combined_bucket_events = events_for_bucket(combined_events, combined_bucket_key)
    combined_candidates = candidates_for_mode(
        combined_profile.config,
        args.candidate_mode,
        combined_bucket_events,
        args.exit_mode,
    )
    candidate = find_candidate(combined_candidates, args.candidate)
    bucket_keys = {combined_bucket_key, *combined_profile.source_keys}

    for path in files:
        events, profiles = load_tape([path], price_source=args.price_source)
        events, dropped = compact_scan_events(events, max(0, args.scan_interval_seconds))
        bucket_key, profile = matching_fold_profile(profiles, bucket_keys)
        if profile is None or bucket_key is None:
            labels = "\n".join(f"- {profile.label}" for profile in profiles.values())
            raise SystemExit(f"No fold bucket matched stitched source keys for {path.name}. Available:\n{labels}")
        bucket_events = events_for_bucket(events, bucket_key)
        metrics = simulate_candidate(
            bucket_events,
            profile,
            candidate,
            max(ZERO, args.slippage_bps),
            liquidate_at_end=not args.no_liquidate_at_end,
            max_hold_minutes=max(0, args.max_hold_minutes),
            liquidate_on_close=bool(args.liquidate_on_close),
            collect_trades=True,
            min_stop_hold_minutes=max(0, args.min_stop_hold_minutes),
            entry_open_guard_minutes=max(0, args.entry_open_guard_minutes),
        )
        payload = metrics_payload(metrics)
        fold = {
            "file": path.name,
            "date": tape_file_date(path),
            "bucket": profile.label,
            "candidate": candidate_payload(candidate),
            "dropped_scans": dropped,
            "metrics": payload,
        }
        report["folds"].append(fold)
        print(f"{path.name}: {metric_line(metrics)}")
        for trade in payload.get("trades", []):
            if trade.get("event") == "entry":
                print(
                    f"  BUY  {trade['symbol']} qty={trade['qty']} price={trade['price']} "
                    f"score={trade['score']} time={trade['time']}"
                )
            else:
                print(
                    f"  SELL {trade['symbol']} qty={trade['qty']} price={trade['exit_price']} "
                    f"pl={trade['realized_pl']} reason={trade['reason']} held={trade['held_minutes']}m"
                )
        print()

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON diagnostics: {args.json_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
