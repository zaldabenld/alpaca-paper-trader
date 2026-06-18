from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")
ONE = Decimal("1")


REFERENCE_LINKS = [
    {
        "label": "Deflated Sharpe Ratio",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551",
        "note": "Selection bias, non-normal returns, and multiple testing can inflate apparent backtest performance.",
    },
    {
        "label": "Probability of Backtest Overfitting",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253",
        "note": "Investment simulations need cross-validation and explicit overfitting skepticism.",
    },
]


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


def parse_report_spec(raw: str) -> tuple[Path, str | None]:
    if "::" not in raw:
        return Path(raw), None
    path_text, label = raw.split("::", 1)
    return Path(path_text), label.strip() or None


def candidate_name(row: dict[str, Any]) -> str:
    candidate = row.get("candidate")
    if isinstance(candidate, dict):
        return str(candidate.get("name") or "")
    return str(candidate or "")


def bucket_alias(label: str) -> str:
    pieces = []
    for key in ("profile", "max_trade", "max_positions"):
        marker = f"{key}="
        if marker not in label:
            continue
        value = label.split(marker, 1)[1].split(",", 1)[0].strip()
        if key == "max_positions":
            pieces.append(f"max{value}")
        elif key == "max_trade":
            pieces.append(f"${value}")
        else:
            pieces.append(value)
    return " ".join(pieces) if pieces else label


