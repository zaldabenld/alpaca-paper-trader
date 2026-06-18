from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    if value in (None, "", "inf"):
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal, places: str = "0.0001") -> str:
    return format(value.quantize(Decimal(places)), "f")


def percent(value: Decimal) -> str:
    return fmt(value * Decimal("100"))


def parse_spec(raw: str) -> tuple[Path, str | None]:
    if "::" not in raw:
        return Path(raw), None
    path_text, label = raw.split("::", 1)
    return Path(path_text), label.strip() or None


def load_diagnostics(path: Path, label_override: str | None) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings") if isinstance(report.get("settings"), dict) else {}
    label = label_override or str(settings.get("bucket_contains") or path.stem)
    candidate = str(settings.get("candidate") or "")
    slippage_bps = str(settings.get("slippage_bps") or "")
    trade_pls: list[Decimal] = []
    day_pls: dict[str, Decimal] = defaultdict(Decimal)
    for fold in report.get("folds", []):
        date = str(fold.get("date") or "")
        metrics = fold.get("metrics") if isinstance(fold.get("metrics"), dict) else {}
        for trade in metrics.get("trades") or []:
            if not isinstance(trade, dict) or trade.get("event") != "exit":
                continue
            realized = dec(trade.get("realized_pl"))
            trade_pls.append(realized)
            day_pls[date] += realized
    return {
        "label": label,
        "candidate": candidate,
        "source": str(path),
        "slippage_bps": slippage_bps,
        "trade_pls": trade_pls,
        "day_pls": dict(day_pls),
    }


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


def bootstrap(values: list[Decimal], sample_size: int, iterations: int, rng: random.Random) -> dict[str, Any]:
    if not values or sample_size <= 0:
        return {
            "iterations": iterations,
            "positive_probability": "0.0000",
            "p05": "0.0000",
            "p25": "0.0000",
            "p50": "0.0000",
            "p75": "0.0000",
            "p95": "0.0000",
        }
    totals = []
    for _ in range(iterations):
        total = sum((rng.choice(values) for _item in range(sample_size)), ZERO)
        totals.append(total)
    positive_probability = Decimal(sum(1 for item in totals if item > ZERO)) / Decimal(iterations)
    return {
        "iterations": iterations,
        "positive_probability": percent(positive_probability),
        "p05": fmt(quantile(totals, Decimal("0.05"))),
        "p25": fmt(quantile(totals, Decimal("0.25"))),
        "p50": fmt(quantile(totals, Decimal("0.50"))),
        "p75": fmt(quantile(totals, Decimal("0.75"))),
        "p95": fmt(quantile(totals, Decimal("0.95"))),
    }


