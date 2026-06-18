from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from day_tape_strategy_sweep import default_tape_dir, selected_sweep_files, tape_file_date


COMPARE_KEYS = [
    "buy_rsi_min",
    "buy_rsi_max",
    "min_entry_score",
    "min_momentum_percent",
    "min_recent_momentum_percent",
    "min_long_momentum_percent",
    "min_session_change_percent",
    "min_vwap_distance_percent",
    "max_vwap_distance_percent",
    "max_session_pullback_percent",
    "max_recent_pullback_percent",
    "late_momentum_floor_percent",
    "min_smi",
    "volume_multiplier",
    "take_profit_percent",
    "stop_loss_percent",
    "profit_trail_start_percent",
    "profit_trail_drop_percent",
    "exit_close_guard_minutes",
]


def dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def same_value(current: Any, expected: Any) -> bool:
    current_dec = dec(current)
    expected_dec = dec(expected)
    if current_dec is not None and expected_dec is not None:
        return current_dec.quantize(Decimal("0.0001")) == expected_dec.quantize(Decimal("0.0001"))
    return str(current) == str(expected)


def format_value(value: Any) -> str:
    if value is None:
        return "missing"
    return str(value)


def load_patch(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    top = report.get("top") or []
    if not top:
        raise SystemExit(f"No top recommendation found in {path}")
    patch = top[0].get("app_config_patch")
    if not isinstance(patch, dict):
        raise SystemExit(f"No app_config_patch found in {path}")
    return patch


def parse_recommendation(value: str) -> tuple[str, Path]:
    if "::" not in value:
        raise SystemExit("--recommendation must be formatted as bucket_filter::recommendation.json")
    bucket_filter, path_text = value.split("::", 1)
    bucket_filter = bucket_filter.strip()
    if not bucket_filter:
        raise SystemExit("--recommendation bucket_filter cannot be empty")
    return bucket_filter.lower(), Path(path_text)


def bucket_label(config: dict[str, Any]) -> str:
    profile = str(config.get("profile", ""))
    max_trade = str(config.get("max_trade_notional", ""))
    max_positions = str(config.get("max_open_positions", ""))
    dry_run = str(config.get("dry_run", ""))
    return f"profile={profile}, max_trade={max_trade}, max_positions={max_positions}, dry_run={dry_run}"


def latest_configs(files: list[Path]) -> OrderedDict[str, dict[str, Any]]:
    latest: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if "strategy_scan" not in raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
                if not config:
                    continue
                label = bucket_label(config)
                latest[label] = {
                    "label": label,
                    "file": path.name,
                    "date": tape_file_date(path),
                    "time": event.get("time"),
                    "config": config,
                    "trading_enabled": payload.get("trading_enabled"),
                    "entries_allowed": payload.get("entries_allowed"),
                    "should_trade": payload.get("should_trade"),
                }
    return latest


def alignment_for(config_row: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    config = config_row["config"]
    rows = []
    mismatches = 0
    missing = 0
    for key in COMPARE_KEYS:
        current = config.get(key)
        expected = patch.get(key)
        matches = same_value(current, expected)
        if current is None:
            missing += 1
        if not matches:
            mismatches += 1
        rows.append(
            {
                "key": key,
                "current": format_value(current),
                "expected": format_value(expected),
                "matches": matches,
            }
        )
    return {
        "label": config_row["label"],
        "file": config_row["file"],
        "date": config_row["date"],
        "time": config_row["time"],
        "trading_enabled": config_row["trading_enabled"],
        "entries_allowed": config_row["entries_allowed"],
        "should_trade": config_row["should_trade"],
        "mismatch_count": mismatches,
        "missing_count": missing,
        "aligned": mismatches == 0,
        "fields": rows,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Config Alignment",
        "",
        "Read-only comparison of latest sanitized day-tape strategy configs against recommendation patches.",
        "",
        f"Files: `{', '.join(report['files'])}`",
        "",
        "## Summary",
        "",
        "| Bucket | Recommendation | Aligned | Mismatches | Missing | Latest scan | State |",
        "| --- | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report["results"]:
        state = (
            f"trading={row['trading_enabled']}, entries={row['entries_allowed']}, should_trade={row['should_trade']}"
        )
        lines.append(
            f"| `{row['label']}` | `{row['recommendation']}` | {row['aligned']} | "
            f"{row['mismatch_count']} | {row['missing_count']} | {row['time']} | {state} |"
        )
    lines.extend(["", "## Differences", ""])
    for row in report["results"]:
        lines.extend(
            [
                f"### `{row['label']}`",
                "",
                "| Field | Current | Expected |",
                "| --- | ---: | ---: |",
            ]
        )
        differences = [field for field in row["fields"] if not field["matches"]]
        if not differences:
            lines.append("| all checked fields | aligned | aligned |")
        else:
            for field in differences:
                lines.append(f"| `{field['key']}` | `{field['current']}` | `{field['expected']}` |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare day-tape strategy configs with recommendation patches.")
    parser.add_argument("--path", type=Path, default=default_tape_dir())
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--end-date", default="")
    parser.add_argument(
        "--recommendation",
        action="append",
        required=True,
        help="bucket_filter::recommendation.json, for example max_positions=20::reports/recommendation.json",
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    files = selected_sweep_files(args.path, max(1, args.days), str(args.end_date or ""))
    if not files:
        raise SystemExit("No tape files selected.")
    configs = latest_configs(files)
    results = []
    for raw in args.recommendation:
        bucket_filter, path = parse_recommendation(raw)
        patch = load_patch(path)
        matches = [row for label, row in configs.items() if bucket_filter in label.lower()]
        if not matches:
            results.append(
                {
                    "label": bucket_filter,
                    "recommendation": str(path),
                    "aligned": False,
                    "mismatch_count": len(COMPARE_KEYS),
                    "missing_count": len(COMPARE_KEYS),
                    "time": "not found",
                    "trading_enabled": "n/a",
                    "entries_allowed": "n/a",
                    "should_trade": "n/a",
                    "fields": [],
                }
            )
            continue
        for match in matches:
            result = alignment_for(match, patch)
            result["recommendation"] = str(path)
            results.append(result)
    report = {
        "files": [path.name for path in files],
        "results": results,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for row in results:
        print(
            f"{row['label']}: aligned={row['aligned']} mismatches={row['mismatch_count']} "
            f"missing={row['missing_count']} latest={row['time']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
