from __future__ import annotations

import argparse
import csv
import json
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from day_tape_cross_validate import aggregate_result, load_fold, result_sort_key
from day_tape_strategy_sweep import (
    ZERO,
    Candidate,
    EntryTemplate,
    candidate_payload,
    compact_scan_events,
    decimal_payload,
    default_tape_dir,
    events_for_bucket,
    load_tape,
    matching_fold_profile,
    metric_line,
    metrics_payload,
    profile_with_simulation_overrides,
    selected_sweep_files,
    simulate_candidate,
    tape_file_date,
)


DEFAULT_TEMPLATE: dict[str, Any] = {
    "run_name": "manual-swing-momentum-v1",
    "notes": "Research-weighted momentum/relative-strength replay. Edit thresholds and weights, then rerun.",
    "simulation": {
        "days": 3,
        "end_date": "",
        "allow_partial": False,
        "price_source": "trades",
        "scan_interval_seconds": 15,
        "slippage_bps_list": [5, 10, 15],
        "bucket_contains": "",
        "top": 8,
        "simulation_max_positions": 20,
        "simulation_sizing_positions": 20,
        "simulation_inverse_etf_mode": "",
        "liquidate_at_end": True,
        "liquidate_on_close": True,
        "max_hold_minutes": 0,
        "min_stop_hold_minutes": 0,
        "entry_open_guard_minutes": 15,
        "min_fold_trades": 1,
        "min_profit_factor": 1.2,
        "max_drawdown_percent": 3.0,
    },
    "strategies": [
        {
            "name": "weighted-session-momentum",
            "entry": {
                "rsi_min": 42,
                "rsi_max": 70,
                "min_entry_score": 42,
                "min_momentum": 0.05,
                "min_recent_momentum": 0.03,
                "min_long_momentum": 0,
                "min_session_change": 0.1,
                "min_vwap_distance": 0,
                "max_vwap_distance": 2.5,
                "max_session_pullback": 1.0,
                "max_recent_pullback": 0.6,
                "min_smi": 30,
                "min_relative_volume": 1.0,
                "min_price": 0,
                "max_price": 0,
                "max_relative_volume": 0,
                "max_atr_percent": 0,
                "max_volatility_percent": 0,
                "score_bias": 0,
            },
            "score_weights": {
                "momentum": 18,
                "recent_momentum": 10,
                "long_momentum": 12,
                "session_change": 18,
                "relative_volume": 10,
                "vwap_distance": 8,
                "smi": 8,
                "rsi_fit": 6,
                "buy_flow": 4,
                "volatility": 0,
                "volatility_penalty": 3,
                "session_pullback_penalty": 10,
                "recent_pullback_penalty": 7,
                "vwap_extension_penalty": 8,
                "session_extension_penalty": 4,
                "smi_overheat_penalty": 4,
            },
            "exits": [
                {
                    "name": "balanced_2.5_1.25",
                    "take_profit_percent": 2.5,
                    "stop_loss_percent": 1.25,
                    "reentry_score_boost": 12,
                    "exit_style": "fixed",
                },
                {
                    "name": "trend_3_1.5",
                    "take_profit_percent": 3.0,
                    "stop_loss_percent": 1.5,
                    "reentry_score_boost": 12,
                    "exit_style": "fixed",
                },
            ],
        }
    ],
}


CSV_FIELDS = [
    "generated_at",
    "run_id",
    "run_name",
    "bucket",
    "label",
    "candidate",
    "slippage_bps",
    "stable",
    "fold_count",
    "passed_fold_count",
    "positive_fold_count",
    "active_fold_count",
    "total_pnl",
    "total_buys",
    "total_exits",
    "worst_fold_pnl",
    "worst_drawdown_percent",
    "min_profit_factor",
    "report_path",
    "config_path",
    "files",
]


def decimal_value(value: Any, default: Decimal = ZERO) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def decimal_list(value: Any) -> list[Decimal]:
    if isinstance(value, list):
        values = [decimal_value(item) for item in value]
    else:
        values = [decimal_value(item.strip()) for item in str(value or "").split(",") if item.strip()]
    return [max(ZERO, item) for item in values if item >= ZERO] or [Decimal("10")]


