from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")
BPS = Decimal("10000")


def dec(value: Any) -> Decimal:
    if value in (None, "", "inf"):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal, places: str = "0.0001") -> str:
    return format(value.quantize(Decimal(places)), "f")


def percent(numerator: Decimal, denominator: Decimal) -> str:
    if denominator == ZERO:
        return "0.0000"
    return fmt(numerator / denominator * Decimal("100"))


def parse_spec(raw: str) -> tuple[Path, str | None]:
    if "::" not in raw:
        return Path(raw), None
    path_text, label = raw.split("::", 1)
    return Path(path_text), label.strip() or None


def exit_trade_rows(path: Path, label_override: str | None) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings") if isinstance(report.get("settings"), dict) else {}
    label = label_override or str(settings.get("bucket_contains") or path.stem)
    candidate = str(settings.get("candidate") or "")
    slippage_bps = str(settings.get("slippage_bps") or "")
    rows = []
    fold_totals: dict[str, Decimal] = defaultdict(Decimal)
    for fold in report.get("folds", []):
        metrics = fold.get("metrics") if isinstance(fold.get("metrics"), dict) else {}
        date = str(fold.get("date") or "")
        for trade in metrics.get("trades") or []:
            if not isinstance(trade, dict) or trade.get("event") != "exit":
                continue
            qty = dec(trade.get("qty"))
            entry_price = dec(trade.get("entry_price"))
            exit_price = dec(trade.get("exit_price"))
            realized_pl = dec(trade.get("realized_pl"))
            row = {
                "source": str(path),
                "strategy": label,
                "candidate": candidate,
                "slippage_bps": slippage_bps,
                "date": date,
                "symbol": str(trade.get("symbol") or ""),
                "reason": str(trade.get("reason") or ""),
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "realized_pl": realized_pl,
                "held_minutes": dec(trade.get("held_minutes")),
                "round_trip_notional": qty * entry_price + qty * exit_price,
            }
            rows.append(row)
            fold_totals[date] += realized_pl
    return {
        "label": label,
        "candidate": candidate,
        "slippage_bps": slippage_bps,
        "source": str(path),
        "trades": rows,
        "fold_totals": dict(fold_totals),
    }


def stress_result(trades: list[dict[str, Any]], extra_bps: Decimal) -> dict[str, Any]:
    by_date: dict[str, Decimal] = defaultdict(Decimal)
    total = ZERO
    for trade in trades:
        adjusted = trade["realized_pl"] - trade["round_trip_notional"] * extra_bps / BPS
        by_date[trade["date"]] += adjusted
        total += adjusted
    positive_folds = sum(1 for value in by_date.values() if value > ZERO)
    return {
        "extra_bps": fmt(extra_bps),
        "total_pnl": fmt(total),
        "positive_fold_count": positive_folds,
        "fold_count": len(by_date),
        "folds": [{"date": date, "pnl": fmt(value)} for date, value in sorted(by_date.items())],
    }