def stddev(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    return Decimal(str(statistics.stdev(float(item) for item in values)))


def summarize(label: str, source: str, candidate: str, slippage_bps: str, trade_pls: list[Decimal], day_pls: dict[str, Decimal], iterations: int, seed: int) -> dict[str, Any]:
    total = sum(trade_pls, ZERO)
    day_values = [day_pls[date] for date in sorted(day_pls)]
    trade_count = len(trade_pls)
    day_count = len(day_values)
    wins = [item for item in trade_pls if item > ZERO]
    losses = [item for item in trade_pls if item < ZERO]
    rng = random.Random(seed)
    trade_bootstrap = bootstrap(trade_pls, trade_count, iterations, rng)
    day_bootstrap = bootstrap(day_values, day_count, iterations, rng)
    flags = []
    if total <= ZERO:
        flags.append("non-positive observed P/L")
    if day_count < 5:
        flags.append(f"thin day sample ({day_count} folds)")
    if trade_count < 20:
        flags.append(f"thin trade sample ({trade_count} exits)")
    if dec(trade_bootstrap["p05"]) <= ZERO:
        flags.append("trade bootstrap 5th percentile is non-positive")
    if dec(day_bootstrap["p05"]) <= ZERO:
        flags.append("day bootstrap 5th percentile is non-positive")
    if dec(trade_bootstrap["positive_probability"].replace("%", "")) < Decimal("95"):
        flags.append("trade bootstrap positive probability below 95%")
    if dec(day_bootstrap["positive_probability"].replace("%", "")) < Decimal("95"):
        flags.append("day bootstrap positive probability below 95%")
    if total > ZERO and all("bootstrap" not in flag for flag in flags):
        decision = "paper-test candidate; sample still provisional" if flags else "paper-test candidate"
    elif total > ZERO:
        decision = "paper-test candidate; confidence weak"
    else:
        decision = "research only"
    return {
        "name": label,
        "source": source,
        "candidate": candidate,
        "slippage_bps": slippage_bps,
        "decision": decision,
        "observed_total_pnl": fmt(total),
        "trade_count": trade_count,
        "day_count": day_count,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_percent": percent(Decimal(len(wins)) / Decimal(trade_count)) if trade_count else "0.0000",
        "mean_trade_pnl": fmt(total / Decimal(trade_count) if trade_count else ZERO),
        "trade_pnl_stddev": fmt(stddev(trade_pls)),
        "mean_day_pnl": fmt(sum(day_values, ZERO) / Decimal(day_count) if day_count else ZERO),
        "day_pnl_stddev": fmt(stddev(day_values)),
        "trade_bootstrap": trade_bootstrap,
        "day_bootstrap": day_bootstrap,
        "days": [{"date": date, "pnl": fmt(day_pls[date])} for date in sorted(day_pls)],
        "evidence_flags": flags,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Confidence Audit",
        "",
        "Deterministic bootstrap audit over observed trade exits and completed-day fold P/L. This is not a proof of future profitability; it quantifies how weak or strong the current small sample looks under simple resampling.",
        "",
        f"Bootstrap iterations: `{report['iterations']}`",
        "",
        "## Summary",
        "",
        "| Strategy | P/L | Exits | Days | Win rate | Trade P(+)| Trade p05 | Day P(+)| Day p05 | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["strategies"]:
        lines.append(
            f"| `{item['name']}` | {item['observed_total_pnl']} | {item['trade_count']} | "
            f"{item['day_count']} | {item['win_rate_percent']}% | "
            f"{item['trade_bootstrap']['positive_probability']}% | {item['trade_bootstrap']['p05']} | "
            f"{item['day_bootstrap']['positive_probability']}% | {item['day_bootstrap']['p05']} | "
            f"{item['decision']} |"
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
    lines.extend(["## Detail", ""])
    for item in report["strategies"]:
        lines.extend(
            [
                f"### `{item['name']}`",
                "",
                f"Source: `{item['source']}`",
                "",
                f"Candidate: `{item['candidate']}`",
                "",
                f"Diagnostic slippage: `{item['slippage_bps']}` bps",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Mean trade P/L | {item['mean_trade_pnl']} |",
                f"| Trade P/L stddev | {item['trade_pnl_stddev']} |",
                f"| Mean day P/L | {item['mean_day_pnl']} |",
                f"| Day P/L stddev | {item['day_pnl_stddev']} |",
                f"| Trade bootstrap p25/p50/p75 | {item['trade_bootstrap']['p25']} / {item['trade_bootstrap']['p50']} / {item['trade_bootstrap']['p75']} |",
                f"| Day bootstrap p25/p50/p75 | {item['day_bootstrap']['p25']} / {item['day_bootstrap']['p50']} / {item['day_bootstrap']['p75']} |",
                "",
                "| Date | P/L |",
                "| --- | ---: |",
            ]
        )
        for day in item["days"]:
            lines.append(f"| {day['date']} | {day['pnl']} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap confidence audit for trade diagnostics reports.")
    parser.add_argument("--diagnostics", action="append", required=True, help="diagnostic.json or diagnostic.json::label")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260618)
    parser.add_argument("--include-portfolio", action="store_true")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    iterations = max(100, args.iterations)
    loaded = [load_diagnostics(*parse_spec(raw)) for raw in args.diagnostics]
    strategies = [
        summarize(
            item["label"],
            item["source"],
            item["candidate"],
            item["slippage_bps"],
            item["trade_pls"],
            item["day_pls"],
            iterations,
            args.seed + index,
        )
        for index, item in enumerate(loaded)
    ]
    if args.include_portfolio and len(loaded) > 1:
        portfolio_trade_pls: list[Decimal] = []
        portfolio_day_pls: dict[str, Decimal] = defaultdict(Decimal)
        for item in loaded:
            portfolio_trade_pls.extend(item["trade_pls"])
            for date, pnl in item["day_pls"].items():
                portfolio_day_pls[date] += pnl
        strategies.append(
            summarize(
                "combined aggressive portfolio",
                ", ".join(item["source"] for item in loaded),
                ", ".join(sorted({item["candidate"] for item in loaded})),
                loaded[0]["slippage_bps"],
                portfolio_trade_pls,
                dict(portfolio_day_pls),
                iterations,
                args.seed + len(loaded),
            )
        )

    report = {
        "iterations": iterations,
        "seed": args.seed,
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
            f"{item['name']}: pnl={item['observed_total_pnl']} exits={item['trade_count']} "
            f"trade_p+={item['trade_bootstrap']['positive_probability']}% "
            f"day_p+={item['day_bootstrap']['positive_probability']}% "
            f"decision={item['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
