from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from day_tape_cross_validate import (
    FoldTape,
    fold_fail_reasons,
    load_fold,
    parse_candidate_list,
    parse_decimal_list,
)
from day_tape_strategy_sweep import (
    ZERO,
    Candidate,
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


@dataclass
class CandidateFold:
    date: str
    file: str
    status: str
    metrics: Any | None = None
    line: str = ""
    fail_reasons: list[str] | None = None


def profit_factor_score(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return min(value, Decimal("99"))


def train_aggregate(
    fold_rows: list[CandidateFold],
    min_fold_trades: int,
    min_profit_factor: Decimal,
    max_drawdown_percent: Decimal,
) -> dict[str, Any]:
    ok_rows = [row for row in fold_rows if row.status == "ok" and row.metrics is not None]
    metrics = [row.metrics for row in ok_rows]
    total_pnl = sum((item.pnl for item in metrics), ZERO)
    total_buys = sum(item.buys for item in metrics)
    total_exits = sum(item.exits for item in metrics)
    gross_profit = sum((item.gross_profit for item in metrics), ZERO)
    gross_loss = sum((item.gross_loss for item in metrics), ZERO)
    profit_factor: Decimal | None
    if gross_loss > ZERO:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > ZERO:
        profit_factor = Decimal("99")
    else:
        profit_factor = None
    positive_folds = sum(1 for item in metrics if item.pnl > ZERO)
    active_folds = sum(1 for item in metrics if item.buys > 0)
    closed_folds = sum(1 for item in metrics if item.open_positions == 0)
    worst_fold_pnl = min((item.pnl for item in metrics), default=ZERO)
    worst_drawdown_percent = max((item.drawdown_percent for item in metrics), default=ZERO)
    passed_folds = [
        row
        for row in ok_rows
        if row.metrics is not None
        and not fold_fail_reasons(row.metrics, min_fold_trades, min_profit_factor, max_drawdown_percent)
    ]
    passes = bool(metrics) and len(passed_folds) == len(metrics)
    return {
        "passes": passes,
        "fold_count": len(metrics),
        "passed_fold_count": len(passed_folds),
        "positive_fold_count": positive_folds,
        "active_fold_count": active_folds,
        "closed_fold_count": closed_folds,
        "total_pnl": total_pnl,
        "total_buys": total_buys,
        "total_exits": total_exits,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "worst_fold_pnl": worst_fold_pnl,
        "worst_drawdown_percent": worst_drawdown_percent,
    }


def aggregate_payload(aggregate: dict[str, Any]) -> dict[str, Any]:
    profit_factor = aggregate["profit_factor"]
    return {
        "passes": aggregate["passes"],
        "fold_count": aggregate["fold_count"],
        "passed_fold_count": aggregate["passed_fold_count"],
        "positive_fold_count": aggregate["positive_fold_count"],
        "active_fold_count": aggregate["active_fold_count"],
        "closed_fold_count": aggregate["closed_fold_count"],
        "total_pnl": decimal_payload(aggregate["total_pnl"]),
        "total_buys": aggregate["total_buys"],
        "total_exits": aggregate["total_exits"],
        "gross_profit": decimal_payload(aggregate["gross_profit"]),
        "gross_loss": decimal_payload(aggregate["gross_loss"]),
        "profit_factor": (
            None
            if profit_factor is None
            else ("inf" if profit_factor >= Decimal("90") else decimal_payload(profit_factor))
        ),
        "worst_fold_pnl": decimal_payload(aggregate["worst_fold_pnl"]),
        "worst_drawdown_percent": decimal_payload(aggregate["worst_drawdown_percent"]),
    }


def train_sort_key(item: tuple[Candidate, dict[str, Any]]) -> tuple[Any, ...]:
    _candidate, aggregate = item
    return (
        aggregate["passes"],
        aggregate["total_pnl"],
        aggregate["positive_fold_count"],
        profit_factor_score(aggregate["profit_factor"]),
        -aggregate["worst_drawdown_percent"],
        aggregate["total_buys"],
    )


def simulate_folds_for_candidates(
    folds: list[FoldTape],
    bucket_keys: set[str],
    candidates: list[Candidate],
    slippage_bps: Decimal,
    liquidate_at_end: bool,
    liquidate_on_close: bool,
    max_hold_minutes: int,
    min_stop_hold_minutes: int,
    entry_open_guard_minutes: int,
    min_fold_trades: int,
    min_profit_factor: Decimal,
    max_drawdown_percent: Decimal,
) -> dict[str, list[CandidateFold]]:
    by_candidate: dict[str, list[CandidateFold]] = {candidate.name: [] for candidate in candidates}
    for fold in folds:
        matched_bucket, profile = matching_fold_profile(fold.profiles, bucket_keys)
        if profile is None or matched_bucket is None:
            for candidate in candidates:
                by_candidate[candidate.name].append(
                    CandidateFold(
                        date=tape_file_date(fold.file),
                        file=fold.file.name,
                        status="bucket_not_found",
                    )
                )
            continue
        matched_events = events_for_bucket(fold.events, matched_bucket)
        for candidate in candidates:
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
            by_candidate[candidate.name].append(
                CandidateFold(
                    date=tape_file_date(fold.file),
                    file=fold.file.name,
                    status="ok",
                    metrics=metrics,
                    line=metric_line(metrics),
                    fail_reasons=fold_fail_reasons(
                        metrics,
                        min_fold_trades,
                        min_profit_factor,
                        max_drawdown_percent,
                    ),
                )
            )
    return by_candidate


def candidate_fold_payload(row: CandidateFold) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": row.date,
        "file": row.file,
        "status": row.status,
    }
    if row.metrics is not None:
        payload["metrics"] = metrics_payload(row.metrics)
        payload["line"] = row.line
        payload["fail_reasons"] = row.fail_reasons or []
        payload["passes"] = not payload["fail_reasons"]
    return payload


def run_walk_forward(
    files: list[Path],
    price_source: str,
    scan_interval_seconds: int,
    candidate_mode: str,
    exit_mode: str,
    bucket_contains: str,
    candidate_contains: str,
    candidate_list: list[str],
    slippage_bps: Decimal,
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
    markdown_output: Path | None,
) -> int:
    if len(files) < 2:
        print("Walk-forward needs at least two completed tape files.")
        return 1
    start = time.perf_counter()
    combined_events, combined_profiles = load_tape(files, price_source=price_source)
    combined_events, dropped_combined = compact_scan_events(combined_events, scan_interval_seconds)
    folds = [load_fold(path, price_source, scan_interval_seconds) for path in files]

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
            "slippage_bps": decimal_payload(slippage_bps),
            "min_fold_trades": min_fold_trades,
            "min_profit_factor": decimal_payload(min_profit_factor),
            "max_drawdown_percent": decimal_payload(max_drawdown_percent),
            "liquidate_at_end": liquidate_at_end,
            "liquidate_on_close": liquidate_on_close,
            "max_hold_minutes": max_hold_minutes,
            "min_stop_hold_minutes": min_stop_hold_minutes,
            "entry_open_guard_minutes": entry_open_guard_minutes,
            "dropped_combined_scans": dropped_combined,
        },
        "buckets": [],
    }

    print("Day Tape Walk-Forward Selection")
    print(f"Files: {', '.join(path.name for path in files)}")
    print(f"Candidate mode: {candidate_mode}; exit mode: {exit_mode}; price source: {price_source}")
    print(f"Slippage bps: {slippage_bps}")
    print()

    for combined_key, combined_profile in sorted(combined_profiles.items(), key=lambda item: item[1].label):
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
        print(f"Bucket: {combined_profile.label}")
        print(f"  candidates={len(candidates)}")
        if not candidates:
            continue
        fold_results = simulate_folds_for_candidates(
            folds,
            bucket_keys,
            candidates,
            slippage_bps,
            liquidate_at_end,
            liquidate_on_close,
            max_hold_minutes,
            min_stop_hold_minutes,
            entry_open_guard_minutes,
            min_fold_trades,
            min_profit_factor,
            max_drawdown_percent,
        )
        walk_rows: list[dict[str, Any]] = []
        validation_metrics = []
        selected_names: set[str] = set()
        for validation_fold in folds:
            validation_date = tape_file_date(validation_fold.file)
            train_rankings: list[tuple[Candidate, dict[str, Any]]] = []
            candidate_by_name = {candidate.name: candidate for candidate in candidates}
            for candidate in candidates:
                train_rows = [row for row in fold_results[candidate.name] if row.date != validation_date]
                aggregate = train_aggregate(train_rows, min_fold_trades, min_profit_factor, max_drawdown_percent)
                train_rankings.append((candidate, aggregate))
            train_rankings.sort(key=train_sort_key, reverse=True)
            selectable = [(candidate, aggregate) for candidate, aggregate in train_rankings if aggregate["passes"]]
            selected_candidate, selected_train = selectable[0] if selectable else train_rankings[0]
            selected_names.add(selected_candidate.name)
            validation_row = next(
                row for row in fold_results[selected_candidate.name] if row.date == validation_date
            )
            validation_pass = (
                validation_row.metrics is not None
                and not fold_fail_reasons(
                    validation_row.metrics,
                    min_fold_trades,
                    min_profit_factor,
                    max_drawdown_percent,
                )
            )
            if validation_row.metrics is not None:
                validation_metrics.append(validation_row.metrics)
            top_rows = [
                {
                    "rank": rank,
                    "candidate": candidate_payload(candidate),
                    "train": aggregate_payload(aggregate),
                }
                for rank, (candidate, aggregate) in enumerate(train_rankings[:top], start=1)
            ]
            walk_rows.append(
                {
                    "validation_date": validation_date,
                    "selected_candidate": candidate_payload(selected_candidate),
                    "selected_train": aggregate_payload(selected_train),
                    "selected_had_training_pass": selected_train["passes"],
                    "validation": candidate_fold_payload(validation_row),
                    "validation_passes": validation_pass,
                    "top_train_candidates": top_rows,
                }
            )
            print(
                f"    holdout={validation_date} selected={selected_candidate.name} "
                f"train_pnl={decimal_payload(selected_train['total_pnl'])} "
                f"validation_pnl="
                f"{decimal_payload(validation_row.metrics.pnl) if validation_row.metrics is not None else 'n/a'} "
                f"validation_pass={validation_pass}"
            )
        total_validation_pnl = sum((metrics.pnl for metrics in validation_metrics), ZERO)
        positive_validation_folds = sum(1 for metrics in validation_metrics if metrics.pnl > ZERO)
        passed_validation_folds = sum(1 for row in walk_rows if row["validation_passes"])
        total_buys = sum(metrics.buys for metrics in validation_metrics)
        summary = {
            "walk_forward_passes": bool(walk_rows) and passed_validation_folds == len(walk_rows),
            "validation_fold_count": len(walk_rows),
            "passed_validation_fold_count": passed_validation_folds,
            "positive_validation_fold_count": positive_validation_folds,
            "total_validation_pnl": decimal_payload(total_validation_pnl),
            "total_validation_buys": total_buys,
            "unique_selected_candidate_count": len(selected_names),
            "selected_candidates": sorted(selected_names),
        }
        print(
            f"  walk_forward_pass={summary['walk_forward_passes']} "
            f"validation_pnl={summary['total_validation_pnl']} "
            f"passed={passed_validation_folds}/{len(walk_rows)}"
        )
        report["buckets"].append(
            {
                "bucket": combined_key,
                "label": combined_profile.label,
                "candidate_count": len(candidates),
                "summary": summary,
                "walk_forward": walk_rows,
            }
        )
        print()

    report["elapsed_seconds"] = round(time.perf_counter() - start, 4)
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {json_output}")
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {markdown_output}")
    print(f"Elapsed: {report['elapsed_seconds']:.2f}s")
    return 0