def summarize(name: str, source: str, candidate: str, slippage_bps: str, trades: list[dict[str, Any]], extra_bps_values: list[Decimal]) -> dict[str, Any]:
    total = sum((trade["realized_pl"] for trade in trades), ZERO)
    wins = [trade for trade in trades if trade["realized_pl"] > ZERO]
    losses = [trade for trade in trades if trade["realized_pl"] < ZERO]
    by_date: dict[str, Decimal] = defaultdict(Decimal)
    reason_pnl: dict[str, Decimal] = defaultdict(Decimal)
    reason_counts: Counter[str] = Counter()
    for trade in trades:
        by_date[trade["date"]] += trade["realized_pl"]
        reason_pnl[trade["reason"]] += trade["realized_pl"]
        reason_counts[trade["reason"]] += 1

    best_trade = max((trade["realized_pl"] for trade in trades), default=ZERO)
    worst_trade = min((trade["realized_pl"] for trade in trades), default=ZERO)
    best_day = max(by_date.values(), default=ZERO)
    worst_day = min(by_date.values(), default=ZERO)
    close_liquidation_profit = sum(
        (trade["realized_pl"] for trade in trades if trade["reason"] == "close_liquidation" and trade["realized_pl"] > ZERO),
        ZERO,
    )
    remove_best_trade = total - best_trade if best_trade > ZERO else total
    remove_best_day = total - best_day if best_day > ZERO else total
    without_close_liq_winners = total - close_liquidation_profit
    stress_rows = [stress_result(trades, item) for item in extra_bps_values]

    flags = []
    if len(trades) < 20:
        flags.append(f"thin trade sample ({len(trades)} exits)")
    if len(by_date) < 5:
        flags.append(f"thin day sample ({len(by_date)} folds)")
    if total <= ZERO:
        flags.append("non-positive target P/L")
    if remove_best_trade <= ZERO:
        flags.append("profit disappears if the best trade is removed")
    if remove_best_day <= ZERO:
        flags.append("profit disappears if the best day is removed")
    if without_close_liq_winners <= ZERO:
        flags.append("profit depends on positive close-liquidation exits")
    if total > ZERO and best_trade / total > Decimal("0.50"):
        flags.append("best trade contributes more than 50% of total P/L")
    if total > ZERO and close_liquidation_profit / total > Decimal("0.50"):
        flags.append("positive close-liquidation exits contribute more than 50% of total P/L")
    for row in stress_rows:
        if row["positive_fold_count"] != row["fold_count"]:
            flags.append(f"extra {row['extra_bps']} bps cost breaks at least one fold")
            break

    if total > ZERO and not any("profit disappears" in flag for flag in flags):
        decision = "paper-test candidate; concentration still provisional" if flags else "paper-test candidate"
    elif total > ZERO:
        decision = "research only until concentration improves"
    else:
        decision = "research only"

    return {
        "name": name,
        "source": source,
        "candidate": candidate,
        "slippage_bps": slippage_bps,
        "decision": decision,
        "trade_count": len(trades),
        "fold_count": len(by_date),
        "total_pnl": fmt(total),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": percent(Decimal(len(wins)), Decimal(len(trades))) if trades else "0.0000",
        "gross_profit": fmt(sum((trade["realized_pl"] for trade in wins), ZERO)),
        "gross_loss": fmt(sum((trade["realized_pl"] for trade in losses), ZERO)),
        "expectancy_per_exit": fmt(total / Decimal(len(trades)) if trades else ZERO),
        "best_trade_pnl": fmt(best_trade),
        "worst_trade_pnl": fmt(worst_trade),
        "best_trade_share_percent": percent(best_trade, total) if total > ZERO and best_trade > ZERO else "0.0000",
        "best_day_pnl": fmt(best_day),
        "worst_day_pnl": fmt(worst_day),
        "best_day_share_percent": percent(best_day, total) if total > ZERO and best_day > ZERO else "0.0000",
        "remove_best_trade_pnl": fmt(remove_best_trade),
        "remove_best_day_pnl": fmt(remove_best_day),
        "close_liquidation_profit": fmt(close_liquidation_profit),
        "close_liquidation_profit_share_percent": percent(close_liquidation_profit, total)
        if total > ZERO and close_liquidation_profit > ZERO
        else "0.0000",
        "pnl_without_close_liquidation_winners": fmt(without_close_liq_winners),
        "reason_summary": [
            {
                "reason": reason,
                "count": reason_counts[reason],
                "pnl": fmt(pnl),
            }
            for reason, pnl in sorted(reason_pnl.items())
        ],
        "folds": [{"date": date, "pnl": fmt(value)} for date, value in sorted(by_date.items())],
        "extra_cost_stress": stress_rows,
        "evidence_flags": flags,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Fragility Audit",
        "",
        "Trade-level stress audit for selected replay candidates. This checks concentration, close-liquidation dependence, and additional transaction-cost sensitivity on top of the target slippage already used in the diagnostics.",
        "",
        "## Summary",
        "",
        "| Strategy | P/L | Exits | Win rate | Best trade share | Best day share | Remove best trade | Remove best day | Close-liq winner share | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["strategies"]:
        lines.append(
            f"| `{item['name']}` | {item['total_pnl']} | {item['trade_count']} | "
            f"{item['win_rate_percent']}% | {item['best_trade_share_percent']}% | "
            f"{item['best_day_share_percent']}% | {item['remove_best_trade_pnl']} | "
            f"{item['remove_best_day_pnl']} | {item['close_liquidation_profit_share_percent']}% | {item['decision']} |"
        )
    lines.extend(["", "## Evidence Flags", ""])
    for item in report["strategies"]:
        lines.append(f"### `{item['name']}`")
        if item["evidence_flags"]:
            for flag in item["evidence_flags"]:
                lines.append(f"- {flag}")
        else:
            lines.append("- none")
        lines.append("")

    lines.extend(["## Reason And Fold Detail", ""])
    for item in report["strategies"]:
        lines.extend(
            [
                f"### `{item['name']}`",
                "",
                f"Source: `{item['source']}`",
                "",
                f"Candidate: `{item['candidate']}`",
                "",
                f"Target diagnostic slippage: `{item['slippage_bps']}` bps",
                "",
                "| Exit reason | Count | P/L |",
                "| --- | ---: | ---: |",
            ]
        )
        for reason in item["reason_summary"]:
            lines.append(f"| `{reason['reason']}` | {reason['count']} | {reason['pnl']} |")
        lines.extend(["", "| Date | P/L |", "| --- | ---: |"])
        for fold in item["folds"]:
            lines.append(f"| {fold['date']} | {fold['pnl']} |")
        lines.extend(["", "| Extra cost | Total P/L | Positive folds |", "| ---: | ---: | ---: |"])
        for stress in item["extra_cost_stress"]:
            lines.append(
                f"| {stress['extra_bps']} bps | {stress['total_pnl']} | "
                f"{stress['positive_fold_count']}/{stress['fold_count']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit trade-level concentration and fragility for replay diagnostics.")
    parser.add_argument("--diagnostics", action="append", required=True, help="diagnostic.json or diagnostic.json::label")
    parser.add_argument("--extra-bps-list", default="5,10", help="Additional per-side bps cost stress levels.")
    parser.add_argument("--include-portfolio", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    extra_bps_values = [dec(item.strip()) for item in args.extra_bps_list.split(",") if item.strip()]
    loaded = [exit_trade_rows(*parse_spec(raw)) for raw in args.diagnostics]
    strategies = [
        summarize(
            item["label"],
            item["source"],
            item["candidate"],
            item["slippage_bps"],
            item["trades"],
            extra_bps_values,
        )
        for item in loaded
    ]
    if args.include_portfolio and len(loaded) > 1:
        portfolio_trades = []
        for item in loaded:
            portfolio_trades.extend(item["trades"])
        strategies.append(
            summarize(
                "combined aggressive portfolio",
                ", ".join(item["source"] for item in loaded),
                ", ".join(sorted({item["candidate"] for item in loaded})),
                loaded[0]["slippage_bps"],
                portfolio_trades,
                extra_bps_values,
            )
        )

    report = {
        "extra_bps_list": [fmt(item) for item in extra_bps_values],
        "strategies": strategies,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for item in strategies:
        print(
            f"{item['name']}: pnl={item['total_pnl']} exits={item['trade_count']} "
            f"remove_best_trade={item['remove_best_trade_pnl']} "
            f"remove_best_day={item['remove_best_day_pnl']} decision={item['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
