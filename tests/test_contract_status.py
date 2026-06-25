from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUS_SCRIPT = REPO_ROOT / "scripts" / "contract_status.py"


def load_status_module():
    spec = importlib.util.spec_from_file_location("contract_status_under_test", STATUS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {STATUS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check(name: str, ok: bool = True, detail: str = "synthetic") -> dict[str, object]:
    return {"name": name, "ok": ok, "detail": detail}


class ContractStatusTests(unittest.TestCase):
    def test_category_mapping_identifies_live_failures(self) -> None:
        module = load_status_module()
        live_report = {
            "checks": [
                check("shortcut.path"),
                check("launcher.vbs_exists"),
                check("launcher.health_currentness"),
                check("launcher.instance_startup_guard"),
                check("launcher.hidden_backend"),
                check("launcher.hidden_smoke"),
                check("launcher.edge_app_mode"),
                check("backend.health_reachable"),
                check("backend.current", False, "stale"),
                check("backend.url"),
                check("backend.paper_only"),
                check("backend.single_process", False, "two processes"),
                check("backend.health_pid_process"),
                check("instance.present"),
                check("instance.url"),
                check("instance.pid"),
                check("accounts.count"),
                check("settings.accounts_count"),
                check("settings.load_errors"),
                check("runtime.errors"),
                check("top_volume.source", False, "missing"),
                check("top_volume.count"),
                check("top_volume.error"),
                check("top_volume.cache_seconds", False, "600"),
                check("market_stream.surface"),
                check("market_stream.status"),
                check("market_stream.error"),
                check("market_stream.dashboard_symbols"),
                check("market_stream.bar_symbols"),
                *[
                    check(f"account_{index}.{suffix}")
                    for index in range(1, 4)
                    for suffix in (
                        "connected",
                        "trading_enabled",
                        "market_clock",
                        "state_surfaces",
                        "replay_surface",
                        "dashboard_surface",
                        "daily_pl_fields",
                        "daily_pl_session_date",
                        "realized_pl_session_date",
                        "daily_pl_source",
                        "daily_pl_percent_source",
                        "sizing_mode",
                        "top_volume_universe",
                    )
                ],
            ]
        }
        ui_report = {
            "ok": True,
            "checks": [
                check("ui.dailyPl"),
                check("ui.dailyPlDetail"),
                check("ui.realizedPl"),
                check("ui.active_card_daily_pl"),
                check("ui.runtime_warning_visible"),
                check("ui.stale_runtime_warning_hidden"),
            ],
        }

        categories = {
            item.name: item
            for item in module.build_categories(
                live_report,
                ui_report,
                (True, "layout passed"),
                (True, "preservation passed"),
                (True, "frontend state passed"),
                (True, "passed"),
                (True, "backtest passed"),
                (True, "audit passed"),
                (True, "strategy passed"),
            )
        }

        self.assertFalse(categories["backend_currentness"].ok)
        self.assertFalse(categories["top_volume_universe"].ok)
        self.assertTrue(categories["desktop_launcher"].ok)
        self.assertTrue(categories["paper_trading_safety"].ok)
        self.assertTrue(categories["account_state_surfaces"].ok)
        self.assertTrue(categories["daily_pl_backend"].ok)
        self.assertTrue(categories["daily_pl_rendered_ui"].ok)
        self.assertTrue(categories["runtime_warning_rendered"].ok)
        self.assertTrue(categories["market_data_stream"].ok)
        self.assertTrue(categories["layout_contract"].ok)
        self.assertTrue(categories["app_data_preservation"].ok)
        self.assertTrue(categories["audit_logging"].ok)
        self.assertTrue(categories["frontend_state_coordination"].ok)
        self.assertTrue(categories["strategy_selection_contract"].ok)
        self.assertTrue(categories["regression_harness"].ok)
        self.assertTrue(categories["replay_backtester"].ok)
        acceptance = {item.name: item for item in module.build_acceptance(list(categories.values()))}
        self.assertFalse(acceptance["backend_expected_url"].ok)
        self.assertFalse(acceptance["top25_universe_from_alpaca_api"].ok)
        self.assertTrue(acceptance["desktop_launch_from_shortcut"].ok)
        self.assertTrue(acceptance["paper_trading_only"].ok)
        self.assertTrue(acceptance["no_stale_runtime_warning"].ok)
        self.assertTrue(acceptance["saved_app_data_preserved"].ok)
        self.assertTrue(acceptance["audit_build_notes_retrievable"].ok)
        self.assertTrue(acceptance["account_switching_async_safe"].ok)
        self.assertTrue(acceptance["layout_no_horizontal_overflow"].ok)
        self.assertTrue(acceptance["market_data_stream_healthy"].ok)
        self.assertTrue(acceptance["stock_selection_independent_of_sizing"].ok)
        self.assertTrue(acceptance["backtester_uses_same_strategy_logic"].ok)

    def test_acceptance_mapping_marks_unrequested_regression_and_backtest_missing(self) -> None:
        module = load_status_module()
        categories = [
            module.Category("desktop_launcher", True, ["ok"]),
            module.Category("paper_trading_safety", True, ["ok"]),
            module.Category("backend_currentness", True, ["ok"]),
            module.Category("runtime_warning_rendered", True, ["ok"]),
            module.Category("instance_json", True, ["ok"]),
            module.Category("accounts_loaded", True, ["ok"]),
            module.Category("account_state_surfaces", True, ["ok"]),
            module.Category("daily_pl_backend", True, ["ok"]),
            module.Category("daily_pl_rendered_ui", True, ["ok"]),
            module.Category("sizing_modes", True, ["ok"]),
            module.Category("top_volume_universe", True, ["ok"]),
            module.Category("market_data_stream", True, ["ok"]),
        ]

        acceptance = {item.name: item for item in module.build_acceptance(categories)}

        self.assertFalse(acceptance["backtester_uses_same_strategy_logic"].ok)
        self.assertFalse(acceptance["regression_checks_pass"].ok)
        self.assertFalse(acceptance["layout_no_horizontal_overflow"].ok)
        self.assertFalse(acceptance["saved_app_data_preserved"].ok)
        self.assertFalse(acceptance["audit_build_notes_retrievable"].ok)
        self.assertFalse(acceptance["account_switching_async_safe"].ok)
        self.assertFalse(acceptance["stock_selection_independent_of_sizing"].ok)
        self.assertIn("replay_backtester: missing", acceptance["backtester_uses_same_strategy_logic"].evidence)
        self.assertIn("regression_harness: missing", acceptance["regression_checks_pass"].evidence)
        self.assertIn("layout_contract: missing", acceptance["layout_no_horizontal_overflow"].evidence)
        self.assertIn("app_data_preservation: missing", acceptance["saved_app_data_preserved"].evidence)
        self.assertIn("audit_logging: missing", acceptance["audit_build_notes_retrievable"].evidence)
        self.assertIn("frontend_state_coordination: missing", acceptance["account_switching_async_safe"].evidence)
        self.assertIn(
            "strategy_selection_contract: missing",
            acceptance["stock_selection_independent_of_sizing"].evidence,
        )

    def test_market_data_stream_category_fails_on_stream_errors(self) -> None:
        module = load_status_module()
        live_report = {
            "checks": [
                check("market_stream.surface"),
                check("market_stream.status"),
                check("market_stream.error", False, "market stream last_error is set"),
                check("market_stream.dashboard_symbols"),
                check("market_stream.bar_symbols"),
            ]
        }

        categories = {
            item.name: item
            for item in module.build_categories(live_report, {"checks": []}, None, None, None, None)
        }
        acceptance = {item.name: item for item in module.build_acceptance(list(categories.values()))}

        self.assertFalse(categories["market_data_stream"].ok)
        self.assertFalse(acceptance["market_data_stream_healthy"].ok)
        self.assertTrue(
            any("market_stream.error: fail" in item for item in acceptance["market_data_stream_healthy"].evidence)
        )

    def test_runtime_warning_category_fails_when_current_backend_shows_stale_warning(self) -> None:
        module = load_status_module()
        ui_report = {
            "ok": False,
            "checks": [
                check("ui.runtime_warning_visible"),
                check("ui.stale_runtime_warning_hidden", False, "current backend must not render a stale runtime warning"),
            ],
        }

        categories = {
            item.name: item
            for item in module.build_categories({"checks": []}, ui_report, None, None, None, None)
        }

        self.assertFalse(categories["runtime_warning_rendered"].ok)
        self.assertTrue(
            any("current backend must not render a stale runtime warning" in item for item in categories["runtime_warning_rendered"].evidence)
        )

    def test_paper_trading_safety_category_fails_when_health_contract_is_missing(self) -> None:
        module = load_status_module()
        live_report = {"checks": [check("backend.paper_only", False, "broker_mode=live")]}

        categories = {
            item.name: item
            for item in module.build_categories(live_report, {"checks": []}, None, None, None, None)
        }
        acceptance = {item.name: item for item in module.build_acceptance(list(categories.values()))}

        self.assertFalse(categories["paper_trading_safety"].ok)
        self.assertFalse(acceptance["paper_trading_only"].ok)
        self.assertTrue(
            any("backend.paper_only: fail" in item for item in acceptance["paper_trading_only"].evidence)
        )

    def test_strategy_contract_check_summarizes_focused_tests(self) -> None:
        module = load_status_module()
        completed = module.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="Ran 12 tests in 0.123s\n\nOK\n",
        )

        with patch.object(module.subprocess, "run", return_value=completed) as run:
            passed, message = module.run_strategy_contract_check()

        self.assertTrue(passed)
        self.assertIn("tests=12", message)
        self.assertIn("sizing/capacity separation", message)
        command = run.call_args.args[0]
        self.assertIn("tests.test_regression_baselines.StrategySelectionContractTests", command)

    def test_layout_check_summarizes_viewport_overflow_evidence(self) -> None:
        module = load_status_module()
        completed = module.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "viewports": [
                        {
                            "viewport_width": 1024,
                            "whole_page_horizontal_overflow": False,
                            "tables_scroll_locally": True,
                        },
                        {
                            "viewport_width": 1280,
                            "whole_page_horizontal_overflow": False,
                            "tables_scroll_locally": True,
                        },
                    ]
                }
            ),
            stderr="",
        )

        with patch.object(module.subprocess, "run", return_value=completed):
            passed, message = module.run_layout_check()

        self.assertTrue(passed)
        self.assertIn("viewports=1024,1280", message)
        self.assertIn("whole_page_horizontal_overflow=false", message)
        self.assertIn("tables_scroll_locally=true", message)

    def test_frontend_state_coordination_check_summarizes_focused_tests(self) -> None:
        module = load_status_module()
        completed = module.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="Ran 4 tests in 0.123s\n\nOK\n",
        )

        with patch.object(module.subprocess, "run", return_value=completed):
            passed, message = module.run_frontend_state_coordination_check()

        self.assertTrue(passed)
        self.assertIn("tests=4", message)
        self.assertIn("stale-response guards", message)

    def test_frontend_state_coordination_check_fails_when_focused_tests_fail(self) -> None:
        module = load_status_module()
        completed = module.subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="FAILED (failures=1)\n",
        )

        with patch.object(module.subprocess, "run", return_value=completed):
            passed, message = module.run_frontend_state_coordination_check()

        self.assertFalse(passed)
        self.assertIn("frontend state coordination failed", message)

    def test_app_data_preservation_check_summarizes_backup_plan_without_contents(self) -> None:
        module = load_status_module()
        with self.subTest("complete plan"):
            source = Path("C:/safe/AlpacaPaperTrader")
            files = {
                "python-settings.json": True,
                "instance.json": True,
                "dashboard-cache.json": True,
            }
            dirs = {"replay": True, "day-tape": True}

            def fake_exists(path: Path) -> bool:
                name = path.name
                return str(path) == str(source) or files.get(name, False) or dirs.get(name, False)

            with (
                patch.object(module.pre_live_backup, "app_data_dir", return_value=source),
                patch.object(Path, "exists", fake_exists),
                patch.object(Path, "is_file", lambda path: files.get(path.name, False)),
                patch.object(Path, "is_dir", lambda path: dirs.get(path.name, False)),
                patch.object(Path, "stat", lambda _path: type("Stat", (), {"st_size": 10})()),
                patch.object(module.pre_live_backup, "directory_size", return_value=(2, 20)),
                patch.object(module.pre_live_backup, "available_bytes", return_value=1000),
            ):
                passed, message = module.run_app_data_preservation_check()

            self.assertTrue(passed)
            self.assertIn("python-settings.json", message)
            self.assertIn("day-tape:2", message)
            self.assertIn("planned=", message)

    def test_app_data_preservation_check_fails_when_required_targets_are_missing(self) -> None:
        module = load_status_module()
        source = Path("C:/safe/AlpacaPaperTrader")

        def fake_exists(path: Path) -> bool:
            return str(path) == str(source)

        with (
            patch.object(module.pre_live_backup, "app_data_dir", return_value=source),
            patch.object(Path, "exists", fake_exists),
            patch.object(Path, "is_file", return_value=False),
            patch.object(Path, "is_dir", return_value=False),
            patch.object(module.pre_live_backup, "available_bytes", return_value=1000),
        ):
            passed, message = module.run_app_data_preservation_check()

        self.assertFalse(passed)
        self.assertIn("missing=", message)

    def test_audit_log_check_requires_structured_sanitized_audit_entries(self) -> None:
        module = load_status_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "audit.md"
            path.write_text(
                "\n".join(
                    [
                        "### 2026-06-25 - Goal continuation finding: AUDIT-999 sample",
                        "Status: Fixed locally",
                        "Evidence:",
                        "- observed",
                        "Expected behavior:",
                        "- expected",
                        "Fix evidence:",
                        "- fixed",
                        "Verification:",
                        "- verified",
                    ]
                ),
                encoding="utf-8",
            )

            passed, message = module.run_audit_log_check(path)

        self.assertTrue(passed)
        self.assertIn("audit_entries=1", message)
        self.assertIn("latest=AUDIT-999", message)

    def test_audit_log_check_fails_on_sensitive_token_patterns(self) -> None:
        module = load_status_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "audit.md"
            path.write_text(
                "\n".join(
                    [
                        "### 2026-06-25 - Goal continuation finding: AUDIT-999 sample",
                        "Status: Fixed locally",
                        "Evidence:",
                        "- observed",
                        "Expected behavior:",
                        "- expected",
                        "Fix evidence:",
                        "- fixed",
                        "Verification:",
                        "- verified",
                        "token ABCDEF1234567890ABCDEF1234567890",
                    ]
                ),
                encoding="utf-8",
            )

            passed, message = module.run_audit_log_check(path)

        self.assertFalse(passed)
        self.assertIn("sensitive_pattern_hits=32_hex_token", message)

    def test_replay_failure_includes_account_market_clock_evidence(self) -> None:
        module = load_status_module()
        live_report = {
            "checks": [
                check(
                    "account_1.market_clock",
                    True,
                    "account 1 market clock is_open=False, status=Closed, session=2026-06-24, next_open=Jun 25, 08:30 AM Central Daylight Time, next_close=Jun 25, 03:00 PM Central Daylight Time",
                ),
                check(
                    "account_2.market_clock",
                    True,
                    "account 2 market clock is_open=False, status=Closed, session=2026-06-24, next_open=Jun 25, 08:30 AM Central Daylight Time, next_close=Jun 25, 03:00 PM Central Daylight Time",
                ),
                check(
                    "account_3.market_clock",
                    True,
                    "account 3 market clock is_open=False, status=Closed, session=2026-06-24, next_open=Jun 25, 08:30 AM Central Daylight Time, next_close=Jun 25, 03:00 PM Central Daylight Time",
                ),
            ]
        }

        categories = {
            item.name: item
            for item in module.build_categories(live_report, {"checks": []}, None, None, None, None, (False, "waiting for scans"))
        }

        replay = categories["replay_backtester"]
        self.assertFalse(replay.ok)
        self.assertIn("waiting for scans", replay.evidence[0])
        self.assertTrue(any("account_1.market_clock" in item and "status=Closed" in item for item in replay.evidence))
        self.assertTrue(any("account_1.market_clock" in item and "next_open=Jun 25, 08:30 AM" in item for item in replay.evidence))

    def test_backtest_status_requires_app_engine_fixed_harness_and_rejections(self) -> None:
        module = load_status_module()
        summary = {
            "selection_engine": "app_engine",
            "sizing_harness": {
                "starting_equity": "1000",
                "starting_cash": "1000",
                "max_positions": 20,
                "trade_percent": "5",
                "total_exposure_percent": "100",
            },
            "counts": {
                "top_volume_snapshots": 1,
                "top_volume_contexts": 1,
                "evaluations": 2,
                "accepted_trades": 0,
                "rejected_candidates": 4,
                "parse_errors": 0,
            },
            "top_volume_sources": ["alpaca_most_actives_volume"],
            "expected_top_volume_source": "alpaca_most_actives_volume",
            "top_volume_snapshots_by_source": {"alpaca_most_actives_volume": 1},
            "top_volume_contexts_by_source": {"alpaca_most_actives_volume": 1},
            "evaluations_by_top_volume_source": {"alpaca_most_actives_volume": 2},
            "accepted_trades": [],
            "rejected_candidates_sample": [{"symbol": "AAA", "reason": "Hold"}],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }
        with (
            patch.object(module.day_tape_backtest, "default_tape_dir", return_value=Path("C:/fake/day-tape")),
            patch.object(module.day_tape_backtest, "selected_files", return_value=[Path("tape-20260624.jsonl")]),
            patch.object(module.day_tape_backtest, "run_backtest", return_value=summary),
        ):
            passed, message = module.run_backtest(days=1, max_events=123)

        self.assertTrue(passed)
        self.assertIn("event_window=latest", message)
        self.assertIn("selection_engine=app_engine", message)
        self.assertIn("rejected=4", message)
        self.assertIn("alpaca_most_actives_volume_snapshots=1", message)
        self.assertIn("alpaca_most_actives_volume_contexts=1", message)
        self.assertIn("alpaca_most_actives_volume_evaluations=2", message)

    def test_backtest_status_passes_with_scan_embedded_top_volume_context(self) -> None:
        module = load_status_module()
        summary = {
            "selection_engine": "app_engine",
            "sizing_harness": {
                "starting_equity": "1000",
                "starting_cash": "1000",
                "max_positions": 20,
                "trade_percent": "5",
                "total_exposure_percent": "100",
            },
            "counts": {
                "top_volume_snapshots": 0,
                "top_volume_contexts": 1,
                "strategy_scan_top_volume_contexts": 1,
                "evaluations": 1,
                "accepted_trades": 0,
                "rejected_candidates": 2,
                "parse_errors": 0,
            },
            "top_volume_sources": ["alpaca_most_actives_volume"],
            "expected_top_volume_source": "alpaca_most_actives_volume",
            "top_volume_snapshots_by_source": {},
            "top_volume_contexts_by_source": {"alpaca_most_actives_volume": 1},
            "evaluations_by_top_volume_source": {"alpaca_most_actives_volume": 1},
            "accepted_trades": [],
            "rejected_candidates_sample": [{"symbol": "AAA", "reason": "Hold"}],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }
        with (
            patch.object(module.day_tape_backtest, "default_tape_dir", return_value=Path("C:/fake/day-tape")),
            patch.object(module.day_tape_backtest, "selected_files", return_value=[Path("tape-20260624.jsonl")]),
            patch.object(module.day_tape_backtest, "run_backtest", return_value=summary),
        ):
            passed, message = module.run_backtest(days=1, max_events=123)

        self.assertTrue(passed)
        self.assertIn("alpaca_most_actives_volume_snapshots=0", message)
        self.assertIn("alpaca_most_actives_volume_contexts=1", message)
        self.assertIn("alpaca_most_actives_volume_evaluations=1", message)

    def test_backtest_status_fails_without_expected_alpaca_source_evaluations(self) -> None:
        module = load_status_module()
        summary = {
            "selection_engine": "app_engine",
            "sizing_harness": {
                "starting_equity": "1000",
                "starting_cash": "1000",
                "max_positions": 20,
                "trade_percent": "5",
                "total_exposure_percent": "100",
            },
            "counts": {
                "top_volume_snapshots": 1,
                "top_volume_contexts": 1,
                "evaluations": 2,
                "accepted_trades": 0,
                "rejected_candidates": 4,
                "parse_errors": 0,
            },
            "top_volume_sources": ["sp500_snapshot_volume"],
            "expected_top_volume_source": "alpaca_most_actives_volume",
            "top_volume_snapshots_by_source": {"sp500_snapshot_volume": 1},
            "top_volume_contexts_by_source": {"sp500_snapshot_volume": 1},
            "evaluations_by_top_volume_source": {"sp500_snapshot_volume": 2},
            "accepted_trades": [],
            "rejected_candidates_sample": [{"symbol": "AAA", "reason": "Hold"}],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }
        with (
            patch.object(module.day_tape_backtest, "default_tape_dir", return_value=Path("C:/fake/day-tape")),
            patch.object(module.day_tape_backtest, "selected_files", return_value=[Path("tape-20260624.jsonl")]),
            patch.object(module.day_tape_backtest, "run_backtest", return_value=summary),
        ):
            passed, message = module.run_backtest(days=1, max_events=123)

        self.assertFalse(passed)
        self.assertIn("expected_top_volume_source", message)
        self.assertIn("alpaca_most_actives_volume_evaluations=0", message)

    def test_backtest_status_reports_pending_market_open_scan_when_alpaca_snapshots_exist(self) -> None:
        module = load_status_module()
        summary = {
            "selection_engine": "app_engine",
            "sizing_harness": {
                "starting_equity": "1000",
                "starting_cash": "1000",
                "max_positions": 20,
                "trade_percent": "5",
                "total_exposure_percent": "100",
            },
            "counts": {
                "top_volume_snapshots": 1,
                "top_volume_contexts": 1,
                "evaluations": 2,
                "accepted_trades": 0,
                "rejected_candidates": 4,
                "parse_errors": 0,
            },
            "top_volume_sources": ["alpaca_most_actives_volume"],
            "expected_top_volume_source": "alpaca_most_actives_volume",
            "top_volume_snapshots_by_source": {"alpaca_most_actives_volume": 1},
            "top_volume_contexts_by_source": {"alpaca_most_actives_volume": 1},
            "evaluations_by_top_volume_source": {"sp500_snapshot_volume": 2},
            "accepted_trades": [],
            "rejected_candidates_sample": [{"symbol": "AAA", "reason": "Hold"}],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }
        with (
            patch.object(module.day_tape_backtest, "default_tape_dir", return_value=Path("C:/fake/day-tape")),
            patch.object(module.day_tape_backtest, "selected_files", return_value=[Path("tape-20260624.jsonl")]),
            patch.object(module.day_tape_backtest, "run_backtest", return_value=summary),
        ):
            passed, message = module.run_backtest(days=1, max_events=123)

        self.assertFalse(passed)
        self.assertIn("alpaca_most_actives_volume_snapshots=1", message)
        self.assertIn("alpaca_most_actives_volume_contexts=1", message)
        self.assertIn("alpaca_most_actives_volume_evaluations=0", message)
        self.assertIn("waiting for market-open strategy_scan evaluations", message)

    def test_backtest_status_fails_on_parallel_selector_or_parse_errors(self) -> None:
        module = load_status_module()
        summary = {
            "selection_engine": "parallel_selector",
            "sizing_harness": {},
            "counts": {
                "top_volume_snapshots": 0,
                "top_volume_contexts": 0,
                "evaluations": 1,
                "accepted_trades": 0,
                "rejected_candidates": 0,
                "parse_errors": 1,
            },
            "accepted_trades": [],
            "rejected_candidates_sample": [],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }
        with (
            patch.object(module.day_tape_backtest, "default_tape_dir", return_value=Path("C:/fake/day-tape")),
            patch.object(module.day_tape_backtest, "selected_files", return_value=[Path("tape-20260624.jsonl")]),
            patch.object(module.day_tape_backtest, "run_backtest", return_value=summary),
        ):
            passed, message = module.run_backtest(days=1, max_events=123)

        self.assertFalse(passed)
        self.assertIn("failed_checks=", message)


if __name__ == "__main__":
    unittest.main()
