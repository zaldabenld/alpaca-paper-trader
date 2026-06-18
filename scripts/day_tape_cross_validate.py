from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
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
    profile_with_simulation_overrides,
    selected_sweep_files,
    simulate_candidate,
    tape_file_date,
)


@dataclass
class FoldTape:
    file: Path
    events: list[Any]
    profiles: dict[str, Any]
    dropped_scans: int


def parse_decimal_list(value: str) -> list[Decimal]:
    items: list[Decimal] = []
    for raw in str(value or "").split(","):
        text = raw.strip()
        if not text:
            continue
        items.append(max(ZERO, Decimal(text)))
    return items or [Decimal("1")]


def parse_candidate_list(values: list[str]) -> list[str]:
    candidates: list[str] = []
    for value in values:
        for raw in str(value or "").split(","):
            text = raw.strip()
            if text:
                candidates.append(text)
    return candidates


def profit_factor_score(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return min(value, Decimal("99"))


def load_fold(path: Path, price_source: str, scan_interval_seconds: int) -> FoldTape:
    events, profiles = load_tape([path], price_source=price_source)
    events, dropped = compact_scan_events(events, scan_interval_seconds)
    return FoldTape(path, events, profiles, dropped)


def fold_passes(metrics: Any, min_trades: int, min_profit_factor: Decimal, max_drawdown_percent: Decimal) -> bool:
    return not fold_fail_reasons(metrics, min_trades, min_profit_factor, max_drawdown_percent)


def fold_fail_reasons(metrics: Any, min_trades: int, min_profit_factor: Decimal, max_drawdown_percent: Decimal) -> list[str]:
    reasons: list[str] = []
    if metrics.buys < min_trades:
        reasons.append(f"buys {metrics.buys} < {min_trades}")
    if metrics.open_positions > 0:
        reasons.append(f"open_positions {metrics.open_positions} > 0")
    if metrics.pnl <= ZERO:
        reasons.append(f"pnl {decimal_payload(metrics.pnl)} <= 0")
    profit_factor = metrics.profit_factor
    if profit_factor is None:
        reasons.append("profit_factor unavailable")
    elif profit_factor < min_profit_factor:
        reasons.append(f"profit_factor {decimal_payload(profit_factor)} < {decimal_payload(min_profit_factor)}")
    if metrics.drawdown_percent > max_drawdown_percent:
        reasons.append(
            f"drawdown {decimal_payload(metrics.drawdown_percent)} > {decimal_payload(max_drawdown_percent)}"
        )
    return reasons


def aggregate_result(
    candidate: Any,
    slippage_bps: Decimal,
    fold_results: list[dict[str, Any]],
    min_trades: int,
    min_profit_factor: Decimal,
    max_drawdown_percent: Decimal,
) -> dict[str, Any]:
    ok_folds = [fold for fold in fold_results if fold.get("status") == "ok"]
    metrics = [fold["raw_metrics"] for fold in ok_folds]
    passed_folds = [
        fold
        for fold in ok_folds
        if fold_passes(fold["raw_metrics"], min_trades, min_profit_factor, max_drawdown_percent)
    ]
    total_pnl = sum((item.pnl for item in metrics), ZERO)
    total_buys = sum(item.buys for item in metrics)
    total_exits = sum(item.exits for item in metrics)
    positive_folds = sum(1 for item in metrics if item.pnl > ZERO)
    active_folds = sum(1 for item in metrics if item.buys > 0)
    closed_folds = sum(1 for item in metrics if item.open_positions == 0)
    worst_pnl = min((item.pnl for item in metrics), default=ZERO)
    worst_drawdown_percent = max((item.drawdown_percent for item in metrics), default=ZERO)
    min_profit_factor_seen = min((profit_factor_score(item.profit_factor) for item in metrics), default=ZERO)
    stable = bool(metrics) and len(passed_folds) == len(metrics)
    serializable_folds = []
    for fold in fold_results:
        item = dict(fold)
        metrics_item = item.get("raw_metrics")
        if metrics_item is not None:
            reasons = fold_fail_reasons(metrics_item, min_trades, min_profit_factor, max_drawdown_percent)
            item["passes"] = not reasons
            item["fail_reasons"] = reasons
        item.pop("raw_metrics", None)
        serializable_folds.append(item)
    return {
        "stable": stable,
        "candidate": candidate_payload(candidate),
        "slippage_bps": decimal_payload(slippage_bps),
        "fold_count": len(metrics),
        "passed_fold_count": len(passed_folds),
        "active_fold_count": active_folds,
        "positive_fold_count": positive_folds,
        "closed_fold_count": closed_folds,
        "total_pnl": decimal_payload(total_pnl),
        "total_buys": total_buys,
        "total_exits": total_exits,
        "worst_fold_pnl": decimal_payload(worst_pnl),
        "worst_drawdown_percent": decimal_payload(worst_drawdown_percent),
        "min_profit_factor": "inf" if min_profit_factor_seen >= Decimal("90") else decimal_payload(min_profit_factor_seen),
        "folds": serializable_folds,
    }


def result_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["stable"],
        Decimal(item["total_pnl"]),
        item["positive_fold_count"],
        item["active_fold_count"],
        Decimal(item["min_profit_factor"]) if item["min_profit_factor"] != "inf" else Decimal("99"),
        -Decimal(item["worst_drawdown_percent"]),
        item["total_buys"],
    )