def collect_rows(path: Path, source_label: str | None) -> list[dict[str, Any]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for bucket in report.get("buckets", []):
        bucket_label = str(bucket.get("label") or bucket.get("bucket") or "")
        label = source_label or bucket_alias(bucket_label)
        for slippage_result in bucket.get("slippage_results", []):
            slippage = dec(slippage_result.get("slippage_bps"))
            for row in slippage_result.get("top", []):
                name = candidate_name(row)
                if not name:
                    continue
                rows.append(
                    {
                        "source": str(path),
                        "source_label": label,
                        "bucket": bucket_label,
                        "candidate_name": name,
                        "slippage_bps": slippage,
                        "row": row,
                    }
                )
    return rows


def row_metric(row: dict[str, Any], key: str) -> Decimal:
    return dec(row.get(key), inf_value=Decimal("999999"))


def row_int(row: dict[str, Any], key: str) -> int:
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def exact_or_closest(rows: list[dict[str, Any]], target: Decimal) -> dict[str, Any] | None:
    exact = [item for item in rows if item["slippage_bps"] == target]
    if exact:
        return exact[0]
    if not rows:
        return None
    return min(rows, key=lambda item: abs(item["slippage_bps"] - target))


def highest_passing_slippage(rows: list[dict[str, Any]]) -> Decimal:
    passing = [
        item["slippage_bps"]
        for item in rows
        if bool(item["row"].get("stable")) and row_metric(item["row"], "total_pnl") > ZERO
    ]
    return max(passing) if passing else ZERO


def evidence_flags(target_row: dict[str, Any] | None, highest_pass: Decimal, target: Decimal, min_days: int, min_buys: int) -> list[str]:
    if target_row is None:
        return ["missing target slippage row"]
    row = target_row["row"]
    flags = []
    fold_count = row_int(row, "fold_count")
    buys = row_int(row, "total_buys")
    positive_folds = row_int(row, "positive_fold_count")
    active_folds = row_int(row, "active_fold_count")
    pnl = row_metric(row, "total_pnl")
    if not row.get("stable"):
        flags.append("target row fails fold gates")
    if pnl <= ZERO:
        flags.append("target P/L is non-positive")
    if fold_count and positive_folds < fold_count:
        flags.append(f"positive folds {positive_folds}/{fold_count}")
    if fold_count and active_folds < fold_count:
        flags.append(f"active folds {active_folds}/{fold_count}")
    if fold_count < min_days:
        flags.append(f"thin day sample ({fold_count} folds < {min_days})")
    if buys < min_buys:
        flags.append(f"thin trade sample ({buys} buys < {min_buys})")
    if highest_pass <= target:
        flags.append("no passing slippage cushion above target")
    if row_metric(row, "worst_fold_pnl") <= ZERO:
        flags.append("worst fold is non-positive")
    return flags


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= ZERO:
        return ZERO
    return numerator / denominator


def capped_ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= ZERO:
        return ONE
    return min(ONE, max(ZERO, numerator / denominator))


def score_candidate(
    key: tuple[str, str, str, str],
    rows: list[dict[str, Any]],
    target: Decimal,
    min_days: Decimal,
    min_buys: Decimal,
) -> dict[str, Any]:
    rows = sorted(rows, key=lambda item: item["slippage_bps"])
    target_row = exact_or_closest(rows, target)
    highest_pass = highest_passing_slippage(rows)
    flags = evidence_flags(target_row, highest_pass, target, int(min_days), int(min_buys))
    if target_row is None:
        return {
            "source": key[0],
            "source_label": key[1],
            "bucket": key[2],
            "candidate_name": key[3],
            "risk_adjusted_score": "0.0000",
            "score_components": {},
            "evidence_flags": flags,
            "slippage_results": [],
        }

    row = target_row["row"]
    pnl = max(ZERO, row_metric(row, "total_pnl"))
    fold_count = Decimal(row_int(row, "fold_count"))
    positive_folds = Decimal(row_int(row, "positive_fold_count"))
    active_folds = Decimal(row_int(row, "active_fold_count"))
    passed_folds = Decimal(row_int(row, "passed_fold_count"))
    buys = Decimal(row_int(row, "total_buys"))
    pf = min(dec(row.get("min_profit_factor"), inf_value=Decimal("10")), Decimal("10"))
    drawdown_percent = max(ZERO, row_metric(row, "worst_drawdown_percent"))
    slippage_cushion = max(ZERO, highest_pass - target)

    consistency = ratio(positive_folds, fold_count) * ratio(active_folds, fold_count) * ratio(passed_folds, fold_count)
    sample_factor = capped_ratio(fold_count, min_days) * capped_ratio(buys, min_buys)
    slippage_factor = ONE + ratio(slippage_cushion, max(target, ONE))
    pf_factor = ratio(pf, Decimal("10"))
    drawdown_factor = ONE / (ONE + drawdown_percent)
    gate_factor = ONE if bool(row.get("stable")) and pnl > ZERO else ZERO
    score = pnl * consistency * sample_factor * slippage_factor * pf_factor * drawdown_factor * gate_factor

    return {
        "source": key[0],
        "source_label": key[1],
        "bucket": key[2],
        "candidate_name": key[3],
        "target_slippage_bps": fmt(target),
        "risk_adjusted_score": fmt(score),
        "rank_tuple": [
            bool(row.get("stable")),
            fmt(score),
            fmt(highest_pass),
            fmt(pnl),
            row_int(row, "positive_fold_count"),
            row_int(row, "active_fold_count"),
            fmt(pf),
            fmt(-drawdown_percent),
            row_int(row, "total_buys"),
        ],
        "target_result": {
            "slippage_bps": fmt(target_row["slippage_bps"]),
            "stable": bool(row.get("stable")),
            "total_pnl": fmt(row_metric(row, "total_pnl")),
            "total_buys": row_int(row, "total_buys"),
            "total_exits": row_int(row, "total_exits"),
            "fold_count": row_int(row, "fold_count"),
            "passed_fold_count": row_int(row, "passed_fold_count"),
            "positive_fold_count": row_int(row, "positive_fold_count"),
            "active_fold_count": row_int(row, "active_fold_count"),
            "worst_fold_pnl": fmt(row_metric(row, "worst_fold_pnl")),
            "worst_drawdown_percent": fmt(drawdown_percent),
            "min_profit_factor": "inf" if dec(row.get("min_profit_factor"), inf_value=Decimal("999999")) >= Decimal("999998") else fmt(dec(row.get("min_profit_factor"), inf_value=Decimal("999999"))),
        },
        "score_components": {
            "pnl_component": fmt(pnl),
            "consistency_factor": fmt(consistency),
            "sample_factor": fmt(sample_factor),
            "slippage_factor": fmt(slippage_factor),
            "profit_factor_component": fmt(pf_factor),
            "drawdown_factor": fmt(drawdown_factor),
            "gate_factor": fmt(gate_factor),
            "highest_passing_slippage_bps": fmt(highest_pass),
            "slippage_cushion_bps": fmt(slippage_cushion),
        },
        "evidence_flags": flags,
        "slippage_results": [
            {
                "slippage_bps": fmt(item["slippage_bps"]),
                "stable": bool(item["row"].get("stable")),
                "total_pnl": fmt(row_metric(item["row"], "total_pnl")),
                "total_buys": row_int(item["row"], "total_buys"),
                "positive_fold_count": row_int(item["row"], "positive_fold_count"),
                "active_fold_count": row_int(item["row"], "active_fold_count"),
                "fold_count": row_int(item["row"], "fold_count"),
                "worst_fold_pnl": fmt(row_metric(item["row"], "worst_fold_pnl")),
                "worst_drawdown_percent": fmt(row_metric(item["row"], "worst_drawdown_percent")),
                "min_profit_factor": str(item["row"].get("min_profit_factor") or "0"),
            }
            for item in rows
        ],
    }


def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    target = item.get("target_result") or {}
    return (
        bool(target.get("stable")),
        dec(item.get("risk_adjusted_score")),
        dec((item.get("score_components") or {}).get("highest_passing_slippage_bps")),
        dec(target.get("total_pnl")),
        int(target.get("positive_fold_count") or 0),
        int(target.get("active_fold_count") or 0),
        dec(target.get("min_profit_factor"), inf_value=Decimal("999999")),
        -dec(target.get("worst_drawdown_percent")),
        int(target.get("total_buys") or 0),
    )


def build_scorecard(reports: list[str], target: Decimal, min_days: int, min_buys: int) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in reports:
        path, label = parse_report_spec(raw)
        for item in collect_rows(path, label):
            key = (item["source"], item["source_label"], item["bucket"], item["candidate_name"])
            grouped[key].append(item)
    candidates = [
        score_candidate(key, rows, target, Decimal(min_days), Decimal(min_buys))
        for key, rows in grouped.items()
    ]
    candidates.sort(key=rank_key, reverse=True)
    return {
        "target_slippage_bps": fmt(target),
        "min_days_for_full_credit": min_days,
        "min_buys_for_full_credit": min_buys,
        "method": {
            "formula": "target_pnl * consistency * sample_factor * slippage_factor * profit_factor_component * drawdown_factor * gate_factor",
            "consistency": "positive_fold_ratio * active_fold_ratio * passed_fold_ratio",
            "sample_factor": "min(1, fold_count/min_days) * min(1, total_buys/min_buys)",
            "slippage_factor": "1 + max(0, highest_passing_slippage_bps - target_bps) / max(target_bps, 1)",
            "profit_factor_component": "min(min_profit_factor, 10) / 10",
            "drawdown_factor": "1 / (1 + worst_drawdown_percent)",
            "gate_factor": "1 only when the target row is stable and profitable, otherwise 0",
            "note": "This score ranks simulator evidence. It is not a trading parameter and should not override hard promotion gates.",
        },
        "references": REFERENCE_LINKS,
        "candidates": candidates,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Candidate Scorecard",
        "",
        "Risk-adjusted ranking for simulator candidates. This scorecard is meant to reduce cherry-picking after many replay tests; it does not prove future profitability.",
        "",
        f"Target slippage: `{report['target_slippage_bps']}` bps",
        f"Full sample credit: `{report['min_days_for_full_credit']}` days and `{report['min_buys_for_full_credit']}` buys",
        "",
        "Method:",
        f"- `{report['method']['formula']}`",
        f"- Consistency: {report['method']['consistency']}",
        f"- Sample factor: {report['method']['sample_factor']}",
        f"- Slippage factor: {report['method']['slippage_factor']}",
        f"- Profit-factor component: {report['method']['profit_factor_component']}",
        f"- Drawdown factor: {report['method']['drawdown_factor']}",
        f"- Gate factor: {report['method']['gate_factor']}",
        "",
        "References:",
    ]
    for ref in report["references"]:
        lines.append(f"- [{ref['label']}]({ref['url']}): {ref['note']}")
    lines.extend(
        [
            "",
            "## Ranking",
            "",
            "| Rank | Label | Candidate | Score | Target P/L | Buys | Folds + | Pass bps | Worst fold | DD | PF | Flags |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for index, item in enumerate(report["candidates"], start=1):
        target = item.get("target_result") or {}
        components = item.get("score_components") or {}
        flags = "; ".join(item.get("evidence_flags") or []) or "none"
        lines.append(
            f"| {index} | `{item['source_label']}` | `{item['candidate_name']}` | {item['risk_adjusted_score']} | "
            f"{target.get('total_pnl', 'n/a')} | {target.get('total_buys', 'n/a')} | "
            f"{target.get('positive_fold_count', 'n/a')}/{target.get('fold_count', 'n/a')} | "
            f"{components.get('highest_passing_slippage_bps', 'n/a')} | {target.get('worst_fold_pnl', 'n/a')} | "
            f"{target.get('worst_drawdown_percent', 'n/a')}% | {target.get('min_profit_factor', 'n/a')} | {flags} |"
        )
    lines.extend(["", "## Component Detail", ""])
    for item in report["candidates"]:
        lines.extend(
            [
                f"### `{item['source_label']}`",
                "",
                f"Candidate: `{item['candidate_name']}`",
                "",
                "| Component | Value |",
                "| --- | ---: |",
            ]
        )
        for key, value in (item.get("score_components") or {}).items():
            lines.append(f"| `{key}` | {value} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank cross-validation candidates with a risk-adjusted simulator score.")
    parser.add_argument("--report", action="append", required=True, help="cross-validation report JSON, optionally report.json::label")
    parser.add_argument("--target-slippage-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--min-days", type=int, default=5, help="Fold count needed for full sample credit.")
    parser.add_argument("--min-buys", type=int, default=20, help="Buy count needed for full sample credit.")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    report = build_scorecard(
        args.report,
        max(ZERO, args.target_slippage_bps),
        max(1, args.min_days),
        max(1, args.min_buys),
    )
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON scorecard: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown scorecard: {args.markdown_output}")
    for index, item in enumerate(report["candidates"][:10], start=1):
        target = item.get("target_result") or {}
        print(
            f"#{index} {item['source_label']} {item['candidate_name']} "
            f"score={item['risk_adjusted_score']} pnl={target.get('total_pnl', 'n/a')} "
            f"buys={target.get('total_buys', 'n/a')} flags={len(item.get('evidence_flags') or [])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