def markdown_report(report: dict[str, Any]) -> str:
    settings = report["settings"]
    lines = [
        "# Day Tape Walk-Forward Selection",
        "",
        "Leave-one-day-out selection test. For each held-out tape day, candidates are ranked only on the other selected days; the selected training winner is then replayed on the held-out day.",
        "",
        "This is stricter than ranking a candidate after seeing every fold and is meant to catch parameter choices that only look good after hindsight.",
        "",
        "## Settings",
        "",
        f"- Files: `{', '.join(report['files'])}`",
        f"- Candidate mode: `{settings['candidate_mode']}`",
        f"- Exit mode: `{settings['exit_mode']}`",
        f"- Price source: `{settings['price_source']}`",
        f"- Slippage: `{settings['slippage_bps']}` bps",
        f"- Close liquidation: `{settings['liquidate_on_close']}`",
        f"- Stop grace: `{settings['min_stop_hold_minutes']}` minutes",
        "",
    ]
    for bucket in report["buckets"]:
        summary = bucket["summary"]
        lines.extend(
            [
                f"## {bucket['label']}",
                "",
                f"- Candidate count: `{bucket['candidate_count']}`",
                f"- Walk-forward pass: `{summary['walk_forward_passes']}`",
                f"- Validation P/L: `{summary['total_validation_pnl']}`",
                f"- Validation buys: `{summary['total_validation_buys']}`",
                f"- Passed validation folds: `{summary['passed_validation_fold_count']}/{summary['validation_fold_count']}`",
                f"- Positive validation folds: `{summary['positive_validation_fold_count']}/{summary['validation_fold_count']}`",
                f"- Unique selected candidates: `{summary['unique_selected_candidate_count']}`",
                "",
                "| Holdout | Selected candidate | Train P/L | Train folds + | Validation P/L | Validation buys | Pass |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in bucket["walk_forward"]:
            train = row["selected_train"]
            validation = row["validation"].get("metrics") or {}
            selected = row["selected_candidate"]["name"]
            lines.append(
                f"| {row['validation_date']} | `{selected}` | {train['total_pnl']} | "
                f"{train['passed_fold_count']}/{train['fold_count']} | "
                f"{validation.get('pnl', 'n/a')} | {validation.get('buys', 'n/a')} | "
                f"{row['validation_passes']} |"
            )
        lines.append("")
        for row in bucket["walk_forward"]:
            fail_reasons = row["validation"].get("fail_reasons") or []
            if not fail_reasons:
                continue
            lines.append(f"Validation fail reasons for `{row['validation_date']}`:")
            for reason in fail_reasons:
                lines.append(f"- {reason}")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Leave-one-day-out walk-forward selector for day-tape candidates.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=3, help="Most-recent tape files to use.")
    parser.add_argument("--end-date", default="", help="Only use tape files up through this YYYYMMDD date.")
    parser.add_argument("--top", type=int, default=5, help="Top training candidates to store for each holdout.")
    parser.add_argument(
        "--candidate-mode",
        choices=("standard", "broad", "research", "impulse", "riskbox", "pricebox", "pricebox_session", "conservative_bridge"),
        default="broad",
    )
    parser.add_argument("--exit-mode", choices=("fixed", "adaptive", "all"), default="fixed")
    parser.add_argument("--bucket-contains", default="")
    parser.add_argument("--candidate-contains", default="")
    parser.add_argument(
        "--candidate-list",
        action="append",
        default=[],
        help="Comma-separated exact candidate names to test. May be repeated.",
    )
    parser.add_argument("--price-source", choices=("bars", "trades"), default="trades")
    parser.add_argument("--scan-interval-seconds", type=int, default=60)
    parser.add_argument("--slippage-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--min-fold-trades", type=int, default=1)
    parser.add_argument("--min-profit-factor", type=Decimal, default=Decimal("1.2"))
    parser.add_argument("--max-drawdown-percent", type=Decimal, default=Decimal("3.0"))
    parser.add_argument("--no-liquidate-at-end", action="store_true")
    parser.add_argument("--liquidate-on-close", action="store_true")
    parser.add_argument("--max-hold-minutes", type=int, default=0)
    parser.add_argument("--min-stop-hold-minutes", type=int, default=0)
    parser.add_argument("--entry-open-guard-minutes", type=int, default=0)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    files = selected_sweep_files(args.path, args.days, str(args.end_date or ""))
    return run_walk_forward(
        files=files,
        price_source=args.price_source,
        scan_interval_seconds=max(0, args.scan_interval_seconds),
        candidate_mode=args.candidate_mode,
        exit_mode=args.exit_mode,
        bucket_contains=str(args.bucket_contains or ""),
        candidate_contains=str(args.candidate_contains or ""),
        candidate_list=parse_candidate_list(args.candidate_list),
        slippage_bps=max(ZERO, args.slippage_bps),
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
        markdown_output=args.markdown_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