def run_cross_validate(
    files: list[Path],
    price_source: str,
    scan_interval_seconds: int,
    candidate_mode: str,
    exit_mode: str,
    bucket_contains: str,
    candidate_contains: str,
    candidate_list: list[str],
    slippage_values: list[Decimal],
    min_fold_trades: int,
    min_profit_factor: Decimal,
    max_drawdown_percent: Decimal,
    liquidate_at_end: bool,
    liquidate_on_close: bool,
    max_hold_minutes: int,
    min_stop_hold_minutes: int,
    entry_open_guard_minutes: int,
    top: int,
    json_output: Path | None,
    simulation_max_positions: int = 20,
    simulation_sizing_positions: int = 20,
    simulation_inverse_etf_mode: str = "",
) -> int:
    if not files:
        print("No day-tape files found.")
        return 0

    start = time.perf_counter()
    combined_events, combined_profiles = load_tape(files, price_source=price_source)
    combined_events, dropped_combined = compact_scan_events(combined_events, scan_interval_seconds)
    folds = [load_fold(path, price_source, scan_interval_seconds) for path in files]

    print("Day Tape Strategy Cross Validation")
    print(f"Files: {', '.join(path.name for path in files)}")
    print(f"Candidate mode: {candidate_mode}; exit mode: {exit_mode}; price source: {price_source}")
    print(f"Slippage bps: {', '.join(str(value) for value in slippage_values)}")
    print(f"Liquidate at fold end: {liquidate_at_end}; liquidate on close: {liquidate_on_close}")
    print(f"Entry open guard override: {entry_open_guard_minutes or 'disabled'} minutes")
    print(
        "Simulation capacity/sizing: "
        f"max positions={simulation_max_positions or 'profile'}, "
        f"sizing positions={simulation_sizing_positions or 'profile'}"
    )
    if simulation_inverse_etf_mode:
        print(f"Simulation inverse ETF mode override: {simulation_inverse_etf_mode}")
    print(f"Min fold trades: {min_fold_trades}; min PF: {min_profit_factor}; max DD: {max_drawdown_percent}%")
    if bucket_contains:
        print(f"Bucket filter: {bucket_contains}")
    if candidate_contains:
        print(f"Candidate filter: {candidate_contains}")
    if candidate_list:
        print(f"Candidate list: {', '.join(candidate_list)}")
    print()

    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": [path.name for path in files],
        "settings": {
            "price_source": price_source,
            "scan_interval_seconds": scan_interval_seconds,
            "candidate_mode": candidate_mode,
            "exit_mode": exit_mode,
            "bucket_contains": bucket_contains,
            "candidate_contains": candidate_contains,
            "candidate_list": candidate_list,
            "slippage_bps": [decimal_payload(value) for value in slippage_values],
            "min_fold_trades": min_fold_trades,
            "min_profit_factor": decimal_payload(min_profit_factor),
            "max_drawdown_percent": decimal_payload(max_drawdown_percent),
            "liquidate_at_end": liquidate_at_end,
            "liquidate_on_close": liquidate_on_close,
            "max_hold_minutes": max_hold_minutes,
            "min_stop_hold_minutes": min_stop_hold_minutes,
            "entry_open_guard_minutes": entry_open_guard_minutes,
            "simulation_max_positions": simulation_max_positions,
            "simulation_sizing_positions": simulation_sizing_positions,
            "simulation_inverse_etf_mode": simulation_inverse_etf_mode,
            "dropped_combined_scans": dropped_combined,
        },
        "buckets": [],
    }

    for combined_key, combined_profile in sorted(combined_profiles.items(), key=lambda item: item[1].label):
        combined_profile = profile_with_simulation_overrides(
            combined_profile,
            simulation_max_positions=simulation_max_positions,
            simulation_sizing_positions=simulation_sizing_positions,
            inverse_etf_mode=simulation_inverse_etf_mode,
        )
        if bucket_contains and bucket_contains.lower() not in combined_profile.label.lower():
            continue
        bucket_events = events_for_bucket(combined_events, combined_key)
        candidates = candidates_for_mode(combined_profile.config, candidate_mode, bucket_events, exit_mode)
        if candidate_contains:
            candidates = [
                candidate for candidate in candidates if candidate_contains.lower() in candidate.name.lower()
            ]
        if candidate_list:
            wanted = {name.lower() for name in candidate_list}
            candidates = [candidate for candidate in candidates if candidate.name.lower() in wanted]
        bucket_keys = {combined_key, *combined_profile.source_keys}
        bucket_report: dict[str, Any] = {
            "bucket": combined_key,
            "label": combined_profile.label,
            "candidate_count": len(candidates),
            "slippage_results": [],
        }
        print(f"Bucket: {combined_profile.label}")
        print(f"  candidates={len(candidates)}")

        for slippage_bps in slippage_values:
            candidate_results: list[dict[str, Any]] = []
            for candidate in candidates:
                fold_results: list[dict[str, Any]] = []
                for fold in folds:
                    matched_bucket, profile = matching_fold_profile(fold.profiles, bucket_keys)
                    if profile is None or matched_bucket is None:
                        fold_results.append(
                            {
                                "file": fold.file.name,
                                "date": tape_file_date(fold.file),
                                "status": "bucket_not_found",
                            }
                        )
                        continue
                    profile = profile_with_simulation_overrides(
                        profile,
                        simulation_max_positions=simulation_max_positions,
                        simulation_sizing_positions=simulation_sizing_positions,
                        inverse_etf_mode=simulation_inverse_etf_mode,
                    )
                    matched_events = events_for_bucket(fold.events, matched_bucket)
                    metrics = simulate_candidate(
                        matched_events,
                        profile,
                        candidate,
                        slippage_bps,
                        liquidate_at_end,
                        max_hold_minutes,
                        liquidate_on_close,
                        min_stop_hold_minutes=min_stop_hold_minutes,
                        entry_open_guard_minutes=entry_open_guard_minutes,
                    )
                    fold_results.append(
                        {
                            "file": fold.file.name,
                            "date": tape_file_date(fold.file),
                            "status": "ok",
                            "matched_bucket": matched_bucket,
                            "matched_label": profile.label,
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
            print(f"  slippage={slippage_bps} candidates={len(candidate_results)} stable={stable_count}")
            for rank, item in enumerate(candidate_results[:top], start=1):
                candidate_name = item["candidate"]["name"]
                marker = "stable" if item["stable"] else "provisional"
                print(
                    f"    #{rank} {marker} {candidate_name} "
                    f"total_pnl={item['total_pnl']} buys={item['total_buys']} "
                    f"positive_folds={item['positive_fold_count']}/{item['fold_count']} "
                    f"active_folds={item['active_fold_count']}/{item['fold_count']} "
                    f"min_pf={item['min_profit_factor']} worst_dd={item['worst_drawdown_percent']}%"
                )
            bucket_report["slippage_results"].append(
                {
                    "slippage_bps": decimal_payload(slippage_bps),
                    "stable_candidate_count": stable_count,
                    "top": candidate_results[:top],
                }
            )
        print()
        report["buckets"].append(bucket_report)

    report["elapsed_seconds"] = round(time.perf_counter() - start, 4)
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {json_output}")
    print(f"Elapsed: {report['elapsed_seconds']:.2f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank strategy candidates across each selected day tape as a fold.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=3, help="Most-recent tape files to use.")
    parser.add_argument("--end-date", default="", help="Only use tape files up through this YYYYMMDD date.")
    parser.add_argument("--top", type=int, default=8, help="Top candidates to print per bucket/slippage.")
    parser.add_argument("--candidate-mode", choices=("standard", "broad", "research", "impulse", "riskbox", "pricebox", "pricebox_session", "conservative_bridge"), default="broad")
    parser.add_argument("--exit-mode", choices=("fixed", "adaptive", "all"), default="adaptive")
    parser.add_argument("--bucket-contains", default="")
    parser.add_argument("--candidate-contains", default="")
    parser.add_argument(
        "--candidate-list",
        action="append",
        default=[],
        help="Comma-separated exact candidate names to test. May be repeated.",
    )
    parser.add_argument("--price-source", choices=("bars", "trades"), default="bars")
    parser.add_argument("--scan-interval-seconds", type=int, default=60)
    parser.add_argument("--slippage-bps-list", default="1,5,10")
    parser.add_argument("--min-fold-trades", type=int, default=1)
    parser.add_argument("--min-profit-factor", type=Decimal, default=Decimal("1.2"))
    parser.add_argument("--max-drawdown-percent", type=Decimal, default=Decimal("3.0"))
    parser.add_argument("--no-liquidate-at-end", action="store_true")
    parser.add_argument("--liquidate-on-close", action="store_true")
    parser.add_argument("--max-hold-minutes", type=int, default=0)
    parser.add_argument("--min-stop-hold-minutes", type=int, default=0)
    parser.add_argument("--entry-open-guard-minutes", type=int, default=0)
    parser.add_argument("--simulation-max-positions", type=int, default=20)
    parser.add_argument("--simulation-sizing-positions", type=int, default=20)
    parser.add_argument("--simulation-inverse-etf-mode", choices=("", "exclude", "allow", "inverse_only"), default="")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    files = selected_sweep_files(args.path, args.days, str(args.end_date or ""))
    return run_cross_validate(
        files=files,
        price_source=args.price_source,
        scan_interval_seconds=max(0, args.scan_interval_seconds),
        candidate_mode=args.candidate_mode,
        exit_mode=args.exit_mode,
        bucket_contains=str(args.bucket_contains or ""),
        candidate_contains=str(args.candidate_contains or ""),
        candidate_list=parse_candidate_list(args.candidate_list),
        slippage_values=parse_decimal_list(args.slippage_bps_list),
        min_fold_trades=max(0, args.min_fold_trades),
        min_profit_factor=max(ZERO, args.min_profit_factor),
        max_drawdown_percent=max(ZERO, args.max_drawdown_percent),
        liquidate_at_end=not args.no_liquidate_at_end,
        liquidate_on_close=bool(args.liquidate_on_close),
        max_hold_minutes=max(0, args.max_hold_minutes),
        min_stop_hold_minutes=max(0, args.min_stop_hold_minutes),
        entry_open_guard_minutes=max(0, args.entry_open_guard_minutes),
        top=max(1, args.top),
        json_output=args.json_output,
        simulation_max_positions=max(1, args.simulation_max_positions),
        simulation_sizing_positions=max(1, args.simulation_sizing_positions),
        simulation_inverse_etf_mode=str(args.simulation_inverse_etf_mode or ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
