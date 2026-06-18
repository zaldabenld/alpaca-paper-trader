from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


FEATURES = (
    ("row_price", "Entry price"),
    ("score", "Entry score"),
    ("rsi", "RSI"),
    ("momentum", "Momentum"),
    ("recent_momentum", "Recent momentum"),
    ("long_momentum", "Long momentum"),
    ("session_change", "Session change"),
    ("vwap_distance", "VWAP distance"),
    ("session_pullback", "Session pullback"),
    ("recent_pullback", "Recent pullback"),
    ("smi", "SMI"),
    ("relative_volume", "Relative volume"),
    ("atr", "ATR"),
    ("volatility", "Volatility"),
)


GATES = (
    ("row_price", "min_price", "min"),
    ("row_price", "max_price", "max"),
    ("score", "min_entry_score", "min"),
    ("rsi", "rsi_min", "min"),
    ("rsi", "rsi_max", "max"),
    ("momentum", "min_momentum", "min"),
    ("recent_momentum", "min_recent_momentum", "min"),
    ("long_momentum", "min_long_momentum", "min"),
    ("session_change", "min_session_change", "min"),
    ("vwap_distance", "min_vwap_distance", "min"),
    ("vwap_distance", "max_vwap_distance", "max"),
    ("session_pullback", "max_session_pullback", "max"),
    ("recent_pullback", "max_recent_pullback", "max"),
    ("smi", "min_smi", "min"),
    ("relative_volume", "min_relative_volume", "min"),
)


def dec(value: Any) -> Decimal:
    if value in (None, "", "inf"):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal, places: str = "0.0001") -> str:
    return format(value.quantize(Decimal(places)), "f")


def money(value: Decimal) -> str:
    sign = "+" if value >= ZERO else "-"
    return f"{sign}${fmt(abs(value))}"


def parse_spec(raw: str) -> tuple[Path, str | None]:
    if "::" not in raw:
        return Path(raw), None
    path_text, label = raw.split("::", 1)
    return Path(path_text), label.strip() or None


def quantile(values: list[Decimal], q: Decimal) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def decimal_summary(values: list[Decimal]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "min": "n/a",
            "p25": "n/a",
            "median": "n/a",
            "p75": "n/a",
            "max": "n/a",
            "mean": "n/a",
        }
    total = sum(values, ZERO)
    return {
        "count": len(values),
        "min": fmt(min(values)),
        "p25": fmt(quantile(values, Decimal("0.25"))),
        "median": fmt(quantile(values, Decimal("0.50"))),
        "p75": fmt(quantile(values, Decimal("0.75"))),
        "max": fmt(max(values)),
        "mean": fmt(total / Decimal(len(values))),
    }


def load_report(path: Path, label_override: str | None) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings") if isinstance(report.get("settings"), dict) else {}
    label = label_override or str(settings.get("bucket_contains") or path.stem)
    trades = []
    for fold in report.get("folds", []):
        date = str(fold.get("date") or "")
        metrics = fold.get("metrics") if isinstance(fold.get("metrics"), dict) else {}
        pending_entries: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for trade in metrics.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            symbol = str(trade.get("symbol") or "").upper()
            if trade.get("event") == "entry":
                pending_entries[symbol].append(trade)
                continue
            if trade.get("event") != "exit":
                continue
            entry = pending_entries[symbol].popleft() if pending_entries[symbol] else {}
            features = entry.get("features") if isinstance(entry.get("features"), dict) else {}
            trades.append(
                {
                    "date": date,
                    "label": label,
                    "source": str(path),
                    "candidate": str(settings.get("candidate") or ""),
                    "symbol": symbol,
                    "entry_time": entry.get("time"),
                    "exit_time": trade.get("time"),
                    "reason": trade.get("reason"),
                    "realized_pl": fmt(dec(trade.get("realized_pl"))),
                    "_realized_pl": dec(trade.get("realized_pl")),
                    "features": {name: fmt(dec(features.get(name))) for name, _title in FEATURES},
                    "_features": {name: dec(features.get(name)) for name, _title in FEATURES},
                }
            )
    return {
        "label": label,
        "source": str(path),
        "settings": settings,
        "trades": trades,
    }


def candidate_entry(report: dict[str, Any]) -> dict[str, Any]:
    for fold in report.get("folds", []):
        candidate = fold.get("candidate") if isinstance(fold.get("candidate"), dict) else {}
        entry = candidate.get("entry") if isinstance(candidate.get("entry"), dict) else {}
        if entry:
            return entry
    return {}


