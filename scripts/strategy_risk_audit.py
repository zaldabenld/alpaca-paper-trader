from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")


def dec(value: Any, *, inf_value: Decimal | None = None) -> Decimal:
    if value in (None, ""):
        return ZERO
    if value == "inf":
        return inf_value if inf_value is not None else Decimal("999999")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal, places: str = "0.0001") -> str:
    return format(value.quantize(Decimal(places)), "f")


def fmt_optional(value: Decimal | None, places: str = "0.0001") -> str:
    if value is None:
        return "n/a"
    return fmt(value, places)


def candidate_name(row: dict[str, Any]) -> str:
    candidate = row.get("candidate")
    if isinstance(candidate, dict):
        return str(candidate.get("name") or "")
    return str(candidate or "")


def load_candidate_matches(spec: str) -> list[dict[str, Any]]:
    if "::" not in spec:
        raise SystemExit("--candidate-report must be formatted as report.json::candidate_name")
    path_text, wanted_name = spec.split("::", 1)
    path = Path(path_text)
    report = json.loads(path.read_text(encoding="utf-8"))
    matches: list[dict[str, Any]] = []
    for bucket in report.get("buckets", []):
        bucket_label = str(bucket.get("label") or bucket.get("bucket") or "")
        for slippage_result in bucket.get("slippage_results", []):
            for row in slippage_result.get("top", []):
                if candidate_name(row) != wanted_name:
                    continue
                matches.append(
                    {
                        "kind": "candidate",
                        "source": str(path),
                        "name": wanted_name,
                        "bucket": bucket_label,
                        "slippage_bps": str(row.get("slippage_bps") or slippage_result.get("slippage_bps")),
                        "row": row,
                    }
                )
    if not matches:
        raise SystemExit(f"Candidate {wanted_name!r} not found in {path}")
    return matches


def load_portfolio_results(path: Path) -> list[dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    name = "portfolio: " + ", ".join(item.get("candidate_name", "") for item in report.get("candidates", []))
    return [
        {
            "kind": "portfolio",
            "source": str(path),
            "name": name,
            "bucket": "combined",
            "slippage_bps": str(row.get("slippage_bps")),
            "row": row,
        }
        for row in report.get("slippage_results", [])
        if row.get("status") == "ok"
    ]


def group_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["kind"], row["source"], row["name"], row["bucket"])].append(row)
    return [
        {"kind": kind, "source": source, "name": name, "bucket": bucket, "matches": sorted(matches, key=slippage)}
        for (kind, source, name, bucket), matches in sorted(grouped.items())
    ]


def slippage(match: dict[str, Any]) -> Decimal:
    return dec(match.get("slippage_bps"))


def bucket_alias(bucket: str) -> str:
    text = str(bucket or "")
    if text == "combined":
        return "combined"
    pieces = []
    for key in ("profile", "max_trade", "max_positions"):
        marker = f"{key}="
        if marker not in text:
            continue
        value = text.split(marker, 1)[1].split(",", 1)[0].strip()
        if key == "max_positions":
            pieces.append(f"max{value}")
        elif key == "max_trade":
            pieces.append(f"${value}")
        else:
            pieces.append(value)
    return " ".join(pieces) if pieces else text


def display_name(strategy: dict[str, Any]) -> str:
    if strategy["kind"] == "portfolio":
        return strategy["name"]
    alias = bucket_alias(strategy["bucket"])
    return f"{alias}: {strategy['name']}" if alias else strategy["name"]


def fold_metrics(row: dict[str, Any]) -> list[dict[str, Any]]:
    folds = []
    for fold in row.get("folds", []):
        metrics = fold.get("metrics") or fold
        if not metrics:
            continue
        folds.append(
            {
                "date": str(fold.get("date") or metrics.get("date") or ""),
                "pnl": dec(metrics.get("pnl")),
                "pnl_percent": dec(metrics.get("pnl_percent")),
                "starting_equity": dec(metrics.get("starting_equity")),
                "max_drawdown": dec(metrics.get("max_drawdown")),
                "drawdown_percent": dec(metrics.get("drawdown_percent")),
                "buys": int(metrics.get("buys") or 0),
                "exits": int(metrics.get("exits") or 0),
                "gross_profit": dec(metrics.get("gross_profit")),
                "gross_loss": dec(metrics.get("gross_loss")),
                "profit_factor": dec(metrics.get("profit_factor"), inf_value=Decimal("999999")),
                "positive": dec(metrics.get("pnl")) > ZERO,
            }
        )
    return folds


