from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


@dataclass(frozen=True)
class AuditItem:
    label: str
    source: str
    kind: str
    family_tests: int
    target_slippage_bps: Decimal
    total_pnl: Decimal
    total_buys: int
    fold_pnls: list[Decimal]


def dec(value: Any) -> Decimal:
    if value in (None, ""):
        return ZERO
    if value == "inf":
        return Decimal("999999")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal, places: str = "0.0001") -> str:
    return format(value.quantize(Decimal(places)), "f")


def parse_spec(raw: str, expected_parts: int, help_text: str) -> list[str]:
    parts = [part.strip() for part in str(raw or "").split("::")]
    if len(parts) < expected_parts or not all(parts[:expected_parts]):
        raise SystemExit(help_text)
    return parts


def candidate_name(row: dict[str, Any]) -> str:
    candidate = row.get("candidate")
    if isinstance(candidate, dict):
        return str(candidate.get("name") or "")
    return str(candidate or "")


def fold_pnls_from_cv_row(row: dict[str, Any]) -> list[Decimal]:
    pnls: list[Decimal] = []
    for fold in row.get("folds", []):
        metrics = fold.get("metrics") or {}
        pnls.append(dec(metrics.get("pnl")))
    return pnls


def count_cv_family_tests(path: Path) -> int:
    report = json.loads(path.read_text(encoding="utf-8"))
    tests = 0
    for bucket in report.get("buckets", []):
        candidate_count = int(bucket.get("candidate_count") or 0)
        slippage_count = len(bucket.get("slippage_results", []))
        tests += max(1, candidate_count) * max(1, slippage_count)
    return max(1, tests)


def load_candidate_item(
    spec: str,
    target_slippage_bps: Decimal,
    default_family_tests: int | None,
) -> AuditItem:
    parts = parse_spec(
        spec,
        2,
        "--candidate-report must be formatted as report.json::candidate_name or report.json::candidate_name::label",
    )
    path = Path(parts[0])
    wanted_candidate = parts[1]
    label = parts[2] if len(parts) >= 3 and parts[2] else wanted_candidate
    report = json.loads(path.read_text(encoding="utf-8"))
    matches: list[dict[str, Any]] = []
    for bucket in report.get("buckets", []):
        for slippage_result in bucket.get("slippage_results", []):
            if dec(slippage_result.get("slippage_bps")) != target_slippage_bps:
                continue
            for row in slippage_result.get("top", []):
                if candidate_name(row) == wanted_candidate:
                    matches.append(row)
    if not matches:
        raise SystemExit(f"Candidate {wanted_candidate!r} at {target_slippage_bps} bps not found in {path}")
    if len(matches) > 1:
        # Multiple stitched buckets can appear in older reports. Aggregate them as one tested account row.
        total_pnl = sum((dec(row.get("total_pnl")) for row in matches), ZERO)
        total_buys = sum(int(row.get("total_buys") or 0) for row in matches)
        by_index: dict[int, Decimal] = {}
        for row in matches:
            for index, pnl in enumerate(fold_pnls_from_cv_row(row)):
                by_index[index] = by_index.get(index, ZERO) + pnl
        fold_pnls = [by_index[index] for index in sorted(by_index)]
    else:
        row = matches[0]
        total_pnl = dec(row.get("total_pnl"))
        total_buys = int(row.get("total_buys") or 0)
        fold_pnls = fold_pnls_from_cv_row(row)
    return AuditItem(
        label=label,
        source=str(path),
        kind="candidate",
        family_tests=default_family_tests or count_cv_family_tests(path),
        target_slippage_bps=target_slippage_bps,
        total_pnl=total_pnl,
        total_buys=total_buys,
        fold_pnls=fold_pnls,
    )


def load_portfolio_item(
    spec: str,
    target_slippage_bps: Decimal,
    family_tests: int,
) -> AuditItem:
    parts = parse_spec(spec, 1, "--portfolio-report must be formatted as report.json or report.json::label")
    path = Path(parts[0])
    label = parts[1] if len(parts) >= 2 and parts[1] else "portfolio"
    report = json.loads(path.read_text(encoding="utf-8"))
    matches = [
        row
        for row in report.get("slippage_results", [])
        if dec(row.get("slippage_bps")) == target_slippage_bps and row.get("status") == "ok"
    ]
    if not matches:
        raise SystemExit(f"Portfolio row at {target_slippage_bps} bps not found in {path}")
    row = matches[0]
    fold_pnls = [dec(fold.get("pnl")) for fold in row.get("folds", [])]
    return AuditItem(
        label=label,
        source=str(path),
        kind="portfolio",
        family_tests=max(1, family_tests),
        target_slippage_bps=target_slippage_bps,
        total_pnl=dec(row.get("total_pnl")),
        total_buys=int(row.get("total_buys") or 0),
        fold_pnls=fold_pnls,
    )


def sign_test_p_value(positive_folds: int, fold_count: int) -> Decimal:
    if fold_count <= 0:
        return Decimal("1")
    successes = max(0, min(positive_folds, fold_count))
    numerator = sum(math.comb(fold_count, k) for k in range(successes, fold_count + 1))
    denominator = 2 ** fold_count
    return Decimal(numerator) / Decimal(denominator)


def required_successes(fold_count: int, family_tests: int, alpha: Decimal) -> int | None:
    for successes in range(0, fold_count + 1):
        adjusted = min(Decimal("1"), sign_test_p_value(successes, fold_count) * Decimal(family_tests))
        if adjusted <= alpha:
            return successes
    return None


