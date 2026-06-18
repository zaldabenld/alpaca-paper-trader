from __future__ import annotations

import argparse
from datetime import datetime
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from day_tape_strategy_sweep import default_tape_dir, selected_sweep_files, tape_file_date


BEST_CANDIDATE = "pricebox_session_0.30_max_300_smi_50_score_30|balanced_2.5_1.25"
FAILED_NEIGHBOR_CANDIDATE = "pricebox_session_0.25_max_300_smi_50_score_30|balanced_2.5_1.25"
MAX20_NEIGHBORHOOD = [
    FAILED_NEIGHBOR_CANDIDATE,
    BEST_CANDIDATE,
    "pricebox_session_0.35_max_300_smi_50_score_30|balanced_2.5_1.25",
]
MAX16_NEIGHBORHOOD = [
    FAILED_NEIGHBOR_CANDIDATE,
    BEST_CANDIDATE,
    "pricebox_session_0.35_max_300_smi_50_score_30|balanced_2.5_1.25",
]


@dataclass(frozen=True)
class CommandSpec:
    label: str
    args: list[str]


def script(name: str) -> str:
    return str(Path("scripts") / name)


def report_path(reports_dir: Path, name: str, end_date: str, ext: str) -> str:
    return str(reports_dir / f"{name}-{end_date}.{ext}")


def candidate_args(names: list[str]) -> list[str]:
    args: list[str] = []
    for name in names:
        args.extend(["--candidate-list", name])
    return args


def cross_validate_command(
    *,
    tape_path: str,
    label: str,
    days: int,
    end_date: str,
    bucket: str,
    candidates: list[str],
    slippage: str,
    output: str,
) -> CommandSpec:
    return CommandSpec(
        label,
        [
            sys.executable,
            script("day_tape_cross_validate.py"),
            "--path",
            tape_path,
            "--days",
            str(days),
            "--end-date",
            end_date,
            "--top",
            "12",
            "--candidate-mode",
            "pricebox_session",
            "--exit-mode",
            "fixed",
            *candidate_args(candidates),
            "--bucket-contains",
            bucket,
            "--slippage-bps-list",
            slippage,
            "--min-fold-trades",
            "1",
            "--min-profit-factor",
            "1.2",
            "--price-source",
            "trades",
            "--scan-interval-seconds",
            "15",
            "--min-stop-hold-minutes",
            "0",
            "--no-liquidate-at-end",
            "--liquidate-on-close",
            "--json-output",
            output,
        ],
    )


def walk_forward_command(
    *,
    tape_path: str,
    label: str,
    days: int,
    end_date: str,
    bucket: str,
    candidates: list[str],
    json_output: str,
    markdown_output: str,
) -> CommandSpec:
    return CommandSpec(
        label,
        [
            sys.executable,
            script("day_tape_walk_forward.py"),
            "--path",
            tape_path,
            "--days",
            str(days),
            "--end-date",
            end_date,
            "--top",
            "4",
            "--candidate-mode",
            "pricebox_session",
            "--exit-mode",
            "fixed",
            *candidate_args(candidates),
            "--bucket-contains",
            bucket,
            "--slippage-bps",
            "10",
            "--min-fold-trades",
            "1",
            "--min-profit-factor",
            "1.2",
            "--price-source",
            "trades",
            "--scan-interval-seconds",
            "15",
            "--min-stop-hold-minutes",
            "0",
            "--no-liquidate-at-end",
            "--liquidate-on-close",
            "--json-output",
            json_output,
            "--markdown-output",
            markdown_output,
        ],
    )