def sample_std(values: list[Decimal]) -> Decimal:
    if len(values) < 2:
        return ZERO
    return Decimal(str(statistics.stdev(float(item) for item in values)))


def row_summary(match: dict[str, Any]) -> dict[str, Any]:
    row = match["row"]
    folds = fold_metrics(row)
    fold_pnls = [item["pnl"] for item in folds]
    total_pnl = dec(row.get("total_pnl")) if row.get("total_pnl") is not None else sum(fold_pnls, ZERO)
    total_buys = int(row.get("total_buys") or sum(item["buys"] for item in folds))
    total_exits = int(row.get("total_exits") or sum(item["exits"] for item in folds))
    fold_count = int(row.get("fold_count") or len(folds))
    positive_fold_count = int(row.get("positive_fold_count") or sum(1 for item in folds if item["positive"]))
    active_fold_count = int(row.get("active_fold_count") or sum(1 for item in folds if item["buys"] > 0))
    worst_fold_pnl = dec(row.get("worst_fold_pnl")) if row.get("worst_fold_pnl") is not None else min(fold_pnls, default=ZERO)
    max_drawdown = (
        dec(row.get("max_drawdown"))
        if row.get("max_drawdown") is not None
        else sum((item["max_drawdown"] for item in folds), ZERO)
    )
    worst_drawdown_percent = (
        dec(row.get("worst_drawdown_percent"))
        if row.get("worst_drawdown_percent") is not None
        else max((item["drawdown_percent"] for item in folds), default=ZERO)
    )
    mean_pnl = total_pnl / Decimal(fold_count) if fold_count else ZERO
    std_pnl = sample_std(fold_pnls)
    t_stat = mean_pnl / (std_pnl / Decimal(str(math.sqrt(fold_count)))) if fold_count > 1 and std_pnl > ZERO else None
    expectancy = total_pnl / Decimal(total_buys) if total_buys else ZERO
    pnl_to_drawdown = total_pnl / max_drawdown if max_drawdown > ZERO else None
    gross_profit = sum((item["gross_profit"] for item in folds), ZERO)
    gross_loss = sum((item["gross_loss"] for item in folds), ZERO)
    profit_factor = None
    if gross_loss < ZERO:
        profit_factor = gross_profit / abs(gross_loss)
    elif gross_profit > ZERO:
        profit_factor = Decimal("999999")
    elif row.get("min_profit_factor"):
        profit_factor = dec(row.get("min_profit_factor"), inf_value=Decimal("999999"))
    stable = bool(row.get("stable")) or (
        total_pnl > ZERO and fold_count > 0 and positive_fold_count == fold_count and active_fold_count == fold_count
    )
    return {
        "slippage_bps": fmt(slippage(match)),
        "stable": stable,
        "fold_count": fold_count,
        "positive_fold_count": positive_fold_count,
        "active_fold_count": active_fold_count,
        "total_pnl": fmt(total_pnl),
        "total_buys": total_buys,
        "total_exits": total_exits,
        "worst_fold_pnl": fmt(worst_fold_pnl),
        "worst_drawdown_percent": fmt(worst_drawdown_percent),
        "mean_fold_pnl": fmt(mean_pnl),
        "fold_pnl_stddev": fmt(std_pnl),
        "fold_t_stat": fmt_optional(t_stat),
        "expectancy_per_buy": fmt(expectancy),
        "profit_factor": "inf" if profit_factor and profit_factor >= Decimal("999998") else fmt_optional(profit_factor),
        "pnl_to_drawdown": fmt_optional(pnl_to_drawdown),
        "folds": [
            {
                "date": item["date"],
                "pnl": fmt(item["pnl"]),
                "buys": item["buys"],
                "exits": item["exits"],
                "drawdown_percent": fmt(item["drawdown_percent"]),
            }
            for item in folds
        ],
        "_pnl_decimal": total_pnl,
    }


