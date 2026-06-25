from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import verify_live_contract
import verify_ui_display
import day_tape_backtest
import pre_live_backup


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_BACKTEST_DAYS = 1
DEFAULT_BACKTEST_MAX_EVENTS = 50000
AUDIT_LOG = REPO_ROOT / ".codex" / "audits" / "2026-06-24-full-code-audit.md"


@dataclass
class Category:
    name: str
    ok: bool
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "evidence": self.evidence,
        }


@dataclass
class AcceptanceItem:
    name: str
    ok: bool
    evidence: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "evidence": self.evidence,
        }


def check_lookup(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): item
        for item in report.get("checks", [])
        if isinstance(item, dict)
    }


def ok(checks: dict[str, dict[str, Any]], *names: str) -> bool:
    return all(bool(checks.get(name, {}).get("ok")) for name in names)


def detail(checks: dict[str, dict[str, Any]], name: str) -> str:
    item = checks.get(name, {})
    status = "ok" if item.get("ok") else "fail"
    return f"{name}: {status} - {item.get('detail', 'missing')}"


def run_regression() -> tuple[bool, str]:
    result = subprocess.run(
        [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), str(SCRIPT_DIR / "run_regression_tests.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, "scripts/run_regression_tests.py passed"
    tail = "\n".join((result.stdout + result.stderr).splitlines()[-8:])
    return False, f"scripts/run_regression_tests.py failed: {tail}"


def run_frontend_state_coordination_check() -> tuple[bool, str]:
    result = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "unittest",
            "tests.test_frontend_state_layout.FrontendStateCoordinationTests",
            "-v",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode == 0:
        ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
        count = ran.group(1) if ran else "unknown"
        return (
            True,
            "frontend state coordination passed: "
            f"tests={count}, account-scoped requests, stale-response guards, and guarded autosave covered",
        )
    tail = "\n".join(output.splitlines()[-8:])
    return False, f"frontend state coordination failed: {tail}"


def run_strategy_contract_check() -> tuple[bool, str]:
    targets = [
        "tests.test_regression_baselines.ConfigAndSizingBaselineTests",
        "tests.test_regression_baselines.StrategySelectionContractTests",
        "tests.test_regression_baselines.MarketStreamBaselineTests",
        "tests.test_day_tape_backtest.DayTapeBacktestTests.test_backtest_uses_recorded_top_volume_universe_not_fallback_symbols",
        "tests.test_day_tape_backtest.DayTapeBacktestTests.test_disabled_trading_strategy_scan_still_proves_replay_universe",
        "tests.test_day_tape_backtest.DayTapeBacktestTests.test_replay_harness_forces_top_volume_context_over_manual_scan_config",
        "tests.test_backtester_boundary_diagnostics.BacktesterBoundaryTests.test_backtester_boundary_delegates_to_live_strategy_methods",
    ]
    result = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
            "-m",
            "unittest",
            *targets,
            "-v",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    if result.returncode == 0:
        ran = re.search(r"Ran\s+(\d+)\s+tests?", output)
        count = ran.group(1) if ran else "unknown"
        return (
            True,
            "strategy selection contract passed: "
            f"tests={count}, top-volume universe, sizing/capacity separation, "
            "inverse ETF same-rule eligibility, held-position monitoring, disabled-trading replay capture, "
            "and replay engine reuse covered",
        )
    tail = "\n".join(output.splitlines()[-8:])
    return False, f"strategy selection contract failed: {tail}"


def run_layout_check() -> tuple[bool, str]:
    result = subprocess.run(
        [str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"), str(SCRIPT_DIR / "check_frontend_layout.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-8:])
        return False, f"scripts/check_frontend_layout.py failed: {tail}"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return True, "scripts/check_frontend_layout.py passed"
    viewports = payload.get("viewports") if isinstance(payload, dict) else []
    if isinstance(viewports, list) and viewports:
        widths = [
            str(item.get("viewport_width"))
            for item in viewports
            if isinstance(item, dict) and item.get("viewport_width")
        ]
        overflow = any(
            bool(item.get("whole_page_horizontal_overflow"))
            for item in viewports
            if isinstance(item, dict)
        )
        local_scroll = all(
            bool(item.get("tables_scroll_locally"))
            for item in viewports
            if isinstance(item, dict)
        )
        return (
            not overflow and local_scroll,
            "scripts/check_frontend_layout.py passed: "
            f"viewports={','.join(widths) or 'unknown'}, "
            f"whole_page_horizontal_overflow={str(overflow).lower()}, "
            f"tables_scroll_locally={str(local_scroll).lower()}",
        )
    return True, "scripts/check_frontend_layout.py passed"


def run_app_data_preservation_check() -> tuple[bool, str]:
    source_root = pre_live_backup.app_data_dir()
    if not source_root.exists():
        return False, "app data backup plan failed: AlpacaPaperTrader app-data folder is missing"

    expected_files = set(pre_live_backup.CORE_FILES)
    expected_dirs = set(pre_live_backup.CORE_DIRS)
    required_files = {"python-settings.json", "instance.json", "dashboard-cache.json"}
    required_dirs = {"replay", "day-tape"}
    script_covers_expected = required_files.issubset(expected_files) and required_dirs.issubset(expected_dirs)

    present_files = [
        name
        for name in pre_live_backup.CORE_FILES
        if (source_root / name).exists() and (source_root / name).is_file()
    ]
    present_dirs = [
        name
        for name in pre_live_backup.CORE_DIRS
        if (source_root / name).exists() and (source_root / name).is_dir()
    ]
    missing_required = sorted((required_files - set(present_files)) | (required_dirs - set(present_dirs)))

    planned_bytes = 0
    for name in present_files:
        try:
            planned_bytes += (source_root / name).stat().st_size
        except OSError:
            pass
    planned_dir_counts: list[str] = []
    for name in present_dirs:
        count, bytes_total = pre_live_backup.directory_size(source_root / name)
        planned_bytes += bytes_total
        planned_dir_counts.append(f"{name}:{count}")

    previous_root = pre_live_backup.latest_backup_root(pre_live_backup.DEFAULT_BACKUP_ROOT)
    reusable_bytes = pre_live_backup.reusable_backup_bytes(source_root, previous_root)
    additional_bytes = max(0, planned_bytes - reusable_bytes)
    free_bytes = pre_live_backup.available_bytes(pre_live_backup.DEFAULT_BACKUP_ROOT)
    enough_space = additional_bytes <= free_bytes
    ok = script_covers_expected and not missing_required and enough_space
    detail = (
        "app data backup plan "
        f"{'passed' if ok else 'failed'}: "
        f"files={','.join(present_files) or 'none'}, "
        f"dirs={','.join(planned_dir_counts) or 'none'}, "
        f"planned={pre_live_backup.format_bytes(planned_bytes)}, "
        f"reusable={pre_live_backup.format_bytes(reusable_bytes)}, "
        f"additional={pre_live_backup.format_bytes(additional_bytes)}, "
        f"available={pre_live_backup.format_bytes(free_bytes)}"
    )
    if not script_covers_expected:
        detail += "; script_missing_required_targets"
    if missing_required:
        detail += f"; missing={','.join(missing_required)}"
    if not enough_space:
        detail += "; insufficient_backup_space"
    return ok, detail


def run_audit_log_check(path: Path = AUDIT_LOG) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"audit log check failed: {exc}"

    audit_ids = [int(match) for match in re.findall(r"\bAUDIT-(\d{3})\b", text)]
    unique_ids = sorted(set(audit_ids))
    required_terms = ("Status:", "Evidence:", "Expected behavior:", "Fix evidence:")
    missing_terms = [term for term in required_terms if term not in text]
    verification_present = "Verification:" in text or "Required verification:" in text
    sensitive_patterns = {
        "alpaca_key_like_token": r"\bAPCA[A-Z0-9]{10,}\b",
        "32_hex_token": r"\b[a-fA-F0-9]{32}\b",
        "json_secret_assignment": r"(?i)(api_secret|secret_key|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    }
    sensitive_hits = [
        name
        for name, pattern in sensitive_patterns.items()
        if re.search(pattern, text)
    ]
    ok = bool(unique_ids) and not missing_terms and verification_present and not sensitive_hits
    latest = f"AUDIT-{unique_ids[-1]:03d}" if unique_ids else "none"
    detail = (
        "audit log "
        f"{'passed' if ok else 'failed'}: "
        f"path={path}, "
        f"audit_entries={len(unique_ids)}, "
        f"latest={latest}"
    )
    if missing_terms:
        detail += f"; missing_terms={','.join(term.rstrip(':') for term in missing_terms)}"
    if not verification_present:
        detail += "; missing_terms=Verification"
    if sensitive_hits:
        detail += f"; sensitive_pattern_hits={','.join(sensitive_hits)}"
    return ok, detail


def _count(summary: dict[str, Any], name: str) -> int:
    counts = summary.get("counts")
    if not isinstance(counts, dict):
        return 0
    try:
        return int(counts.get(name) or 0)
    except (TypeError, ValueError):
        return 0


def run_backtest(
    days: int = DEFAULT_BACKTEST_DAYS,
    max_events: int = DEFAULT_BACKTEST_MAX_EVENTS,
    *,
    latest_events: bool = True,
) -> tuple[bool, str]:
    path = day_tape_backtest.default_tape_dir()
    files = day_tape_backtest.selected_files(path, max(1, days))
    if not files:
        return False, f"scripts/day_tape_backtest.py found no day-tape files in {path}"
    try:
        summary = day_tape_backtest.run_backtest(files, max(0, max_events), latest_events=latest_events)
    except Exception as exc:
        return False, f"scripts/day_tape_backtest.py failed: {exc}"

    harness = summary.get("sizing_harness")
    fixed_harness = (
        isinstance(harness, dict)
        and harness.get("starting_equity") == "1000"
        and harness.get("starting_cash") == "1000"
        and int(harness.get("max_positions") or 0) == 20
        and str(harness.get("trade_size_mode") or "percent") == "percent"
        and str(harness.get("trade_percent") or "") == "5"
        and str(harness.get("trade_notional") or "0") == "0"
        and str(harness.get("total_exposure_percent") or "") == "100"
    )
    top_volume_sources = summary.get("top_volume_sources") if isinstance(summary.get("top_volume_sources"), list) else []
    expected_top_volume_source = str(
        summary.get("expected_top_volume_source") or verify_live_contract.EXPECTED_TOP_VOLUME_SOURCE
    )
    evaluations_by_source = (
        summary.get("evaluations_by_top_volume_source")
        if isinstance(summary.get("evaluations_by_top_volume_source"), dict)
        else {}
    )
    snapshots_by_source = (
        summary.get("top_volume_snapshots_by_source")
        if isinstance(summary.get("top_volume_snapshots_by_source"), dict)
        else {}
    )
    contexts_by_source = (
        summary.get("top_volume_contexts_by_source")
        if isinstance(summary.get("top_volume_contexts_by_source"), dict)
        else snapshots_by_source
    )
    expected_source_evaluations = 0
    try:
        expected_source_evaluations = int(evaluations_by_source.get(expected_top_volume_source) or 0)
    except (TypeError, ValueError):
        expected_source_evaluations = 0
    expected_source_snapshots = 0
    try:
        expected_source_snapshots = int(snapshots_by_source.get(expected_top_volume_source) or 0)
    except (TypeError, ValueError):
        expected_source_snapshots = 0
    expected_source_contexts = 0
    try:
        expected_source_contexts = int(contexts_by_source.get(expected_top_volume_source) or 0)
    except (TypeError, ValueError):
        expected_source_contexts = 0
    top_volume_context_count = _count(summary, "top_volume_contexts") or _count(summary, "top_volume_snapshots")
    reports = (
        isinstance(summary.get("accepted_trades"), list)
        and isinstance(summary.get("rejected_candidates_sample"), list)
        and isinstance(summary.get("winner_indicator_averages"), dict)
        and isinstance(summary.get("loser_indicator_averages"), dict)
    )
    checks = {
        "selection_engine": summary.get("selection_engine") == "app_engine",
        "fixed_harness": fixed_harness,
        "top_volume_contexts": top_volume_context_count > 0,
        "expected_top_volume_source": expected_top_volume_source in {str(item) for item in top_volume_sources}
        and expected_source_evaluations > 0,
        "evaluations": _count(summary, "evaluations") > 0,
        "rejected_candidates": _count(summary, "rejected_candidates") > 0,
        "parse_errors": _count(summary, "parse_errors") == 0,
        "reports": reports,
    }
    ok = all(checks.values())
    failed = [name for name, passed in checks.items() if not passed]
    message = (
        "scripts/day_tape_backtest.py "
        f"{'passed' if ok else 'failed'}: "
        f"files={len(files)}, max_events={max(0, max_events)}, "
        f"event_window={'latest' if latest_events else 'from_start'}, "
        f"selection_engine={summary.get('selection_engine')}, "
        f"top_volume_sources={','.join(str(item) for item in top_volume_sources) or 'none'}, "
        f"{expected_top_volume_source}_snapshots={expected_source_snapshots}, "
        f"{expected_top_volume_source}_contexts={expected_source_contexts}, "
        f"{expected_top_volume_source}_evaluations={expected_source_evaluations}, "
        f"top_volume_snapshots={_count(summary, 'top_volume_snapshots')}, "
        f"top_volume_contexts={top_volume_context_count}, "
        f"evaluations={_count(summary, 'evaluations')}, "
        f"accepted={_count(summary, 'accepted_trades')}, "
        f"rejected={_count(summary, 'rejected_candidates')}, "
        f"parse_errors={_count(summary, 'parse_errors')}"
    )
    if failed:
        message += f"; failed_checks={','.join(failed)}"
    if expected_source_contexts > 0 and expected_source_evaluations == 0:
        message += "; pending=fresh Alpaca top-volume context captured, waiting for market-open strategy_scan evaluations"
    return ok, message


def build_categories(
    live_report: dict[str, Any],
    ui_report: dict[str, Any] | None,
    layout_result: tuple[bool, str] | None,
    preservation_result: tuple[bool, str] | None,
    frontend_state_result: tuple[bool, str] | None,
    regression_result: tuple[bool, str] | None,
    backtest_result: tuple[bool, str] | None = None,
    audit_result: tuple[bool, str] | None = None,
    strategy_result: tuple[bool, str] | None = None,
) -> list[Category]:
    live = check_lookup(live_report)
    ui = check_lookup(ui_report or {})
    categories = [
        Category(
            "desktop_launcher",
            ok(
                live,
                "shortcut.path",
                "launcher.vbs_exists",
                "launcher.health_currentness",
                "launcher.instance_startup_guard",
                "launcher.hidden_backend",
                "launcher.hidden_smoke",
                "launcher.edge_app_mode",
            ),
            [
                detail(live, "shortcut.path"),
                detail(live, "launcher.vbs_exists"),
                detail(live, "launcher.health_currentness"),
                detail(live, "launcher.instance_startup_guard"),
                detail(live, "launcher.hidden_backend"),
                detail(live, "launcher.hidden_smoke"),
                detail(live, "launcher.edge_app_mode"),
            ],
        ),
        Category(
            "backend_currentness",
            ok(
                live,
                "backend.health_reachable",
                "backend.current",
                "backend.url",
                "backend.paper_only",
                "backend.single_process",
                "backend.health_pid_process",
            ),
            [
                detail(live, "backend.health_reachable"),
                detail(live, "backend.current"),
                detail(live, "backend.url"),
                detail(live, "backend.paper_only"),
                detail(live, "backend.single_process"),
                detail(live, "backend.health_pid_process"),
            ],
        ),
        Category(
            "paper_trading_safety",
            ok(live, "backend.paper_only"),
            [detail(live, "backend.paper_only")],
        ),
        Category(
            "instance_json",
            ok(live, "instance.present", "instance.url", "instance.pid"),
            [detail(live, "instance.present"), detail(live, "instance.url"), detail(live, "instance.pid")],
        ),
        Category(
            "accounts_loaded",
            ok(live, "accounts.count", "settings.accounts_count", "settings.load_errors"),
            [detail(live, "accounts.count"), detail(live, "settings.accounts_count"), detail(live, "settings.load_errors")],
        ),
        Category(
            "account_state_surfaces",
            all(
                ok(
                    live,
                    f"account_{index}.connected",
                    f"account_{index}.trading_enabled",
                    f"account_{index}.market_clock",
                    f"account_{index}.state_surfaces",
                    f"account_{index}.replay_surface",
                    f"account_{index}.dashboard_surface",
                )
                for index in range(1, 4)
            ),
            [
                detail(live, f"account_{index}.{suffix}")
                for index in range(1, 4)
                for suffix in (
                    "connected",
                    "trading_enabled",
                    "market_clock",
                    "state_surfaces",
                    "replay_surface",
                    "dashboard_surface",
                )
            ],
        ),
        Category(
            "daily_pl_backend",
            all(
                ok(
                    live,
                    f"account_{index}.daily_pl_fields",
                    f"account_{index}.daily_pl_session_date",
                    f"account_{index}.realized_pl_session_date",
                    f"account_{index}.daily_pl_source",
                    f"account_{index}.daily_pl_percent_source",
                )
                for index in range(1, 4)
            ),
            [
                detail(live, f"account_{index}.{suffix}")
                for index in range(1, 4)
                for suffix in (
                    "daily_pl_fields",
                    "daily_pl_session_date",
                    "realized_pl_session_date",
                    "daily_pl_source",
                    "daily_pl_percent_source",
                )
            ],
        ),
        Category(
            "daily_pl_rendered_ui",
            bool(ui_report and ui_report.get("ok")) and ok(
                ui,
                "ui.dailyPl",
                "ui.dailyPlDetail",
                "ui.realizedPl",
                "ui.active_card_daily_pl",
            ),
            [
                detail(ui, "ui.dailyPl"),
                detail(ui, "ui.dailyPlDetail"),
                detail(ui, "ui.realizedPl"),
                detail(ui, "ui.active_card_daily_pl"),
            ],
        ),
        Category(
            "runtime_warning_rendered",
            bool(ui_report)
            and ok(ui, "ui.runtime_warning_visible")
            and (ok(ui, "ui.stale_runtime_warning_hidden") or ok(ui, "ui.stale_runtime_warning_visible")),
            [
                detail(ui, "ui.runtime_warning_visible"),
                detail(ui, "ui.stale_runtime_warning_hidden"),
                detail(ui, "ui.stale_runtime_warning_visible"),
            ],
        ),
        Category(
            "sizing_modes",
            all(ok(live, f"account_{index}.sizing_mode") for index in range(1, 4)),
            [detail(live, f"account_{index}.sizing_mode") for index in range(1, 4)],
        ),
        Category(
            "top_volume_universe",
            ok(live, "top_volume.source", "top_volume.count", "top_volume.error", "top_volume.cache_seconds")
            and all(ok(live, f"account_{index}.top_volume_universe") for index in range(1, 4)),
            [
                detail(live, "top_volume.source"),
                detail(live, "top_volume.count"),
                detail(live, "top_volume.error"),
                detail(live, "top_volume.cache_seconds"),
                *[detail(live, f"account_{index}.top_volume_universe") for index in range(1, 4)],
            ],
        ),
        Category(
            "market_data_stream",
            ok(
                live,
                "market_stream.surface",
                "market_stream.status",
                "market_stream.error",
                "market_stream.dashboard_symbols",
                "market_stream.bar_symbols",
            ),
            [
                detail(live, "market_stream.surface"),
                detail(live, "market_stream.status"),
                detail(live, "market_stream.error"),
                detail(live, "market_stream.dashboard_symbols"),
                detail(live, "market_stream.bar_symbols"),
            ],
        ),
        Category(
            "runtime_diagnostics",
            ok(live, "runtime.errors"),
            [detail(live, "runtime.errors")],
        ),
    ]
    if layout_result is not None:
        passed, message = layout_result
        categories.append(Category("layout_contract", passed, [message]))
    if preservation_result is not None:
        passed, message = preservation_result
        categories.append(Category("app_data_preservation", passed, [message]))
    if audit_result is not None:
        passed, message = audit_result
        categories.append(Category("audit_logging", passed, [message]))
    if frontend_state_result is not None:
        passed, message = frontend_state_result
        categories.append(Category("frontend_state_coordination", passed, [message]))
    if strategy_result is not None:
        passed, message = strategy_result
        categories.append(Category("strategy_selection_contract", passed, [message]))
    if regression_result is not None:
        passed, message = regression_result
        categories.append(Category("regression_harness", passed, [message]))
    if backtest_result is not None:
        passed, message = backtest_result
        replay_evidence = [message]
        if not passed:
            replay_evidence.extend(detail(live, f"account_{index}.market_clock") for index in range(1, 4))
        categories.append(Category("replay_backtester", passed, replay_evidence))
    return categories


def build_acceptance(categories: list[Category]) -> list[AcceptanceItem]:
    by_name = {category.name: category for category in categories}

    def item(name: str, category_names: list[str]) -> AcceptanceItem:
        selected = [by_name.get(category_name) for category_name in category_names]
        present = [category for category in selected if category is not None]
        missing = [category_name for category_name, category in zip(category_names, selected) if category is None]
        evidence: list[str] = []
        for category in present:
            evidence.append(f"{category.name}: {'ok' if category.ok else 'fail'}")
            if not category.ok:
                evidence.extend(category.evidence[:3])
        for category_name in missing:
            evidence.append(f"{category_name}: missing")
        return AcceptanceItem(name=name, ok=bool(present) and not missing and all(category.ok for category in present), evidence=evidence)

    return [
        item("desktop_launch_from_shortcut", ["desktop_launcher"]),
        item("self_contained_no_visible_terminal", ["desktop_launcher"]),
        item("paper_trading_only", ["paper_trading_safety"]),
        item("backend_expected_url", ["backend_currentness"]),
        item("no_stale_runtime_warning", ["runtime_warning_rendered"]),
        item("single_active_backend", ["backend_currentness"]),
        item("instance_json_retained", ["instance_json"]),
        item("saved_app_data_preserved", ["app_data_preservation"]),
        item("audit_build_notes_retrievable", ["audit_logging"]),
        item("all_three_accounts_load", ["accounts_loaded", "account_state_surfaces"]),
        item("daily_pl_correct_not_false_zero", ["daily_pl_backend", "daily_pl_rendered_ui"]),
        item("account_switching_async_safe", ["frontend_state_coordination"]),
        item("layout_no_horizontal_overflow", ["layout_contract"]),
        item("sizing_mode_no_percent_dollar_conflict", ["sizing_modes"]),
        item("stock_selection_independent_of_sizing", ["strategy_selection_contract"]),
        item("top25_universe_from_alpaca_api", ["top_volume_universe"]),
        item("market_data_stream_healthy", ["market_data_stream"]),
        item("backtester_uses_same_strategy_logic", ["replay_backtester"]),
        item("regression_checks_pass", ["regression_harness"]),
    ]


def build_status(
    *,
    url: str = DEFAULT_URL,
    expected_accounts: int = 3,
    include_regression: bool = False,
    include_backtest: bool = False,
    backtest_days: int = DEFAULT_BACKTEST_DAYS,
    backtest_max_events: int = DEFAULT_BACKTEST_MAX_EVENTS,
    backtest_latest_events: bool = True,
    skip_ui: bool = False,
    skip_layout: bool = False,
    skip_preservation: bool = False,
    skip_audit: bool = False,
    skip_frontend_state: bool = False,
    skip_strategy_contract: bool = False,
) -> dict[str, Any]:
    live_payload = verify_live_contract.collect_live_payload(url)
    live_report = verify_live_contract.verify_payload(
        live_payload,
        expected_accounts=expected_accounts,
        expected_url=url,
    )
    ui_report: dict[str, Any] | None = None
    if not skip_ui:
        state, rendered = verify_ui_display.collect_rendered_payload(url)
        ui_report = verify_ui_display.verify_rendered_payload(
            state,
            rendered,
            expected_accounts=expected_accounts,
        )
    layout_result = None if skip_layout else run_layout_check()
    preservation_result = None if skip_preservation else run_app_data_preservation_check()
    audit_result = None if skip_audit else run_audit_log_check()
    frontend_state_result = None if skip_frontend_state else run_frontend_state_coordination_check()
    strategy_result = None if skip_strategy_contract else run_strategy_contract_check()
    regression_result = run_regression() if include_regression else None
    backtest_result = (
        run_backtest(backtest_days, backtest_max_events, latest_events=backtest_latest_events)
        if include_backtest
        else None
    )
    categories = build_categories(
        live_report,
        ui_report,
        layout_result,
        preservation_result,
        frontend_state_result,
        regression_result,
        backtest_result,
        audit_result,
        strategy_result,
    )
    acceptance = build_acceptance(categories)
    return {
        "ok": all(category.ok for category in categories),
        "summary": {
            "url": url,
            "expected_accounts": expected_accounts,
            "live_ok": bool(live_report.get("ok")),
            "ui_ok": None if ui_report is None else bool(ui_report.get("ok")),
            "layout_included": not skip_layout,
            "preservation_included": not skip_preservation,
            "audit_included": not skip_audit,
            "frontend_state_included": not skip_frontend_state,
            "strategy_contract_included": not skip_strategy_contract,
            "regression_included": include_regression,
            "backtest_included": include_backtest,
            "acceptance_ok": all(item.ok for item in acceptance),
        },
        "categories": [category.as_dict() for category in categories],
        "acceptance": [item.as_dict() for item in acceptance],
    }


def print_human(report: dict[str, Any]) -> None:
    print("Alpaca contract status")
    print(f"  ok: {report['ok']}")
    summary = report.get("summary", {})
    print(f"  url: {summary.get('url')}")
    print(f"  live verifier ok: {summary.get('live_ok')}")
    print(f"  rendered UI verifier ok: {summary.get('ui_ok')}")
    print(f"  layout included: {summary.get('layout_included')}")
    print(f"  app-data preservation included: {summary.get('preservation_included')}")
    print(f"  audit included: {summary.get('audit_included')}")
    print(f"  frontend state included: {summary.get('frontend_state_included')}")
    print(f"  strategy contract included: {summary.get('strategy_contract_included')}")
    print(f"  regression included: {summary.get('regression_included')}")
    print(f"  backtest included: {summary.get('backtest_included')}")
    print(f"  acceptance ok: {summary.get('acceptance_ok')}")
    print("  categories:")
    for category in report.get("categories", []):
        label = "ok" if category.get("ok") else "fail"
        print(f"    - {category.get('name')}: {label}")
        if not category.get("ok"):
            for item in category.get("evidence", [])[:8]:
                print(f"      {item}")
    if report.get("acceptance"):
        print("  acceptance:")
        for item in report.get("acceptance", []):
            label = "ok" if item.get("ok") else "fail"
            print(f"    - {item.get('name')}: {label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate sanitized Alpaca app contract evidence into pass/fail categories."
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expected-accounts", type=int, default=3)
    parser.add_argument("--include-regression", action="store_true")
    parser.add_argument("--include-backtest", action="store_true")
    parser.add_argument("--backtest-days", type=int, default=DEFAULT_BACKTEST_DAYS)
    parser.add_argument("--backtest-max-events", type=int, default=DEFAULT_BACKTEST_MAX_EVENTS)
    parser.add_argument(
        "--backtest-from-start",
        action="store_true",
        help="Replay from the start of selected tape files instead of the latest bounded event window.",
    )
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--skip-layout", action="store_true")
    parser.add_argument("--skip-preservation", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-frontend-state", action="store_true")
    parser.add_argument("--skip-strategy-contract", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = build_status(
        url=args.url,
        expected_accounts=args.expected_accounts,
        include_regression=bool(args.include_regression),
        include_backtest=bool(args.include_backtest),
        backtest_days=max(1, args.backtest_days),
        backtest_max_events=max(0, args.backtest_max_events),
        backtest_latest_events=not bool(args.backtest_from_start),
        skip_ui=bool(args.skip_ui),
        skip_layout=bool(args.skip_layout),
        skip_preservation=bool(args.skip_preservation),
        skip_audit=bool(args.skip_audit),
        skip_frontend_state=bool(args.skip_frontend_state),
        skip_strategy_contract=bool(args.skip_strategy_contract),
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