def int_setting(settings: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def bool_setting(settings: dict[str, Any], key: str, default: bool) -> bool:
    value = settings.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def selected_hub_files(path: Path, days: int, end_date: str, allow_partial: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if allow_partial:
        return selected_sweep_files(path, days, end_date)
    today = datetime.now().strftime("%Y%m%d")
    files = sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)
    if end_date:
        files = [item for item in files if tape_file_date(item) <= end_date]
    files = [item for item in files if tape_file_date(item) < today]
    return files[-max(1, days) :]


def score_weights_from_spec(spec: dict[str, Any]) -> tuple[tuple[str, Decimal], ...]:
    weights = spec.get("score_weights") if isinstance(spec.get("score_weights"), dict) else {}
    return tuple(sorted((str(key), decimal_value(value)) for key, value in weights.items()))


def entry_from_spec(strategy: dict[str, Any]) -> EntryTemplate:
    entry = strategy.get("entry") if isinstance(strategy.get("entry"), dict) else {}
    name = str(strategy.get("name") or entry.get("name") or "manual")
    return EntryTemplate(
        name=name,
        rsi_min=decimal_value(entry.get("rsi_min"), Decimal("42")),
        rsi_max=decimal_value(entry.get("rsi_max"), Decimal("70")),
        min_entry_score=decimal_value(entry.get("min_entry_score"), Decimal("42")),
        min_momentum=decimal_value(entry.get("min_momentum"), Decimal("0.05")),
        min_recent_momentum=decimal_value(entry.get("min_recent_momentum"), Decimal("0.03")),
        min_long_momentum=decimal_value(entry.get("min_long_momentum"), ZERO),
        min_session_change=decimal_value(entry.get("min_session_change"), Decimal("0.1")),
        min_vwap_distance=decimal_value(entry.get("min_vwap_distance"), ZERO),
        max_vwap_distance=decimal_value(entry.get("max_vwap_distance"), Decimal("2.5")),
        max_session_pullback=decimal_value(entry.get("max_session_pullback"), Decimal("1.0")),
        max_recent_pullback=decimal_value(entry.get("max_recent_pullback"), Decimal("0.6")),
        min_smi=decimal_value(entry.get("min_smi"), Decimal("30")),
        min_relative_volume=decimal_value(entry.get("min_relative_volume"), Decimal("1.0")),
        min_price=decimal_value(entry.get("min_price"), ZERO),
        max_price=decimal_value(entry.get("max_price"), ZERO),
        max_relative_volume=decimal_value(entry.get("max_relative_volume"), ZERO),
        max_atr_percent=decimal_value(entry.get("max_atr_percent"), ZERO),
        max_volatility_percent=decimal_value(entry.get("max_volatility_percent"), ZERO),
        score_weights=score_weights_from_spec(strategy),
        score_bias=decimal_value(entry.get("score_bias"), ZERO),
    )


def candidates_from_config(config: dict[str, Any]) -> list[Candidate]:
    strategies = config.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        strategies = DEFAULT_TEMPLATE["strategies"]
    candidates: list[Candidate] = []
    for raw_strategy in strategies:
        if not isinstance(raw_strategy, dict):
            continue
        entry = entry_from_spec(raw_strategy)
        exits = raw_strategy.get("exits")
        if not isinstance(exits, list) or not exits:
            exits = DEFAULT_TEMPLATE["strategies"][0]["exits"]
        for raw_exit in exits:
            if not isinstance(raw_exit, dict):
                continue
            exit_name = str(raw_exit.get("name") or "manual_exit")
            candidates.append(
                Candidate(
                    name=f"{entry.name}|{exit_name}",
                    entry=entry,
                    take_profit_percent=decimal_value(raw_exit.get("take_profit_percent"), Decimal("2.5")),
                    stop_loss_percent=decimal_value(raw_exit.get("stop_loss_percent"), Decimal("1.25")),
                    reentry_score_boost=decimal_value(raw_exit.get("reentry_score_boost"), Decimal("12")),
                    exit_style=str(raw_exit.get("exit_style") or "fixed"),
                    trail_activation_percent=decimal_value(raw_exit.get("trail_activation_percent"), ZERO),
                    trail_distance_percent=decimal_value(raw_exit.get("trail_distance_percent"), ZERO),
                    profit_lock_percent=decimal_value(raw_exit.get("profit_lock_percent"), ZERO),
                )
            )
    return candidates


def filter_candidates(candidates: list[Candidate], contains: str) -> list[Candidate]:
    needle = str(contains or "").strip().lower()
    if not needle:
        return candidates
    return [candidate for candidate in candidates if needle in candidate.name.lower()]


def write_template(path: Path, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_TEMPLATE, indent=2), encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def log_row(
    generated_at: str,
    run_id: str,
    run_name: str,
    bucket: str,
    label: str,
    item: dict[str, Any],
    files: list[Path],
    report_path: Path,
    config_path: Path,
) -> dict[str, Any]:
    candidate = item["candidate"]
    return {
        "generated_at": generated_at,
        "run_id": run_id,
        "run_name": run_name,
        "bucket": bucket,
        "label": label,
        "candidate": candidate["name"],
        "candidate_payload": candidate,
        "slippage_bps": item["slippage_bps"],
        "stable": item["stable"],
        "fold_count": item["fold_count"],
        "passed_fold_count": item["passed_fold_count"],
        "positive_fold_count": item["positive_fold_count"],
        "active_fold_count": item["active_fold_count"],
        "total_pnl": item["total_pnl"],
        "total_buys": item["total_buys"],
        "total_exits": item["total_exits"],
        "worst_fold_pnl": item["worst_fold_pnl"],
        "worst_drawdown_percent": item["worst_drawdown_percent"],
        "min_profit_factor": item["min_profit_factor"],
        "report_path": str(report_path),
        "config_path": str(config_path),
        "files": ",".join(path.name for path in files),
    }


def run_hub(config_path: Path, args: argparse.Namespace) -> int:
    if not config_path.exists():
        write_template(config_path, force=False)
        print(f"Created template: {config_path}")
        print("Edit it, then rerun this command.")
        return 0

    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = config.get("simulation") if isinstance(config.get("simulation"), dict) else {}
    tape_path = args.path or Path(str(settings.get("path") or default_tape_dir()))
    days = args.days if args.days is not None else int_setting(settings, "days", 3)
    end_date = args.end_date if args.end_date is not None else str(settings.get("end_date") or "")
    allow_partial = bool(args.allow_partial or bool_setting(settings, "allow_partial", False))
    files = selected_hub_files(tape_path, max(1, days), end_date, allow_partial)
    if not files:
        print("No completed day-tape files found.")
        return 0

    run_id = uuid.uuid4().hex[:12]
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run_name = str(args.run_name or config.get("run_name") or "manual-simulation")
    log_dir = args.log_dir or Path("reports/manual")
    report_path = log_dir / f"{generated_at.replace(':', '').replace('-', '')}-{run_id}.json"
    jsonl_path = log_dir / "simulation-runs.jsonl"
    csv_path = log_dir / "simulation-runs.csv"

    price_source = str(args.price_source or settings.get("price_source") or "trades")
    scan_interval_seconds = (
        args.scan_interval_seconds
        if args.scan_interval_seconds is not None
        else int_setting(settings, "scan_interval_seconds", 15)
    )
    slippage_values = decimal_list(
        args.slippage_bps_list
        if args.slippage_bps_list is not None
        else settings.get("slippage_bps_list", [10])
    )
    bucket_contains = args.bucket_contains if args.bucket_contains is not None else str(settings.get("bucket_contains") or "")
    top = args.top if args.top is not None else int_setting(settings, "top", 8)
    simulation_max_positions = int_setting(settings, "simulation_max_positions", 20)
    simulation_sizing_positions = int_setting(settings, "simulation_sizing_positions", 20)
    simulation_inverse_etf_mode = str(settings.get("simulation_inverse_etf_mode") or "")
    liquidate_at_end = bool_setting(settings, "liquidate_at_end", True)
    liquidate_on_close = bool_setting(settings, "liquidate_on_close", True)
    max_hold_minutes = max(0, int_setting(settings, "max_hold_minutes", 0))
    min_stop_hold_minutes = max(0, int_setting(settings, "min_stop_hold_minutes", 0))
    entry_open_guard_minutes = max(0, int_setting(settings, "entry_open_guard_minutes", 15))
    collect_trades = bool(args.collect_trades or bool_setting(settings, "collect_trades", False))
    min_fold_trades = max(0, int_setting(settings, "min_fold_trades", 1))
    min_profit_factor = max(ZERO, decimal_value(settings.get("min_profit_factor"), Decimal("1.2")))
    max_drawdown_percent = max(ZERO, decimal_value(settings.get("max_drawdown_percent"), Decimal("3.0")))
    candidates = filter_candidates(candidates_from_config(config), str(args.candidate_contains or ""))
    if not candidates:
        print("No candidates matched the selected config/filter.")
        return 0

    start = time.perf_counter()
    combined_events, combined_profiles = load_tape(files, price_source="bars")
    combined_events, dropped_combined = compact_scan_events(combined_events, max(0, scan_interval_seconds))
    folds = [load_fold(path, price_source, max(0, scan_interval_seconds)) for path in files]

    report: dict[str, Any] = {
        "generated_at": generated_at,
        "run_id": run_id,
        "run_name": run_name,
        "notes": str(config.get("notes") or ""),
        "files": [path.name for path in files],
        "settings": {
            "price_source": price_source,
            "scan_interval_seconds": scan_interval_seconds,
            "slippage_bps_list": [decimal_payload(value) for value in slippage_values],
            "bucket_contains": bucket_contains,
            "top": top,
            "simulation_max_positions": simulation_max_positions,
            "simulation_sizing_positions": simulation_sizing_positions,
            "simulation_inverse_etf_mode": simulation_inverse_etf_mode,
            "liquidate_at_end": liquidate_at_end,
            "liquidate_on_close": liquidate_on_close,
            "max_hold_minutes": max_hold_minutes,
            "min_stop_hold_minutes": min_stop_hold_minutes,
            "entry_open_guard_minutes": entry_open_guard_minutes,
            "collect_trades": collect_trades,
            "min_fold_trades": min_fold_trades,
            "min_profit_factor": decimal_payload(min_profit_factor),
            "max_drawdown_percent": decimal_payload(max_drawdown_percent),
            "dropped_combined_scans": dropped_combined,
            "allow_partial": allow_partial,
        },
        "strategies": [candidate_payload(candidate) for candidate in candidates],
        "buckets": [],
    }
    log_rows: list[dict[str, Any]] = []

    print("Strategy Simulation Hub")
    print(f"Run: {run_name} ({run_id})")
    print(f"Files: {', '.join(path.name for path in files)}")
    print(
        "Fixed simulation assumptions: "
        f"max positions={simulation_max_positions}, sizing positions={simulation_sizing_positions}"
    )
    print(f"Strategies: {len(candidates)} candidate/exit combinations")
    print()

    for combined_key, raw_profile in sorted(combined_profiles.items(), key=lambda item: item[1].label):
        profile = profile_with_simulation_overrides(
            raw_profile,
            simulation_max_positions=simulation_max_positions,
            simulation_sizing_positions=simulation_sizing_positions,
            inverse_etf_mode=simulation_inverse_etf_mode,
        )
        if bucket_contains and bucket_contains.lower() not in profile.label.lower():
            continue
        bucket_keys = {combined_key, *profile.source_keys}
        bucket_report: dict[str, Any] = {
            "bucket": combined_key,
            "label": profile.label,
            "candidate_count": len(candidates),
            "slippage_results": [],
        }
        print(f"Bucket: {profile.label}")
        for slippage_bps in slippage_values:
            candidate_results: list[dict[str, Any]] = []
            for candidate in candidates:
                fold_results: list[dict[str, Any]] = []
                for fold in folds:
                    matched_bucket, fold_profile = matching_fold_profile(fold.profiles, bucket_keys)
                    if fold_profile is None or matched_bucket is None:
                        fold_results.append(
                            {
                                "file": fold.file.name,
                                "date": tape_file_date(fold.file),
                                "status": "bucket_not_found",
                            }
                        )
                        continue
                    fold_profile = profile_with_simulation_overrides(
                        fold_profile,
                        simulation_max_positions=simulation_max_positions,
                        simulation_sizing_positions=simulation_sizing_positions,
                        inverse_etf_mode=simulation_inverse_etf_mode,
                    )
                    matched_events = events_for_bucket(fold.events, matched_bucket)
                    metrics = simulate_candidate(
                        matched_events,
                        fold_profile,
                        candidate,
                        slippage_bps,
                        liquidate_at_end,
                        max_hold_minutes,
                        liquidate_on_close,
                        min_stop_hold_minutes=min_stop_hold_minutes,
                        entry_open_guard_minutes=entry_open_guard_minutes,
                        collect_trades=collect_trades,
                    )
                    fold_results.append(
                        {
                            "file": fold.file.name,
                            "date": tape_file_date(fold.file),
                            "status": "ok",
                            "matched_bucket": matched_bucket,
                            "matched_label": fold_profile.label,
                            "dropped_scans": fold.dropped_scans,
                            "metrics": metrics_payload(metrics),
                            "line": metric_line(metrics),
                            "raw_metrics": metrics,
                        }
                    )
                candidate_results.append(
                    aggregate_result(
                        candidate,
                        slippage_bps,
                        fold_results,
                        min_fold_trades,
                        min_profit_factor,
                        max_drawdown_percent,
                    )
                )

            candidate_results.sort(key=result_sort_key, reverse=True)
            stable_count = sum(1 for item in candidate_results if item["stable"])
            print(f"  slippage={slippage_bps} stable={stable_count}/{len(candidate_results)}")
            for rank, item in enumerate(candidate_results[:top], start=1):
                marker = "stable" if item["stable"] else "provisional"
                print(
                    f"    #{rank} {marker} {item['candidate']['name']} "
                    f"pnl={item['total_pnl']} buys={item['total_buys']} "
                    f"positive={item['positive_fold_count']}/{item['fold_count']} "
                    f"worst_dd={item['worst_drawdown_percent']}%"
                )
            for item in candidate_results:
                log_rows.append(log_row(generated_at, run_id, run_name, combined_key, profile.label, item, files, report_path, config_path))
            bucket_report["slippage_results"].append(
                {
                    "slippage_bps": decimal_payload(slippage_bps),
                    "stable_candidate_count": stable_count,
                    "top": candidate_results[:top],
                    "all": candidate_results,
                }
            )
        report["buckets"].append(bucket_report)
        print()

    report["elapsed_seconds"] = round(time.perf_counter() - start, 4)
    report["log_files"] = {"jsonl": str(jsonl_path), "csv": str(csv_path)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    append_jsonl(jsonl_path, log_rows)
    append_csv(csv_path, log_rows)
    print(f"Report: {report_path}")
    print(f"Appended logs: {jsonl_path}; {csv_path}")
    print(f"Elapsed: {report['elapsed_seconds']:.2f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual replay simulation hub with append-only result logs.")
    parser.add_argument("--config", type=Path, default=Path("reports/manual/manual-strategy-template.json"))
    parser.add_argument("--init-template", action="store_true", help="Create a starter manual strategy config and exit.")
    parser.add_argument("--force", action="store_true", help="Overwrite the starter config when used with --init-template.")
    parser.add_argument("--path", type=Path, help="Tape directory or one tape file. Defaults to LOCALAPPDATA day-tape.")
    parser.add_argument("--days", type=int, help="Override configured day count.")
    parser.add_argument("--end-date", help="Override configured final YYYYMMDD tape date.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow today's partial tape in the run.")
    parser.add_argument("--bucket-contains", help="Override configured bucket/account label filter.")
    parser.add_argument("--candidate-contains", default="", help="Only run candidates whose name contains this text.")
    parser.add_argument("--price-source", choices=("bars", "trades"), help="Override configured price source.")
    parser.add_argument("--scan-interval-seconds", type=int, help="Override configured scan compaction interval.")
    parser.add_argument("--slippage-bps-list", help="Override configured comma-separated slippage bps list.")
    parser.add_argument("--collect-trades", action="store_true", help="Include entry/exit ledgers in the JSON report.")
    parser.add_argument("--top", type=int, help="Override configured top result count.")
    parser.add_argument("--run-name", default="", help="Override the run name stored in logs.")
    parser.add_argument("--log-dir", type=Path, help="Directory for report JSON plus append-only CSV/JSONL logs.")
    args = parser.parse_args()

    if args.init_template:
        write_template(args.config, force=bool(args.force))
        print(f"Template written: {args.config}")
        return 0
    return run_hub(args.config, args)


if __name__ == "__main__":
    raise SystemExit(main())