def break_even_slippage(summaries: list[dict[str, Any]]) -> str:
    points = [(dec(item["slippage_bps"]), item["_pnl_decimal"]) for item in summaries]
    points.sort(key=lambda item: item[0])
    if not points:
        return "n/a"
    if all(pnl > ZERO for _, pnl in points):
        return f">= {fmt(points[-1][0])}"
    if all(pnl <= ZERO for _, pnl in points):
        return f"<= {fmt(points[0][0])}"
    for (left_bps, left_pnl), (right_bps, right_pnl) in zip(points, points[1:]):
        if left_pnl == ZERO:
            return fmt(left_bps)
        if (left_pnl > ZERO and right_pnl <= ZERO) or (left_pnl <= ZERO and right_pnl > ZERO):
            span = right_bps - left_bps
            pnl_span = right_pnl - left_pnl
            if pnl_span == ZERO:
                return fmt(left_bps)
            estimate = left_bps + (ZERO - left_pnl) * span / pnl_span
            return fmt(estimate)
    return "n/a"


def passing_slippage(summaries: list[dict[str, Any]]) -> str:
    passing = [dec(item["slippage_bps"]) for item in summaries if item["stable"] and item["_pnl_decimal"] > ZERO]
    return fmt(max(passing)) if passing else "none"


def target_summary(summaries: list[dict[str, Any]], target: Decimal) -> dict[str, Any] | None:
    exact = [item for item in summaries if dec(item["slippage_bps"]) == target]
    if exact:
        return exact[0]
    if not summaries:
        return None
    return min(summaries, key=lambda item: abs(dec(item["slippage_bps"]) - target))


def evidence_flags(summary: dict[str, Any] | None, target: Decimal, max_observed: str, break_even: str) -> list[str]:
    if summary is None:
        return ["missing target slippage result"]
    flags = []
    fold_count = int(summary["fold_count"])
    total_buys = int(summary["total_buys"])
    if fold_count < 5:
        flags.append(f"thin day sample ({fold_count} folds)")
    if total_buys < 20:
        flags.append(f"thin trade sample ({total_buys} buys)")
    if summary["positive_fold_count"] != summary["fold_count"]:
        flags.append("not positive in every fold")
    if not summary["stable"]:
        flags.append("fails current fold gates")
    if summary["_pnl_decimal"] <= ZERO:
        flags.append("non-positive target P/L")
    if max_observed != "none" and dec(max_observed) <= target:
        flags.append("no slippage cushion above target")
    if break_even.startswith("<= "):
        flags.append("break-even cost is below tested range")
    return flags