def audit_item(item: AuditItem, alpha: Decimal) -> dict[str, Any]:
    fold_count = len(item.fold_pnls)
    positive_folds = sum(1 for pnl in item.fold_pnls if pnl > ZERO)
    raw_p = sign_test_p_value(positive_folds, fold_count)
    adjusted_p = min(Decimal("1"), raw_p * Decimal(item.family_tests))
    min_raw_p = sign_test_p_value(fold_count, fold_count)
    min_adjusted_p = min(Decimal("1"), min_raw_p * Decimal(item.family_tests))
    required = required_successes(fold_count, item.family_tests, alpha)
    if adjusted_p <= alpha:
        status = "selection-adjusted significant"
    elif raw_p <= alpha:
        status = "raw significant only"
    else:
        status = "not statistically significant"
    return {
        "label": item.label,
        "source": item.source,
        "kind": item.kind,
        "status": status,
        "target_slippage_bps": fmt(item.target_slippage_bps),
        "total_pnl": fmt(item.total_pnl),
        "total_buys": item.total_buys,
        "fold_count": fold_count,
        "positive_fold_count": positive_folds,
        "fold_pnls": [fmt(value) for value in item.fold_pnls],
        "raw_sign_p_value": fmt(raw_p),
        "family_tests": item.family_tests,
        "selection_adjusted_p_value": fmt(adjusted_p),
        "minimum_possible_raw_p_value": fmt(min_raw_p),
        "minimum_possible_adjusted_p_value": fmt(min_adjusted_p),
        "required_positive_folds_for_alpha": required,
        "alpha": fmt(alpha),
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Selection Significance Audit",
        "",
        "Exact fold-sign audit for selected simulator candidates. A positive daily fold is treated as one success; zero or negative folds are not successes. The selection-adjusted p-value multiplies the raw sign-test p-value by the number of candidate/slippage trials in the relevant search family.",
        "",
        f"Target slippage: `{report['target_slippage_bps']}` bps",
        f"Alpha: `{report['alpha']}`",
        "",
        "This is intentionally conservative and does not prove future profitability. With only three completed tapes, even a 3/3 positive fold record has a raw one-sided sign-test p-value of `0.1250` before any search penalty.",
        "",
        "## Summary",
        "",
        "| Label | Status | P/L | Buys | Positive folds | Raw p | Family tests | Adjusted p | Min adjusted p | Required + folds |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["items"]:
        required = item["required_positive_folds_for_alpha"]
        required_text = "not possible" if required is None else str(required)
        lines.append(
            f"| `{item['label']}` | {item['status']} | {item['total_pnl']} | {item['total_buys']} | "
            f"{item['positive_fold_count']}/{item['fold_count']} | {item['raw_sign_p_value']} | "
            f"{item['family_tests']} | {item['selection_adjusted_p_value']} | "
            f"{item['minimum_possible_adjusted_p_value']} | {required_text} |"
        )
    lines.extend(["", "## Fold Detail", ""])
    for item in report["items"]:
        lines.extend(
            [
                f"### `{item['label']}`",
                "",
                f"Source: `{item['source']}`",
                "",
                "| Fold | P/L | Success |",
                "| ---: | ---: | --- |",
            ]
        )
        for index, pnl in enumerate(item["fold_pnls"], start=1):
            success = "yes" if dec(pnl) > ZERO else "no"
            lines.append(f"| {index} | {pnl} | {success} |")
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "- `not statistically significant` means the row can still be a paper-test candidate, but the completed-tape evidence is too small or too search-selected to call it robust.",
            "- `minimum_possible_adjusted_p_value` shows the best p-value this sample size could have achieved if every fold were positive.",
            "- `required_positive_folds_for_alpha` shows whether this fold count could clear the configured alpha after the family penalty.",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit selected simulator candidates for fold-sign significance after search selection.")
    parser.add_argument("--candidate-report", action="append", default=[], help="report.json::candidate_name::label")
    parser.add_argument("--portfolio-report", action="append", default=[], help="portfolio.json::label")
    parser.add_argument("--family-report", action="append", default=[], help="CV report whose candidate/slippage count contributes to a global family penalty.")
    parser.add_argument("--portfolio-family-tests", type=int, default=1, help="Candidate-pair/slippage trials to use for portfolio rows.")
    parser.add_argument("--target-slippage-bps", default="10")
    parser.add_argument("--alpha", default="0.05")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    target = dec(args.target_slippage_bps)
    alpha = dec(args.alpha)
    global_family_tests = sum(count_cv_family_tests(Path(path)) for path in args.family_report) if args.family_report else None
    items: list[AuditItem] = []
    for spec in args.candidate_report:
        items.append(load_candidate_item(spec, target, global_family_tests))
    for spec in args.portfolio_report:
        portfolio_tests = args.portfolio_family_tests
        if global_family_tests is not None:
            portfolio_tests = max(portfolio_tests, global_family_tests)
        items.append(load_portfolio_item(spec, target, portfolio_tests))
    if not items:
        raise SystemExit("Provide at least one --candidate-report or --portfolio-report.")

    report = {
        "target_slippage_bps": fmt(target),
        "alpha": fmt(alpha),
        "global_family_tests": global_family_tests,
        "items": [audit_item(item, alpha) for item in items],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON significance audit: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown significance audit: {args.markdown_output}")
    for item in report["items"]:
        print(
            f"{item['label']}: {item['status']} "
            f"p={item['raw_sign_p_value']} adjusted={item['selection_adjusted_p_value']} "
            f"folds={item['positive_fold_count']}/{item['fold_count']} tests={item['family_tests']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
