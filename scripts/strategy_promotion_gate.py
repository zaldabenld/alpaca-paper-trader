from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    if value in (None, "", "none", "n/a"):
        return ZERO
    if value == "inf":
        return Decimal("999999")
    if isinstance(value, str) and value.startswith(">= "):
        value = value[3:]
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def allowed_provisional_flags(flags: list[str]) -> list[str]:
    allowed_prefixes = ("thin day sample", "thin trade sample")
    return [flag for flag in flags if not flag.startswith(allowed_prefixes)]


def risk_checks(report: dict[str, Any], target_bps: Decimal) -> list[dict[str, Any]]:
    rows = []
    for strategy in report.get("strategies", []):
        target = strategy.get("target_result") or {}
        name = strategy.get("display_name") or strategy.get("name") or "unknown"
        is_portfolio = str(strategy.get("kind")) == "portfolio"
        hard_failures = []
        if dec(strategy.get("highest_passing_slippage_bps")) < target_bps:
            hard_failures.append("does not pass target slippage")
        if not target.get("stable"):
            hard_failures.append("target row is not stable")
        if dec(target.get("total_pnl")) <= ZERO:
            hard_failures.append("target P/L is not positive")
        if int(target.get("positive_fold_count") or 0) != int(target.get("fold_count") or 0):
            hard_failures.append("not positive on every fold")
        if is_portfolio and int(target.get("total_buys") or 0) <= 0:
            hard_failures.append("portfolio has no buys")
        hard_failures.extend(allowed_provisional_flags(strategy.get("evidence_flags") or []))
        rows.append(
            {
                "kind": strategy.get("kind"),
                "name": name,
                "status": "pass" if not hard_failures else "fail",
                "hard_failures": hard_failures,
                "target_pnl": target.get("total_pnl", "n/a"),
                "target_buys": target.get("total_buys", "n/a"),
                "positive_folds": f"{target.get('positive_fold_count', 'n/a')}/{target.get('fold_count', 'n/a')}",
                "highest_passing_slippage_bps": strategy.get("highest_passing_slippage_bps", "n/a"),
                "evidence_flags": strategy.get("evidence_flags") or [],
            }
        )
    return rows


def walk_forward_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for bucket in report.get("buckets", []):
        summary = bucket.get("summary") or {}
        failures = []
        if not summary.get("walk_forward_passes"):
            failures.append("walk-forward did not pass every holdout")
        if dec(summary.get("total_validation_pnl")) <= ZERO:
            failures.append("walk-forward validation P/L is not positive")
        if int(summary.get("positive_validation_fold_count") or 0) != int(summary.get("validation_fold_count") or 0):
            failures.append("not positive on every held-out day")
        rows.append(
            {
                "source": str(path),
                "bucket": bucket.get("label") or bucket.get("bucket") or "",
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "validation_pnl": summary.get("total_validation_pnl", "n/a"),
                "validation_buys": summary.get("total_validation_buys", "n/a"),
                "passed_folds": (
                    f"{summary.get('passed_validation_fold_count', 'n/a')}/"
                    f"{summary.get('validation_fold_count', 'n/a')}"
                ),
                "positive_folds": (
                    f"{summary.get('positive_validation_fold_count', 'n/a')}/"
                    f"{summary.get('validation_fold_count', 'n/a')}"
                ),
                "selected_candidates": summary.get("selected_candidates") or [],
            }
        )
    return rows


def neighborhood_checks(path: Path, report: dict[str, Any], target_bps: Decimal) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("reports", []):
        failures = []
        checked = []
        for bucket in item.get("buckets", []):
            for result in bucket.get("slippage_results", []):
                if dec(result.get("slippage_bps")) != target_bps:
                    continue
                checked.append(result)
                target = result.get("target") or {}
                if not target.get("stable"):
                    failures.append(f"target not stable at {fmt(target_bps)} bps")
                if int(result.get("stable_candidate_count") or 0) <= 0:
                    failures.append(f"no stable neighbors at {fmt(target_bps)} bps")
        if not checked:
            failures.append(f"missing neighborhood result at {fmt(target_bps)} bps")
        rows.append(
            {
                "source": str(path),
                "target": item.get("target", ""),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "target_slippage_bps": fmt(target_bps),
                "checked_rows": len(checked),
            }
        )
    return rows