def audit_strategy(strategy: dict[str, Any], target: Decimal) -> dict[str, Any]:
    summaries = [row_summary(match) for match in strategy["matches"]]
    summaries.sort(key=lambda item: dec(item["slippage_bps"]))
    max_pass = passing_slippage(summaries)
    breakeven = break_even_slippage(summaries)
    target_row = target_summary(summaries, target)
    flags = evidence_flags(target_row, target, max_pass, breakeven)
    if target_row and target_row["stable"] and target_row["_pnl_decimal"] > ZERO and target_row["positive_fold_count"] == target_row["fold_count"]:
        decision = "paper-test candidate"
    else:
        decision = "research only"
    if flags:
        decision += "; evidence still provisional"
    payload_summaries = []
    for item in summaries:
        clean = dict(item)
        clean.pop("_pnl_decimal", None)
        payload_summaries.append(clean)
    return {
        "kind": strategy["kind"],
        "name": strategy["name"],
        "display_name": display_name(strategy),
        "source": strategy["source"],
        "bucket": strategy["bucket"],
        "target_slippage_bps": fmt(target),
        "decision": decision,
        "highest_passing_slippage_bps": max_pass,
        "estimated_break_even_slippage_bps": breakeven,
        "evidence_flags": flags,
        "target_result": {k: v for k, v in target_row.items() if k != "_pnl_decimal"} if target_row else None,
        "slippage_results": payload_summaries,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Risk Audit",
        "",
        "Risk-adjusted audit generated from offline replay cross-validation outputs.",
        "",
        "Method: rank candidates by target-slippage profitability, fold consistency, drawdown, per-buy expectancy, and survival across higher slippage. The evidence flag is intentionally conservative because repeated parameter searches inflate backtest optimism.",
        "",
        "Reference: Bailey and Lopez de Prado's Deflated Sharpe Ratio paper documents why multiple backtests can create inflated apparent performance and why selected strategies need extra skepticism: https://ssrn.com/abstract=2460551",
        "",
        "## Summary",
        "",
        "| Strategy | Target P/L | Buys | Folds + | Worst fold | Max DD | Expectancy/buy | P/L:DD | Pass bps | Break-even bps | Decision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["strategies"]:
        target = item.get("target_result") or {}
        lines.append(
            f"| `{item['display_name']}` | {target.get('total_pnl', 'n/a')} | {target.get('total_buys', 'n/a')} | "
            f"{target.get('positive_fold_count', 'n/a')}/{target.get('fold_count', 'n/a')} | "
            f"{target.get('worst_fold_pnl', 'n/a')} | {target.get('worst_drawdown_percent', 'n/a')}% | "
            f"{target.get('expectancy_per_buy', 'n/a')} | {target.get('pnl_to_drawdown', 'n/a')} | "
            f"{item['highest_passing_slippage_bps']} | {item['estimated_break_even_slippage_bps']} | {item['decision']} |"
        )
    lines.extend(["", "## Evidence Flags", ""])
    for item in report["strategies"]:
        lines.append(f"### `{item['display_name']}`")
        if item["evidence_flags"]:
            for flag in item["evidence_flags"]:
                lines.append(f"- {flag}")
        else:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Slippage Detail", ""])
    for item in report["strategies"]:
        lines.extend(
            [
                f"### `{item['display_name']}`",
                "",
                f"Source: `{item['source']}`",
                "",
                f"Bucket: `{item['bucket']}`",
                "",
                "| Slippage | P/L | Buys | Positive folds | Worst fold | Max DD | Mean fold | Fold stddev | t-stat | PF | P/L:DD |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in item["slippage_results"]:
            lines.append(
                f"| {row['slippage_bps']} | {row['total_pnl']} | {row['total_buys']} | "
                f"{row['positive_fold_count']}/{row['fold_count']} | {row['worst_fold_pnl']} | "
                f"{row['worst_drawdown_percent']}% | {row['mean_fold_pnl']} | {row['fold_pnl_stddev']} | "
                f"{row['fold_t_stat']} | {row['profit_factor']} | {row['pnl_to_drawdown']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a risk-adjusted audit from day-tape replay reports.")
    parser.add_argument("--candidate-report", action="append", default=[], help="report.json::candidate_name")
    parser.add_argument("--portfolio-report", action="append", type=Path, default=[])
    parser.add_argument("--target-slippage-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    matches: list[dict[str, Any]] = []
    for spec in args.candidate_report:
        matches.extend(load_candidate_matches(spec))
    for path in args.portfolio_report:
        matches.extend(load_portfolio_results(path))
    if not matches:
        raise SystemExit("No candidate or portfolio reports supplied.")

    report = {
        "target_slippage_bps": fmt(max(ZERO, args.target_slippage_bps)),
        "strategies": [
            audit_strategy(strategy, max(ZERO, args.target_slippage_bps))
            for strategy in group_results(matches)
        ],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for item in report["strategies"]:
        target = item.get("target_result") or {}
        print(
            f"{item['display_name']}: target_pnl={target.get('total_pnl', 'n/a')} "
            f"buys={target.get('total_buys', 'n/a')} pass_bps={item['highest_passing_slippage_bps']} "
            f"break_even={item['estimated_break_even_slippage_bps']} decision={item['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