def load_candidate_entry(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    return candidate_entry(report)


def threshold_map(entry: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = []
    for feature, key, direction in GATES:
        raw = entry.get(key)
        if raw in (None, "", "0", "0.0000") and key in {"max_price", "max_vwap_distance", "max_session_pullback", "max_recent_pullback"}:
            if key == "max_price":
                continue
        threshold = dec(raw)
        if key in {"max_price", "max_vwap_distance", "max_session_pullback", "max_recent_pullback"} and threshold <= ZERO:
            continue
        thresholds.append(
            {
                "feature": feature,
                "key": key,
                "direction": direction,
                "threshold": fmt(threshold),
                "_threshold": threshold,
            }
        )
    return thresholds


def gate_failures(trade: dict[str, Any], thresholds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    features = trade.get("_features") or {}
    for gate in thresholds:
        value = features.get(gate["feature"], ZERO)
        threshold = gate["_threshold"]
        direction = gate["direction"]
        failed = value < threshold if direction == "min" else value > threshold
        if failed:
            failures.append(
                {
                    "feature": gate["feature"],
                    "key": gate["key"],
                    "direction": direction,
                    "value": fmt(value),
                    "threshold": fmt(threshold),
                    "distance": fmt((threshold - value) if direction == "min" else (value - threshold)),
                }
            )
    return failures


def summarize_feature(trades: list[dict[str, Any]], feature: str) -> dict[str, Any]:
    all_values = [trade["_features"][feature] for trade in trades]
    win_values = [trade["_features"][feature] for trade in trades if trade["_realized_pl"] > ZERO]
    loss_values = [trade["_features"][feature] for trade in trades if trade["_realized_pl"] < ZERO]
    if len(all_values) >= 2:
        try:
            pnl_corr = Decimal(
                str(
                    statistics.correlation(
                        [float(item) for item in all_values],
                        [float(trade["_realized_pl"]) for trade in trades],
                    )
                )
            )
        except statistics.StatisticsError:
            pnl_corr = ZERO
    else:
        pnl_corr = ZERO
    return {
        "feature": feature,
        "all": decimal_summary(all_values),
        "winners": decimal_summary(win_values),
        "losers": decimal_summary(loss_values),
        "pnl_correlation": fmt(pnl_corr),
    }


def gate_support(selected_trades: list[dict[str, Any]], comparison_trades: list[dict[str, Any]], thresholds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for gate in thresholds:
        feature = gate["feature"]
        threshold = gate["_threshold"]
        direction = gate["direction"]
        selected_values = [trade["_features"][feature] for trade in selected_trades]
        margins = [
            (value - threshold) if direction == "min" else (threshold - value)
            for value in selected_values
        ]
        rejected = []
        accepted = []
        for trade in comparison_trades:
            failures = gate_failures(trade, [gate])
            target = rejected if failures else accepted
            target.append(trade)
        rejected_pnl = sum((trade["_realized_pl"] for trade in rejected), ZERO)
        accepted_pnl = sum((trade["_realized_pl"] for trade in accepted), ZERO)
        rows.append(
            {
                "key": gate["key"],
                "feature": feature,
                "direction": direction,
                "threshold": fmt(threshold),
                "selected_margin_min": fmt(min(margins)) if margins else "n/a",
                "selected_margin_median": fmt(quantile(margins, Decimal("0.50"))) if margins else "n/a",
                "comparison_rejected_trades": len(rejected),
                "comparison_rejected_pnl": fmt(rejected_pnl),
                "comparison_accepted_trades": len(accepted),
                "comparison_accepted_pnl": fmt(accepted_pnl),
            }
        )
    return rows


def rejected_trade_rows(comparison_trades: list[dict[str, Any]], thresholds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for trade in comparison_trades:
        failures = gate_failures(trade, thresholds)
        if not failures:
            continue
        rows.append(
            {
                "date": trade["date"],
                "label": trade["label"],
                "symbol": trade["symbol"],
                "realized_pl": trade["realized_pl"],
                "reason": trade["reason"],
                "failed_gates": failures,
            }
        )
    rows.sort(key=lambda item: dec(item["realized_pl"]))
    return rows


def clean_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for trade in trades:
        item = dict(trade)
        item.pop("_features", None)
        item.pop("_realized_pl", None)
        cleaned.append(item)
    return cleaned


def build_report(selected: list[dict[str, Any]], comparison: list[dict[str, Any]], thresholds: list[dict[str, Any]]) -> dict[str, Any]:
    selected_trades = [trade for report in selected for trade in report["trades"]]
    comparison_trades = [trade for report in comparison for trade in report["trades"]]
    feature_rows = [summarize_feature(selected_trades, feature) for feature, _title in FEATURES]
    rejected_rows = rejected_trade_rows(comparison_trades, thresholds)
    return {
        "selected_sources": [{"label": item["label"], "source": item["source"]} for item in selected],
        "comparison_sources": [{"label": item["label"], "source": item["source"]} for item in comparison],
        "selected_trade_count": len(selected_trades),
        "selected_total_pnl": fmt(sum((trade["_realized_pl"] for trade in selected_trades), ZERO)),
        "comparison_trade_count": len(comparison_trades),
        "comparison_total_pnl": fmt(sum((trade["_realized_pl"] for trade in comparison_trades), ZERO)),
        "thresholds": [{k: v for k, v in item.items() if not k.startswith("_")} for item in thresholds],
        "feature_summaries": feature_rows,
        "gate_support": gate_support(selected_trades, comparison_trades, thresholds),
        "comparison_rejected_trades": rejected_rows,
        "selected_trades": clean_trades(selected_trades),
        "evidence_flags": evidence_flags(selected_trades, comparison_trades, rejected_rows),
    }


def evidence_flags(selected_trades: list[dict[str, Any]], comparison_trades: list[dict[str, Any]], rejected_rows: list[dict[str, Any]]) -> list[str]:
    flags = []
    if len(selected_trades) < 20:
        flags.append(f"thin selected trade sample ({len(selected_trades)} exits)")
    days = {trade["date"] for trade in selected_trades}
    if len(days) < 5:
        flags.append(f"thin selected day sample ({len(days)} days)")
    if len(comparison_trades) < len(selected_trades):
        flags.append("comparison sample is smaller than selected sample")
    rejected_pnl = sum((dec(item["realized_pl"]) for item in rejected_rows), ZERO)
    if rejected_rows and rejected_pnl < ZERO:
        flags.append(f"current gates reject {len(rejected_rows)} comparison trades for {money(rejected_pnl)}")
    if not rejected_rows:
        flags.append("no comparison trades were rejected by current gates")
    return flags


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Parameter Evidence",
        "",
        "Trade-level feature evidence for the selected replay candidate. This report is intentionally descriptive: it explains which gates are supported by observed trade outcomes and which still rely on thin-sample assumptions.",
        "",
        f"Selected trades: `{report['selected_trade_count']}`; selected P/L: `{money(dec(report['selected_total_pnl']))}`",
        f"Comparison trades: `{report['comparison_trade_count']}`; comparison P/L: `{money(dec(report['comparison_total_pnl']))}`",
        "",
        "## Evidence Flags",
        "",
    ]
    for flag in report["evidence_flags"]:
        lines.append(f"- {flag}")
    lines.extend(
        [
            "",
            "## Gate Support",
            "",
            "| Gate | Threshold | Selected min margin | Selected median margin | Comparison rejected | Rejected P/L | Comparison accepted | Accepted P/L |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["gate_support"]:
        direction = ">=" if row["direction"] == "min" else "<="
        lines.append(
            f"| `{row['key']}` | {direction} `{row['threshold']}` | {row['selected_margin_min']} | "
            f"{row['selected_margin_median']} | {row['comparison_rejected_trades']} | "
            f"{money(dec(row['comparison_rejected_pnl']))} | {row['comparison_accepted_trades']} | "
            f"{money(dec(row['comparison_accepted_pnl']))} |"
        )
    if report["comparison_rejected_trades"]:
        lines.extend(["", "## Rejected Comparison Trades", ""])
        lines.extend(
            [
                "| Date | Label | Symbol | P/L | Reason | Failed gates |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for row in report["comparison_rejected_trades"]:
            failed = ", ".join(
                f"{item['key']} {item['direction']} threshold {item['threshold']} vs {item['value']}"
                for item in row["failed_gates"]
            )
            lines.append(
                f"| {row['date']} | `{row['label']}` | `{row['symbol']}` | {money(dec(row['realized_pl']))} | "
                f"{row['reason']} | {failed} |"
            )
    lines.extend(
        [
            "",
            "## Feature Distributions",
            "",
            "| Feature | All median | Winners median | Losers median | All range | P/L corr |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    labels = dict(FEATURES)
    for row in report["feature_summaries"]:
        all_stats = row["all"]
        win_stats = row["winners"]
        loss_stats = row["losers"]
        lines.append(
            f"| {labels.get(row['feature'], row['feature'])} | {all_stats['median']} | {win_stats['median']} | "
            f"{loss_stats['median']} | {all_stats['min']}..{all_stats['max']} | {row['pnl_correlation']} |"
        )
    lines.extend(
        [
            "",
            "## Selected Trades",
            "",
            "| Date | Label | Symbol | P/L | Reason | Key features |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for trade in report["selected_trades"]:
        features = trade["features"]
        key_features = (
            f"score {features['score']}, session {features['session_change']}, "
            f"SMI {features['smi']}, VWAP {features['vwap_distance']}, price {features['row_price']}"
        )
        lines.append(
            f"| {trade['date']} | `{trade['label']}` | `{trade['symbol']}` | {money(dec(trade['realized_pl']))} | "
            f"{trade['reason']} | {key_features} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain selected strategy parameters with trade-level replay evidence.")
    parser.add_argument("--selected-diagnostics", action="append", required=True, help="diagnostic.json or diagnostic.json::label")
    parser.add_argument("--comparison-diagnostics", action="append", default=[], help="Older/failed diagnostic.json or diagnostic.json::label")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    selected = [load_report(*parse_spec(raw)) for raw in args.selected_diagnostics]
    comparison = [load_report(*parse_spec(raw)) for raw in args.comparison_diagnostics]
    first_path, _label = parse_spec(args.selected_diagnostics[0])
    thresholds = threshold_map(load_candidate_entry(first_path))
    report = build_report(selected, comparison, thresholds)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    print(
        f"selected_trades={report['selected_trade_count']} selected_pnl={report['selected_total_pnl']} "
        f"comparison_rejected={len(report['comparison_rejected_trades'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
