from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    if value in (None, "", "inf"):
        return Decimal("99") if value == "inf" else ZERO
    return Decimal(str(value))


def load_candidate(report_path: Path, candidate_name: str) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    matches: list[dict[str, Any]] = []
    for bucket in report.get("buckets", []):
        for slippage_result in bucket.get("slippage_results", []):
            for row in slippage_result.get("top", []):
                candidate = row.get("candidate") or {}
                if candidate.get("name") == candidate_name:
                    matches.append(
                        {
                            "source": str(report_path),
                            "bucket": bucket.get("label", ""),
                            "slippage_bps": str(slippage_result.get("slippage_bps")),
                            "candidate": candidate,
                            "row": row,
                        }
                    )
    if not matches:
        raise SystemExit(f"Candidate {candidate_name!r} not found in {report_path}")
    return {"source": str(report_path), "candidate_name": candidate_name, "matches": matches}


def fold_metrics(match: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for fold in match["row"].get("folds", []):
        metrics = fold.get("metrics") or {}
        date = str(fold.get("date") or fold.get("file") or "")
        by_date[date] = metrics
    return by_date


def aggregate_slippage(matches: list[dict[str, Any]], slippage_bps: str) -> dict[str, Any]:
    wanted = dec(slippage_bps)
    selected = [match for match in matches if dec(match["slippage_bps"]) == wanted]
    if not selected:
        return {"slippage_bps": slippage_bps, "status": "missing"}
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_pnl = ZERO
    total_buys = 0
    total_exits = 0
    total_starting_equity = ZERO
    max_drawdown = ZERO
    for match in selected:
        for date, metrics in fold_metrics(match).items():
            by_date[date].append(metrics)
            total_pnl += dec(metrics.get("pnl"))
            total_buys += int(metrics.get("buys") or 0)
            total_exits += int(metrics.get("exits") or 0)
            total_starting_equity += dec(metrics.get("starting_equity"))
            max_drawdown += dec(metrics.get("max_drawdown"))

    fold_rows: list[dict[str, Any]] = []
    for date in sorted(by_date):
        metrics_list = by_date[date]
        pnl = sum((dec(item.get("pnl")) for item in metrics_list), ZERO)
        buys = sum(int(item.get("buys") or 0) for item in metrics_list)
        exits = sum(int(item.get("exits") or 0) for item in metrics_list)
        starting_equity = sum((dec(item.get("starting_equity")) for item in metrics_list), ZERO)
        max_fold_drawdown = sum((dec(item.get("max_drawdown")) for item in metrics_list), ZERO)
        fold_rows.append(
            {
                "date": date,
                "pnl": format_decimal(pnl),
                "pnl_percent": format_decimal(pnl / starting_equity * Decimal("100") if starting_equity > ZERO else ZERO),
                "buys": buys,
                "exits": exits,
                "positive": pnl > ZERO,
                "max_drawdown": format_decimal(max_fold_drawdown),
                "drawdown_percent": format_decimal(
                    max_fold_drawdown / starting_equity * Decimal("100") if starting_equity > ZERO else ZERO
                ),
            }
        )
    positive_folds = sum(1 for item in fold_rows if item["positive"])
    return {
        "slippage_bps": slippage_bps,
        "status": "ok",
        "total_pnl": format_decimal(total_pnl),
        "total_pnl_percent": format_decimal(
            total_pnl / total_starting_equity * Decimal("100") if total_starting_equity > ZERO else ZERO
        ),
        "total_buys": total_buys,
        "total_exits": total_exits,
        "positive_fold_count": positive_folds,
        "fold_count": len(fold_rows),
        "max_drawdown": format_decimal(max_drawdown),
        "max_drawdown_percent": format_decimal(
            max_drawdown / total_starting_equity * Decimal("100") if total_starting_equity > ZERO else ZERO
        ),
        "folds": fold_rows,
    }


def format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Portfolio Candidate Summary",
        "",
        "Combined offline replay for the selected account-specific candidates.",
        "",
        "## Candidates",
        "",
    ]
    for item in report["candidates"]:
        lines.append(f"- `{item['candidate_name']}` from `{item['source']}`")
    lines.extend(
        [
            "",
            "## Combined Results",
            "",
            "| Slippage | Total P/L | Buys | Positive folds | Max DD | Status |",
            "| ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["slippage_results"]:
        if row["status"] != "ok":
            lines.append(f"| {row['slippage_bps']} | n/a | n/a | n/a | n/a | missing |")
            continue
        status = "passes aggregate fold sign" if row["positive_fold_count"] == row["fold_count"] else "has negative fold"
        lines.append(
            f"| {row['slippage_bps']} | {row['total_pnl']} | {row['total_buys']} | "
            f"{row['positive_fold_count']}/{row['fold_count']} | {row['max_drawdown_percent']}% | {status} |"
        )
    lines.extend(["", "## Fold Detail", ""])
    for row in report["slippage_results"]:
        if row["status"] != "ok":
            continue
        lines.extend(
            [
                f"### {row['slippage_bps']} bps",
                "",
                "| Date | P/L | Buys | Exits | DD |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for fold in row["folds"]:
            lines.append(
                f"| {fold['date']} | {fold['pnl']} | {fold['buys']} | {fold['exits']} | {fold['drawdown_percent']}% |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine selected candidate fold results into a portfolio summary.")
    parser.add_argument("--candidate-report", action="append", required=True, help="report.json::candidate_name")
    parser.add_argument("--slippage-bps-list", default="5.0000,10.0000")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    candidates = []
    all_matches = []
    for raw in args.candidate_report:
        if "::" not in raw:
            raise SystemExit("--candidate-report must be formatted as report.json::candidate_name")
        path_text, candidate_name = raw.split("::", 1)
        candidate = load_candidate(Path(path_text), candidate_name)
        candidates.append({"source": candidate["source"], "candidate_name": candidate_name})
        all_matches.extend(candidate["matches"])

    slippages = [item.strip() for item in args.slippage_bps_list.split(",") if item.strip()]
    report = {
        "candidates": candidates,
        "slippage_results": [aggregate_slippage(all_matches, slippage) for slippage in slippages],
    }

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for row in report["slippage_results"]:
        if row["status"] == "ok":
            print(
                f"{row['slippage_bps']} bps: pnl={row['total_pnl']} buys={row['total_buys']} "
                f"positive_folds={row['positive_fold_count']}/{row['fold_count']} "
                f"dd={row['max_drawdown_percent']}%"
            )
        else:
            print(f"{row['slippage_bps']} bps: {row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