def trade_diagnostics_command(
    *,
    tape_path: str,
    label: str,
    days: int,
    end_date: str,
    bucket: str,
    candidate: str,
    json_output: str,
) -> CommandSpec:
    return CommandSpec(
        label,
        [
            sys.executable,
            script("day_tape_trade_diagnostics.py"),
            "--path",
            tape_path,
            "--days",
            str(days),
            "--end-date",
            end_date,
            "--bucket-contains",
            bucket,
            "--candidate",
            candidate,
            "--candidate-mode",
            "pricebox_session",
            "--exit-mode",
            "fixed",
            "--price-source",
            "trades",
            "--scan-interval-seconds",
            "15",
            "--slippage-bps",
            "10",
            "--no-liquidate-at-end",
            "--liquidate-on-close",
            "--min-stop-hold-minutes",
            "0",
            "--json-output",
            json_output,
        ],
    )


def build_commands(args: argparse.Namespace) -> list[CommandSpec]:
    reports_dir = Path(args.reports_dir)
    tape_path = str(Path(args.path))
    days = max(2, args.days)
    end_date = str(args.end_date)
    cv20 = report_path(reports_dir, "cv-max20-pricebox-session030-scan15", end_date, "json")
    cv16 = report_path(reports_dir, "cv-max16-pricebox-session030-scan15", end_date, "json")
    rec20_json = report_path(reports_dir, "recommendation-max20-pricebox-session030-scan15", end_date, "json")
    rec20_md = report_path(reports_dir, "recommendation-max20-pricebox-session030-scan15", end_date, "md")
    rec16_json = report_path(reports_dir, "recommendation-max16-pricebox-session030-scan15", end_date, "json")
    rec16_md = report_path(reports_dir, "recommendation-max16-pricebox-session030-scan15", end_date, "md")
    portfolio_json = report_path(reports_dir, "portfolio-aggressive-pricebox-session030-scan15", end_date, "json")
    portfolio_md = report_path(reports_dir, "portfolio-aggressive-pricebox-session030-scan15", end_date, "md")
    risk_json = report_path(reports_dir, "strategy-risk-audit-aggressive-pricebox-session030-scan15", end_date, "json")
    risk_md = report_path(reports_dir, "strategy-risk-audit-aggressive-pricebox-session030-scan15", end_date, "md")
    scorecard_json = report_path(reports_dir, "strategy-candidate-scorecard-session030", end_date, "json")
    scorecard_md = report_path(reports_dir, "strategy-candidate-scorecard-session030", end_date, "md")
    diag20_json = report_path(reports_dir, "diag-max20-pricebox-session030-smi50-balanced2_5-slip10-scan15", end_date, "json")
    diag16_json = report_path(reports_dir, "diag-max16-pricebox-session030-smi50-balanced2_5-slip10-scan15", end_date, "json")
    diag16_failed_neighbor_json = report_path(reports_dir, "diag-max16-pricebox-session025-smi50-balanced2_5-slip10-scan15", end_date, "json")
    fragility_json = report_path(reports_dir, "strategy-fragility-audit-aggressive-pricebox-session030-scan15", end_date, "json")
    fragility_md = report_path(reports_dir, "strategy-fragility-audit-aggressive-pricebox-session030-scan15", end_date, "md")
    confidence_json = report_path(reports_dir, "strategy-confidence-audit-aggressive-pricebox-session030-scan15", end_date, "json")
    confidence_md = report_path(reports_dir, "strategy-confidence-audit-aggressive-pricebox-session030-scan15", end_date, "md")
    significance_json = report_path(reports_dir, "strategy-selection-significance-session030-scan15", end_date, "json")
    significance_md = report_path(reports_dir, "strategy-selection-significance-session030-scan15", end_date, "md")
    parameter_evidence_json = report_path(reports_dir, "strategy-parameter-evidence-session030", end_date, "json")
    parameter_evidence_md = report_path(reports_dir, "strategy-parameter-evidence-session030", end_date, "md")
    compatibility_json = report_path(reports_dir, "recommendation-app-compatibility-pricebox-session030-scan15", end_date, "json")
    compatibility_md = report_path(reports_dir, "recommendation-app-compatibility-pricebox-session030-scan15", end_date, "md")
    wf20_json = report_path(reports_dir, "walk-forward-max20-pricebox-session030-scan15", end_date, "json")
    wf20_md = report_path(reports_dir, "walk-forward-max20-pricebox-session030-scan15", end_date, "md")
    wf16_json = report_path(reports_dir, "walk-forward-max16-pricebox-session030-scan15", end_date, "json")
    wf16_md = report_path(reports_dir, "walk-forward-max16-pricebox-session030-scan15", end_date, "md")
    neighborhood_json = report_path(reports_dir, "strategy-neighborhood-audit-aggressive-pricebox-session030-scan15", end_date, "json")
    neighborhood_md = report_path(reports_dir, "strategy-neighborhood-audit-aggressive-pricebox-session030-scan15", end_date, "md")
    alignment_json = report_path(reports_dir, "config-alignment-aggressive-pricebox-session030-scan15", end_date, "json")
    alignment_md = report_path(reports_dir, "config-alignment-aggressive-pricebox-session030-scan15", end_date, "md")
    gate_json = report_path(reports_dir, "promotion-gate-aggressive-pricebox-session030-scan15", end_date, "json")
    gate_md = report_path(reports_dir, "promotion-gate-aggressive-pricebox-session030-scan15", end_date, "md")

    commands = [
        cross_validate_command(
            tape_path=tape_path,
            label="cross-validate max20 session-pricebox neighborhood",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=20",
            candidates=MAX20_NEIGHBORHOOD,
            slippage="5,10,15",
            output=cv20,
        ),
        cross_validate_command(
            tape_path=tape_path,
            label="cross-validate max16 session-pricebox neighborhood",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=16",
            candidates=MAX16_NEIGHBORHOOD,
            slippage="5,10,15,20,25",
            output=cv16,
        ),
        CommandSpec(
            "recommend max20 config patch",
            [
                sys.executable,
                script("day_tape_recommendation.py"),
                cv20,
                "--top",
                "4",
                "--json-output",
                rec20_json,
                "--markdown-output",
                rec20_md,
            ],
        ),
        CommandSpec(
            "recommend max16 config patch",
            [
                sys.executable,
                script("day_tape_recommendation.py"),
                cv16,
                "--top",
                "4",
                "--json-output",
                rec16_json,
                "--markdown-output",
                rec16_md,
            ],
        ),
        CommandSpec(
            "combine aggressive portfolio",
            [
                sys.executable,
                script("portfolio_candidate_summary.py"),
                "--candidate-report",
                f"{cv20}::{BEST_CANDIDATE}",
                "--candidate-report",
                f"{cv16}::{BEST_CANDIDATE}",
                "--slippage-bps-list",
                "5,10,15",
                "--json-output",
                portfolio_json,
                "--markdown-output",
                portfolio_md,
            ],
        ),
        CommandSpec(
            "risk audit",
            [
                sys.executable,
                script("strategy_risk_audit.py"),
                "--candidate-report",
                f"{cv20}::{BEST_CANDIDATE}",
                "--candidate-report",
                f"{cv16}::{BEST_CANDIDATE}",
                "--portfolio-report",
                portfolio_json,
                "--target-slippage-bps",
                "10",
                "--json-output",
                risk_json,
                "--markdown-output",
                risk_md,
            ],
        ),
        CommandSpec(
            "risk-adjusted candidate scorecard",
            [
                sys.executable,
                script("strategy_candidate_scorecard.py"),
                "--report",
                f"{cv20}::aggressive max20",
                "--report",
                f"{cv16}::aggressive max16",
                "--target-slippage-bps",
                "10",
                "--json-output",
                scorecard_json,
                "--markdown-output",
                scorecard_md,
            ],
        ),
        trade_diagnostics_command(
            tape_path=tape_path,
            label="trade diagnostics max20 at target slippage",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=20",
            candidate=BEST_CANDIDATE,
            json_output=diag20_json,
        ),
        trade_diagnostics_command(
            tape_path=tape_path,
            label="trade diagnostics max16 at target slippage",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=16",
            candidate=BEST_CANDIDATE,
            json_output=diag16_json,
        ),
        trade_diagnostics_command(
            tape_path=tape_path,
            label="failed-neighbor diagnostics max16 session025",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=16",
            candidate=FAILED_NEIGHBOR_CANDIDATE,
            json_output=diag16_failed_neighbor_json,
        ),
        CommandSpec(
            "fragility audit",
            [
                sys.executable,
                script("strategy_fragility_audit.py"),
                "--diagnostics",
                f"{diag20_json}::aggressive max20",
                "--diagnostics",
                f"{diag16_json}::aggressive max16",
                "--include-portfolio",
                "--extra-bps-list",
                "5,10",
                "--json-output",
                fragility_json,
                "--markdown-output",
                fragility_md,
            ],
        ),
        CommandSpec(
            "confidence audit",
            [
                sys.executable,
                script("strategy_confidence_audit.py"),
                "--diagnostics",
                f"{diag20_json}::aggressive max20",
                "--diagnostics",
                f"{diag16_json}::aggressive max16",
                "--include-portfolio",
                "--iterations",
                "10000",
                "--json-output",
                confidence_json,
                "--markdown-output",
                confidence_md,
            ],
        ),
        CommandSpec(
            "selection significance audit",
            [
                sys.executable,
                script("strategy_selection_significance.py"),
                "--candidate-report",
                f"{cv20}::{BEST_CANDIDATE}::aggressive max20 session030",
                "--candidate-report",
                f"{cv16}::{BEST_CANDIDATE}::aggressive max16 session030",
                "--portfolio-report",
                f"{portfolio_json}::combined aggressive portfolio",
                "--family-report",
                cv20,
                "--family-report",
                cv16,
                "--portfolio-family-tests",
                "27",
                "--target-slippage-bps",
                "10",
                "--json-output",
                significance_json,
                "--markdown-output",
                significance_md,
            ],
        ),
        CommandSpec(
            "parameter evidence audit",
            [
                sys.executable,
                script("strategy_parameter_evidence.py"),
                "--selected-diagnostics",
                f"{diag20_json}::aggressive max20 session030",
                "--selected-diagnostics",
                f"{diag16_json}::aggressive max16 session030",
                "--comparison-diagnostics",
                f"{diag16_failed_neighbor_json}::max16 session025 failed-neighbor",
                "--json-output",
                parameter_evidence_json,
                "--markdown-output",
                parameter_evidence_md,
            ],
        ),
        CommandSpec(
            "recommendation app compatibility",
            [
                sys.executable,
                script("recommendation_app_compatibility.py"),
                "--recommendation",
                rec20_json,
                "--recommendation",
                rec16_json,
                "--json-output",
                compatibility_json,
                "--markdown-output",
                compatibility_md,
            ],
        ),
        walk_forward_command(
            tape_path=tape_path,
            label="walk-forward max20",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=20",
            candidates=MAX20_NEIGHBORHOOD,
            json_output=wf20_json,
            markdown_output=wf20_md,
        ),
        walk_forward_command(
            tape_path=tape_path,
            label="walk-forward max16",
            days=days,
            end_date=end_date,
            bucket="profile=aggressive, max_trade=50, max_positions=16",
            candidates=MAX16_NEIGHBORHOOD,
            json_output=wf16_json,
            markdown_output=wf16_md,
        ),
        CommandSpec(
            "neighborhood audit",
            [
                sys.executable,
                script("strategy_neighborhood_audit.py"),
                "--report",
                f"{cv20}::{BEST_CANDIDATE}",
                "--report",
                f"{cv16}::{BEST_CANDIDATE}",
                "--json-output",
                neighborhood_json,
                "--markdown-output",
                neighborhood_md,
            ],
        ),
        CommandSpec(
            "config alignment",
            [
                sys.executable,
                script("strategy_config_alignment.py"),
                "--path",
                tape_path,
                "--days",
                "1",
                "--end-date",
                end_date,
                "--recommendation",
                f"profile=aggressive, max_trade=50, max_positions=20::{rec20_json}",
                "--recommendation",
                f"profile=aggressive, max_trade=50, max_positions=16::{rec16_json}",
                "--json-output",
                alignment_json,
                "--markdown-output",
                alignment_md,
            ],
        ),
        CommandSpec(
            "promotion gate",
            [
                sys.executable,
                script("strategy_promotion_gate.py"),
                "--risk-report",
                risk_json,
                "--walk-forward-report",
                wf20_json,
                "--walk-forward-report",
                wf16_json,
                "--neighborhood-report",
                neighborhood_json,
                "--compatibility-report",
                compatibility_json,
                "--fragility-report",
                fragility_json,
                "--confidence-report",
                confidence_json,
                "--significance-report",
                significance_json,
                "--config-alignment-report",
                alignment_json,
                "--target-slippage-bps",
                "10",
                "--json-output",
                gate_json,
                "--markdown-output",
                gate_md,
            ],
        ),
    ]
    return commands