def config_alignment_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("results", []):
        failures = []
        if not item.get("aligned"):
            failures.append(
                f"{item.get('mismatch_count', 'n/a')} mismatches, {item.get('missing_count', 'n/a')} missing fields"
            )
        rows.append(
            {
                "source": str(path),
                "bucket": item.get("label", ""),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "mismatch_count": item.get("mismatch_count", "n/a"),
                "missing_count": item.get("missing_count", "n/a"),
                "latest_scan": item.get("time", "n/a"),
            }
        )
    return rows


def compatibility_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("results", []):
        failures = []
        if not item.get("compatible"):
            failures.append(f"{item.get('missing_count', 'n/a')} unsupported patch fields")
        rows.append(
            {
                "source": str(path),
                "recommendation": item.get("recommendation", ""),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "field_count": item.get("field_count", "n/a"),
                "missing_count": item.get("missing_count", "n/a"),
            }
        )
    return rows


def fragility_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("strategies", []):
        decision = str(item.get("decision") or "")
        failures = []
        if decision.startswith("research only"):
            failures.append(decision)
        rows.append(
            {
                "source": str(path),
                "name": item.get("name", "unknown"),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "total_pnl": item.get("total_pnl", "n/a"),
                "trade_count": item.get("trade_count", "n/a"),
                "remove_best_trade_pnl": item.get("remove_best_trade_pnl", "n/a"),
                "remove_best_day_pnl": item.get("remove_best_day_pnl", "n/a"),
                "close_liquidation_profit_share_percent": item.get("close_liquidation_profit_share_percent", "n/a"),
                "decision": decision,
                "evidence_flags": item.get("evidence_flags") or [],
            }
        )
    return rows


def confidence_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("strategies", []):
        decision = str(item.get("decision") or "")
        failures = []
        if decision.startswith("research only"):
            failures.append(decision)
        trade_bootstrap = item.get("trade_bootstrap") if isinstance(item.get("trade_bootstrap"), dict) else {}
        day_bootstrap = item.get("day_bootstrap") if isinstance(item.get("day_bootstrap"), dict) else {}
        rows.append(
            {
                "source": str(path),
                "name": item.get("name", "unknown"),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "observed_total_pnl": item.get("observed_total_pnl", "n/a"),
                "trade_count": item.get("trade_count", "n/a"),
                "day_count": item.get("day_count", "n/a"),
                "trade_positive_probability": trade_bootstrap.get("positive_probability", "n/a"),
                "trade_p05": trade_bootstrap.get("p05", "n/a"),
                "day_positive_probability": day_bootstrap.get("positive_probability", "n/a"),
                "day_p05": day_bootstrap.get("p05", "n/a"),
                "decision": decision,
                "evidence_flags": item.get("evidence_flags") or [],
            }
        )
    return rows


