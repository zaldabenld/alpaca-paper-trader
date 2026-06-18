from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


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


def candidate_name(row: dict[str, Any]) -> str:
    candidate = row.get("candidate")
    if isinstance(candidate, dict):
        return str(candidate.get("name") or "")
    return str(candidate or "")


def fold_label(row: dict[str, Any]) -> str:
    return f"{row.get('positive_fold_count', 0)}/{row.get('fold_count', 0)}"


def row_summary(row: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "name": candidate_name(row),
        "stable": bool(row.get("stable")),
        "total_pnl": str(row.get("total_pnl", "0")),
        "total_buys": int(row.get("total_buys") or 0),
        "positive_folds": fold_label(row),
        "active_folds": f"{row.get('active_fold_count', 0)}/{row.get('fold_count', 0)}",
        "worst_fold_pnl": str(row.get("worst_fold_pnl", "0")),
        "worst_drawdown_percent": str(row.get("worst_drawdown_percent", "0")),
        "min_profit_factor": str(row.get("min_profit_factor", "n/a")),
    }


def status_for(target: dict[str, Any] | None, stable_count: int) -> str:
    if target is None:
        return "target missing"
    if not target["stable"]:
        return "target fails"
    if stable_count <= 1:
        return "lonely survivor"
    return "family support"


def audit_report(spec: str) -> dict[str, Any]:
    if "::" not in spec:
        raise SystemExit("--report must be formatted as report.json::target_candidate_name")
    path_text, target_name = spec.split("::", 1)
    path = Path(path_text)
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings") or {}
    buckets = []
    for bucket in report.get("buckets", []):
        rows_by_slippage = []
        for slippage_result in bucket.get("slippage_results", []):
            rows = slippage_result.get("top", [])
            summaries = [row_summary(row, rank) for rank, row in enumerate(rows, start=1)]
            target = next((item for item in summaries if item["name"] == target_name), None)
            stable = [item for item in summaries if item["stable"]]
            positive_all = [
                item
                for item in summaries
                if item["positive_folds"].split("/", 1)[0] == item["positive_folds"].split("/", 1)[-1]
            ]
            rows_by_slippage.append(
                {
                    "slippage_bps": str(slippage_result.get("slippage_bps")),
                    "candidate_count": int(bucket.get("candidate_count") or len(rows)),
                    "top_count": len(rows),
                    "stable_candidate_count": int(slippage_result.get("stable_candidate_count") or len(stable)),
                    "positive_all_fold_count": len(positive_all),
                    "status": status_for(target, int(slippage_result.get("stable_candidate_count") or len(stable))),
                    "target": target,
                    "stable_candidates": stable,
                    "top_candidates": summaries[:8],
                    "truncated": len(rows) < int(bucket.get("candidate_count") or len(rows)),
                }
            )
        buckets.append(
            {
                "bucket": str(bucket.get("label") or bucket.get("bucket") or ""),
                "candidate_count": int(bucket.get("candidate_count") or 0),
                "slippage_results": rows_by_slippage,
            }
        )
    return {
        "source": str(path),
        "target": target_name,
        "settings": {
            "price_source": settings.get("price_source"),
            "scan_interval_seconds": settings.get("scan_interval_seconds"),
            "candidate_mode": settings.get("candidate_mode"),
            "exit_mode": settings.get("exit_mode"),
            "slippage_bps": settings.get("slippage_bps"),
            "min_stop_hold_minutes": settings.get("min_stop_hold_minutes"),
            "entry_open_guard_minutes": settings.get("entry_open_guard_minutes"),
            "liquidate_on_close": settings.get("liquidate_on_close"),
            "candidate_list_size": len(settings.get("candidate_list") or []),
        },
        "buckets": buckets,
    }


def headline_status(item: dict[str, Any]) -> str:
    statuses = []
    min_stable: int | None = None
    target_stable = True
    for bucket in item["buckets"]:
        for result in bucket["slippage_results"]:
            statuses.append(result["status"])
            min_stable = (
                result["stable_candidate_count"]
                if min_stable is None
                else min(min_stable, result["stable_candidate_count"])
            )
            target = result.get("target")
            if not target or not target.get("stable"):
                target_stable = False
    if not target_stable:
        return "not robust"
    if min_stable is None or min_stable <= 0:
        return "not robust"
    if min_stable == 1:
        return "fragile pass"
    return "neighborhood support"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Neighborhood Audit",
        "",
        "Checks whether selected candidates are isolated parameter hits or have nearby family support in the simulator reports.",
        "",
        "## Summary",
        "",
        "| Source | Target | Mode | Stop grace | Candidate set | Status |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for item in report["reports"]:
        settings = item["settings"]
        lines.append(
            f"| `{Path(item['source']).name}` | `{item['target']}` | "
            f"{settings.get('candidate_mode')}/{settings.get('exit_mode')} | "
            f"{settings.get('min_stop_hold_minutes', 'n/a')} | "
            f"{settings.get('candidate_list_size', 'n/a')} | {headline_status(item)} |"
        )
    lines.extend(["", "## Detail", ""])
    for item in report["reports"]:
        settings = item["settings"]
        lines.extend(
            [
                f"### `{Path(item['source']).name}`",
                "",
                f"Target: `{item['target']}`",
                "",
                (
                    f"Settings: price `{settings.get('price_source')}`, scan `{settings.get('scan_interval_seconds')}` sec, "
                    f"mode `{settings.get('candidate_mode')}`, exits `{settings.get('exit_mode')}`, "
                    f"stop grace `{settings.get('min_stop_hold_minutes')}`, close liquidation `{settings.get('liquidate_on_close')}`."
                ),
                "",
            ]
        )
        for bucket in item["buckets"]:
            lines.extend(
                [
                    f"Bucket: `{bucket['bucket']}`",
                    "",
                    "| Slippage | Stable | Positive all folds | Target rank | Target P/L | Target folds | Status |",
                    "| ---: | ---: | ---: | ---: | ---: | ---: | --- |",
                ]
            )
            for result in bucket["slippage_results"]:
                target = result.get("target") or {}
                target_rank = target.get("rank", "n/a")
                target_pnl = target.get("total_pnl", "n/a")
                target_folds = target.get("positive_folds", "n/a")
                lines.append(
                    f"| {result['slippage_bps']} | {result['stable_candidate_count']}/{result['candidate_count']} | "
                    f"{result['positive_all_fold_count']}/{result['candidate_count']} | {target_rank} | "
                    f"{target_pnl} | {target_folds} | {result['status']} |"
                )
            lines.append("")
            for result in bucket["slippage_results"]:
                stable = result["stable_candidates"]
                if not stable:
                    continue
                lines.extend([f"Stable candidates at `{result['slippage_bps']}` bps:", ""])
                for stable_row in stable:
                    lines.append(
                        f"- `#{stable_row['rank']} {stable_row['name']}`: P/L `{stable_row['total_pnl']}`, "
                        f"buys `{stable_row['total_buys']}`, folds `{stable_row['positive_folds']}`, "
                        f"min PF `{stable_row['min_profit_factor']}`"
                    )
                lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit whether selected strategy candidates have nearby family support.")
    parser.add_argument("--report", action="append", required=True, help="cross-validation report.json::target_candidate")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    payload = {"reports": [audit_report(spec) for spec in args.report]}
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(payload), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for item in payload["reports"]:
        print(f"{Path(item['source']).name}: {headline_status(item)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