def render_command(args: list[str]) -> str:
    rendered = []
    for arg in args:
        text = str(arg)
        if not text:
            rendered.append('""')
            continue
        if any(char.isspace() for char in text) or any(char in text for char in "|&;<>()@^"):
            rendered.append('"' + text.replace('"', '`"') + '"')
        else:
            rendered.append(text)
    return " ".join(rendered)


def validate_completed_tapes(args: argparse.Namespace) -> list[Path]:
    tape_path = Path(args.path)
    end_date = str(args.end_date or "")
    if not (len(end_date) == 8 and end_date.isdigit()):
        raise SystemExit("--end-date must be YYYYMMDD.")
    today = datetime.now().strftime("%Y%m%d")
    if end_date > today:
        raise SystemExit(f"--end-date {end_date} is in the future relative to local date {today}.")
    if end_date == today and not args.allow_partial:
        raise SystemExit(
            f"--end-date {end_date} is today's tape and may still be partial. "
            "Use a completed prior date, or pass --allow-partial only for intentional research."
        )
    files = selected_sweep_files(tape_path, max(2, args.days), end_date)
    dates = [tape_file_date(path) for path in files]
    if not files:
        raise SystemExit(f"No tape files found at {tape_path}.")
    if end_date not in dates:
        available = ", ".join(dates) or "none"
        raise SystemExit(f"No selected tape matches --end-date {end_date}. Selected dates: {available}.")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the current aggressive pricebox validation evidence pipeline.")
    parser.add_argument("--path", default=str(default_tape_dir()), help="Tape directory or one tape file.")
    parser.add_argument("--end-date", required=True, help="Completed tape end date, YYYYMMDD. Required to avoid partial tapes.")
    parser.add_argument("--days", type=int, default=4, help="Most recent completed tapes up through --end-date.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without running them.")
    parser.add_argument("--allow-partial", action="store_true", help="Allow --end-date to be today. Use only for intentional research.")
    args = parser.parse_args()

    files = validate_completed_tapes(args)
    commands = build_commands(args)
    print(f"Strategy validation pipeline for completed tapes through {args.end_date}")
    print(f"Tapes: {', '.join(path.name for path in files)}")
    print(f"Steps: {len(commands)}")
    for index, command in enumerate(commands, start=1):
        print(f"\n[{index}/{len(commands)}] {command.label}")
        print(render_command(command.args))
        if args.dry_run:
            continue
        result = subprocess.run(command.args, check=False)
        if result.returncode != 0:
            print(f"Step failed with exit code {result.returncode}: {command.label}")
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