def significance_checks(path: Path, report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in report.get("items", []):
        status_text = str(item.get("status") or "")
        failures = []
        evidence_flags = []
        if dec(item.get("total_pnl")) <= ZERO:
            failures.append("target P/L is not positive")
        if int(item.get("positive_fold_count") or 0) != int(item.get("fold_count") or 0):
            failures.append("not positive on every fold")
        if status_text != "selection-adjusted significant":
            evidence_flags.append(status_text or "not statistically significant")
        rows.append(
            {
                "source": str(path),
                "label": item.get("label", "unknown"),
                "status": "pass" if not failures else "fail",
                "hard_failures": failures,
                "evidence_flags": evidence_flags,
                "total_pnl": item.get("total_pnl", "n/a"),
                "total_buys": item.get("total_buys", "n/a"),
                "positive_folds": f"{item.get('positive_fold_count', 'n/a')}/{item.get('fold_count', 'n/a')}",
                "raw_sign_p_value": item.get("raw_sign_p_value", "n/a"),
                "family_tests": item.get("family_tests", "n/a"),
                "selection_adjusted_p_value": item.get("selection_adjusted_p_value", "n/a"),
                "minimum_possible_adjusted_p_value": item.get("minimum_possible_adjusted_p_value", "n/a"),
            }
        )
    return rows


def overall_decision(
    risk_rows: list[dict[str, Any]],
    walk_rows: list[dict[str, Any]],
    neighborhood_rows: list[dict[str, Any]],
    config_rows: list[dict[str, Any]],
    compatibility_rows: list[dict[str, Any]],
    fragility_rows: list[dict[str, Any]],
    confidence_rows: list[dict[str, Any]],
    significance_rows: list[dict[str, Any]],
) -> str:
    evidence_rows = (
        risk_rows
        + walk_rows
        + neighborhood_rows
        + compatibility_rows
        + fragility_rows
        + confidence_rows
        + significance_rows
    )
    if any(row["status"] != "pass" for row in compatibility_rows):
        return "research only"
    if any(row["status"] != "pass" for row in config_rows):
        return "config not aligned"
    rows = evidence_rows + config_rows
    if not rows:
        return "research only"
    if any(row["status"] != "pass" for row in evidence_rows):
        return "research only"
    if any(row.get("evidence_flags") for row in risk_rows):
        return "paper-test provisional"
    if any(row.get("evidence_flags") for row in fragility_rows):
        return "paper-test provisional"
    if any(row.get("evidence_flags") for row in confidence_rows):
        return "paper-test provisional"
    if any(row.get("evidence_flags") for row in significance_rows):
        return "paper-test provisional"
    return "paper-test"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Strategy Promotion Gate",
        "",
        f"Decision: `{report['decision']}`",
        "",
        f"Target slippage: `{report['target_slippage_bps']}` bps",
        "",
        "## Risk Checks",
        "",
        "| Strategy | Status | Target P/L | Buys | Positive folds | Pass bps | Notes |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["risk_checks"]:
        notes = "; ".join(row["hard_failures"] or row["evidence_flags"] or ["ok"])
        lines.append(
            f"| `{row['name']}` | {row['status']} | {row['target_pnl']} | {row['target_buys']} | "
            f"{row['positive_folds']} | {row['highest_passing_slippage_bps']} | {notes} |"
        )
    lines.extend(
        [
            "",
            "## Walk-Forward Checks",
            "",
            "| Bucket | Status | Validation P/L | Buys | Passed folds | Positive folds | Selected candidates |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report["walk_forward_checks"]:
        selected = ", ".join(f"`{item}`" for item in row["selected_candidates"])
        notes = "; ".join(row["hard_failures"])
        status = row["status"] if not notes else f"{row['status']}: {notes}"
        lines.append(
            f"| `{row['bucket']}` | {status} | {row['validation_pnl']} | {row['validation_buys']} | "
            f"{row['passed_folds']} | {row['positive_folds']} | {selected} |"
        )
    lines.extend(
        [
            "",
            "## Neighborhood Checks",
            "",
            "| Target | Status | Checked rows | Notes |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for row in report["neighborhood_checks"]:
        notes = "; ".join(row["hard_failures"] or ["ok"])
        lines.append(f"| `{row['target']}` | {row['status']} | {row['checked_rows']} | {notes} |")
    if report.get("config_alignment_checks"):
        lines.extend(
            [
                "",
                "## Config Alignment Checks",
                "",
                "| Bucket | Status | Mismatches | Missing | Latest scan | Notes |",
                "| --- | --- | ---: | ---: | --- | --- |",
            ]
        )
        for row in report["config_alignment_checks"]:
            notes = "; ".join(row["hard_failures"] or ["ok"])
            lines.append(
                f"| `{row['bucket']}` | {row['status']} | {row['mismatch_count']} | "
                f"{row['missing_count']} | {row['latest_scan']} | {notes} |"
            )
    if report.get("compatibility_checks"):
        lines.extend(
            [
                "",
                "## App Compatibility Checks",
                "",
                "| Recommendation | Status | Fields | Missing | Notes |",
                "| --- | --- | ---: | ---: | --- |",
            ]
        )
        for row in report["compatibility_checks"]:
            notes = "; ".join(row["hard_failures"] or ["ok"])
            lines.append(
                f"| `{row['recommendation']}` | {row['status']} | {row['field_count']} | "
                f"{row['missing_count']} | {notes} |"
            )
    if report.get("fragility_checks"):
        lines.extend(
            [
                "",
                "## Fragility Checks",
                "",
                "| Strategy | Status | P/L | Exits | Remove best trade | Remove best day | Close-liq winner share | Notes |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in report["fragility_checks"]:
            notes = "; ".join(row["hard_failures"] or row["evidence_flags"] or ["ok"])
            lines.append(
                f"| `{row['name']}` | {row['status']} | {row['total_pnl']} | {row['trade_count']} | "
                f"{row['remove_best_trade_pnl']} | {row['remove_best_day_pnl']} | "
                f"{row['close_liquidation_profit_share_percent']}% | {notes} |"
            )
    if report.get("confidence_checks"):
        lines.extend(
            [
                "",
                "## Confidence Checks",
                "",
                "| Strategy | Status | P/L | Exits | Days | Trade P(+) | Trade p05 | Day P(+) | Day p05 | Notes |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in report["confidence_checks"]:
            notes = "; ".join(row["hard_failures"] or row["evidence_flags"] or ["ok"])
            lines.append(
                f"| `{row['name']}` | {row['status']} | {row['observed_total_pnl']} | "
                f"{row['trade_count']} | {row['day_count']} | {row['trade_positive_probability']}% | "
                f"{row['trade_p05']} | {row['day_positive_probability']}% | {row['day_p05']} | {notes} |"
            )
    if report.get("significance_checks"):
        lines.extend(
            [
                "",
                "## Selection Significance Checks",
                "",
                "| Strategy | Status | P/L | Buys | Positive folds | Raw p | Family tests | Adjusted p | Min adjusted p | Notes |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for row in report["significance_checks"]:
            notes = "; ".join(row["hard_failures"] or row["evidence_flags"] or ["ok"])
            lines.append(
                f"| `{row['label']}` | {row['status']} | {row['total_pnl']} | {row['total_buys']} | "
                f"{row['positive_folds']} | {row['raw_sign_p_value']} | {row['family_tests']} | "
                f"{row['selection_adjusted_p_value']} | {row['minimum_possible_adjusted_p_value']} | {notes} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Combine replay evidence into a paper-test promotion decision.")
    parser.add_argument("--risk-report", type=Path, required=True)
    parser.add_argument("--walk-forward-report", action="append", type=Path, default=[])
    parser.add_argument("--neighborhood-report", action="append", type=Path, default=[])
    parser.add_argument("--config-alignment-report", action="append", type=Path, default=[])
    parser.add_argument("--compatibility-report", action="append", type=Path, default=[])
    parser.add_argument("--fragility-report", action="append", type=Path, default=[])
    parser.add_argument("--confidence-report", action="append", type=Path, default=[])
    parser.add_argument("--significance-report", action="append", type=Path, default=[])
    parser.add_argument("--target-slippage-bps", type=Decimal, default=Decimal("10"))
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    target_bps = max(ZERO, args.target_slippage_bps)
    risk_rows = risk_checks(load_json(args.risk_report), target_bps)
    walk_rows: list[dict[str, Any]] = []
    for path in args.walk_forward_report:
        walk_rows.extend(walk_forward_checks(path, load_json(path)))
    neighborhood_rows: list[dict[str, Any]] = []
    for path in args.neighborhood_report:
        neighborhood_rows.extend(neighborhood_checks(path, load_json(path), target_bps))
    config_rows: list[dict[str, Any]] = []
    for path in args.config_alignment_report:
        config_rows.extend(config_alignment_checks(path, load_json(path)))
    compatibility_rows: list[dict[str, Any]] = []
    for path in args.compatibility_report:
        compatibility_rows.extend(compatibility_checks(path, load_json(path)))
    fragility_rows: list[dict[str, Any]] = []
    for path in args.fragility_report:
        fragility_rows.extend(fragility_checks(path, load_json(path)))
    confidence_rows: list[dict[str, Any]] = []
    for path in args.confidence_report:
        confidence_rows.extend(confidence_checks(path, load_json(path)))
    significance_rows: list[dict[str, Any]] = []
    for path in args.significance_report:
        significance_rows.extend(significance_checks(path, load_json(path)))
    report = {
        "decision": overall_decision(
            risk_rows,
            walk_rows,
            neighborhood_rows,
            config_rows,
            compatibility_rows,
            fragility_rows,
            confidence_rows,
            significance_rows,
        ),
        "target_slippage_bps": fmt(target_bps),
        "risk_report": str(args.risk_report),
        "walk_forward_reports": [str(path) for path in args.walk_forward_report],
        "neighborhood_reports": [str(path) for path in args.neighborhood_report],
        "config_alignment_reports": [str(path) for path in args.config_alignment_report],
        "compatibility_reports": [str(path) for path in args.compatibility_report],
        "fragility_reports": [str(path) for path in args.fragility_report],
        "confidence_reports": [str(path) for path in args.confidence_report],
        "significance_reports": [str(path) for path in args.significance_report],
        "risk_checks": risk_rows,
        "walk_forward_checks": walk_rows,
        "neighborhood_checks": neighborhood_rows,
        "config_alignment_checks": config_rows,
        "compatibility_checks": compatibility_rows,
        "fragility_checks": fragility_rows,
        "confidence_checks": confidence_rows,
        "significance_checks": significance_rows,
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    print(f"Decision: {report['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
