from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
CUTOVER_SCRIPT = REPO_ROOT / "scripts" / "live_cutover.py"


def load_cutover_module():
    spec = importlib.util.spec_from_file_location("live_cutover_under_test", CUTOVER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {CUTOVER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiveCutoverTests(unittest.TestCase):
    def test_dry_run_does_not_stop_or_launch(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0) as backup,
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}),
                patch.object(module, "live_process_pids", return_value=[111, 222]),
                patch.object(module, "stop_processes") as stop_processes,
                patch.object(module, "launch_shortcut") as launch_shortcut,
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=False,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                )

        self.assertEqual(exit_code, 0)
        backup.assert_called_once_with(execute=False, backup_root=backup_root)
        stop_processes.assert_not_called()
        launch_shortcut.assert_not_called()
        self.assertIn("Dry run only", output.getvalue())
        self.assertIn("launch auto-start override: False", output.getvalue())

    def test_execute_stops_launches_and_runs_verifier_after_backup(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0) as backup,
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}),
                patch.object(module, "live_process_pids", return_value=[111]),
                patch.object(module, "stop_processes", return_value=True) as stop_processes,
                patch.object(module, "launch_shortcut") as launch_shortcut,
                patch.object(module, "verify_until_passes", return_value={"ok": True, "summary": {}, "checks": []}) as verifier,
                patch.object(module.verify_ui_display, "collect_rendered_payload", return_value=({"accounts": []}, {})) as ui_collect,
                patch.object(module.verify_ui_display, "verify_rendered_payload", return_value={"ok": True, "summary": {}, "checks": []}) as ui_verify,
                patch.object(module.contract_status, "run_layout_check", return_value=(True, "layout passed")) as layout,
                patch.object(module.contract_status, "run_app_data_preservation_check", return_value=(True, "preservation passed")) as preservation,
                patch.object(module.contract_status, "run_audit_log_check", return_value=(True, "audit passed")) as audit,
                patch.object(module.contract_status, "run_frontend_state_coordination_check", return_value=(True, "frontend state passed")) as frontend_state,
                patch.object(module.contract_status, "run_strategy_contract_check", return_value=(True, "strategy passed")) as strategy,
                patch.object(module.contract_status, "run_regression", return_value=(True, "regression passed")) as regression,
                patch.object(module.contract_status, "run_backtest", return_value=(True, "backtest passed")) as backtest,
                patch.object(module.contract_status, "build_categories", return_value=[]) as aggregate,
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                    allow_auto_start=True,
                )

        self.assertEqual(exit_code, 0)
        backup.assert_called_once_with(execute=True, backup_root=backup_root)
        stop_processes.assert_called_once_with([111])
        launch_shortcut.assert_called_once_with(
            "C:/Users/example/Desktop/Alpaca Paper Trader.lnk",
            disable_auto_start_for_launch=False,
        )
        verifier.assert_called_once()
        ui_collect.assert_called_once()
        ui_verify.assert_called_once()
        layout.assert_called_once()
        preservation.assert_called_once()
        audit.assert_called_once()
        frontend_state.assert_called_once()
        strategy.assert_called_once()
        regression.assert_called_once()
        backtest.assert_called_once()
        aggregate.assert_called_once_with(
            {"ok": True, "summary": {}, "checks": []},
            {"ok": True, "summary": {}, "checks": []},
            (True, "layout passed"),
            (True, "preservation passed"),
            (True, "frontend state passed"),
            (True, "regression passed"),
            (True, "backtest passed"),
            (True, "audit passed"),
            (True, "strategy passed"),
        )

    def test_execute_aborts_before_stop_when_auto_start_needs_approval(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0) as backup,
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}),
                patch.object(module, "stop_processes") as stop_processes,
                patch.object(module, "launch_shortcut") as launch_shortcut,
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                )

        self.assertEqual(exit_code, 1)
        backup.assert_called_once_with(execute=True, backup_root=backup_root)
        stop_processes.assert_not_called()
        launch_shortcut.assert_not_called()
        self.assertIn("--allow-auto-start", output.getvalue())
        self.assertIn("--disable-auto-start-for-launch", output.getvalue())

    def test_execute_can_suppress_auto_start_without_saved_settings_change(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with ExitStack() as stack:
                stack.enter_context(patch.object(module.pre_live_backup, "build_backup", return_value=0))
                stack.enter_context(patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"))
                stack.enter_context(patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}))
                stack.enter_context(patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})))
                stack.enter_context(patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}))
                stack.enter_context(patch.object(module, "live_process_pids", return_value=[111]))
                stop_processes = stack.enter_context(patch.object(module, "stop_processes", return_value=True))
                launch_shortcut = stack.enter_context(patch.object(module, "launch_shortcut"))
                stack.enter_context(patch.object(module, "verify_until_passes", return_value={"ok": True, "summary": {}, "checks": []}))
                stack.enter_context(patch.object(module, "verify_auto_start_override", return_value=(True, "override passed")))
                stack.enter_context(patch.object(module.verify_ui_display, "collect_rendered_payload", return_value=({"accounts": []}, {})))
                stack.enter_context(patch.object(module.verify_ui_display, "verify_rendered_payload", return_value={"ok": True, "summary": {}, "checks": []}))
                stack.enter_context(patch.object(module.contract_status, "run_layout_check", return_value=(True, "layout passed")))
                stack.enter_context(patch.object(module.contract_status, "run_app_data_preservation_check", return_value=(True, "preservation passed")))
                stack.enter_context(patch.object(module.contract_status, "run_audit_log_check", return_value=(True, "audit passed")))
                stack.enter_context(patch.object(module.contract_status, "run_frontend_state_coordination_check", return_value=(True, "frontend state passed")))
                stack.enter_context(patch.object(module.contract_status, "run_strategy_contract_check", return_value=(True, "strategy passed")))
                stack.enter_context(patch.object(module.contract_status, "run_regression", return_value=(True, "regression passed")))
                stack.enter_context(patch.object(module.contract_status, "run_backtest", return_value=(True, "backtest passed")))
                stack.enter_context(patch.object(module.contract_status, "build_categories", return_value=[]))
                stack.enter_context(redirect_stdout(output))
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                    disable_auto_start_for_launch=True,
                )

        self.assertEqual(exit_code, 0)
        stop_processes.assert_called_once_with([111])
        launch_shortcut.assert_called_once_with(
            "C:/Users/example/Desktop/Alpaca Paper Trader.lnk",
            disable_auto_start_for_launch=True,
        )
        self.assertIn("saved auto-start settings will be left unchanged", output.getvalue())

    def test_execute_fails_when_auto_start_override_does_not_hold(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0),
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}),
                patch.object(module, "live_process_pids", return_value=[111]),
                patch.object(module, "stop_processes", return_value=True),
                patch.object(module, "launch_shortcut"),
                patch.object(module, "verify_until_passes", return_value={"ok": True, "summary": {}, "checks": []}),
                patch.object(module, "verify_auto_start_override", return_value=(False, "override failed")),
                patch.object(module.verify_ui_display, "collect_rendered_payload") as ui_collect,
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                    disable_auto_start_for_launch=True,
                )

        self.assertEqual(exit_code, 1)
        ui_collect.assert_not_called()
        self.assertIn("override failed", output.getvalue())

    def test_launch_shortcut_restores_auto_start_environment_after_override(self) -> None:
        module = load_cutover_module()
        original_startfile = getattr(module.os, "startfile", None)
        module.os.startfile = lambda _path: self.assertEqual(module.os.environ.get(module.AUTO_START_OVERRIDE_ENV), "1")
        module.os.environ[module.AUTO_START_OVERRIDE_ENV] = "previous"
        try:
            module.launch_shortcut("C:/Users/example/Desktop/Alpaca Paper Trader.lnk", disable_auto_start_for_launch=True)
            self.assertEqual(module.os.environ.get(module.AUTO_START_OVERRIDE_ENV), "previous")
        finally:
            if original_startfile is None:
                delattr(module.os, "startfile")
            else:
                module.os.startfile = original_startfile
            module.os.environ.pop(module.AUTO_START_OVERRIDE_ENV, None)

    def test_auto_start_override_verifier_reads_sanitized_account_state(self) -> None:
        module = load_cutover_module()
        payload = {
            "account_states": [
                {"selected": {"trading_enabled": False}},
                {"selected": {"trading_enabled": False}},
                {"selected": {"trading_enabled": False}},
            ],
            "state": {"accounts": []},
        }
        with patch.object(module.verify_live_contract, "collect_live_payload", return_value=payload):
            passed, message = module.verify_auto_start_override("http://127.0.0.1:8765", 3)

        self.assertTrue(passed)
        self.assertIn("inspected=3/3", message)

    def test_auto_start_override_verifier_fails_on_enabled_account(self) -> None:
        module = load_cutover_module()
        payload = {
            "account_states": [
                {"selected": {"trading_enabled": False}},
                {"selected": {"trading_enabled": True}},
                {"selected": {"trading_enabled": False}},
            ],
            "state": {"accounts": []},
        }
        with patch.object(module.verify_live_contract, "collect_live_payload", return_value=payload):
            passed, message = module.verify_auto_start_override("http://127.0.0.1:8765", 3)

        self.assertFalse(passed)
        self.assertIn("trading_enabled_accounts=2", message)

    def test_auto_start_override_verifier_falls_back_to_account_summaries(self) -> None:
        module = load_cutover_module()
        payload = {
            "account_states": [],
            "state": {
                "accounts": [
                    {"trading_enabled": False},
                    {"trading_enabled": False},
                    {"trading_enabled": False},
                ]
            },
        }
        with patch.object(module.verify_live_contract, "collect_live_payload", return_value=payload):
            passed, message = module.verify_auto_start_override("http://127.0.0.1:8765", 3)

        self.assertTrue(passed)
        self.assertIn("inspected=3/3", message)

    def test_execute_aborts_before_stop_when_auto_start_status_is_unknown(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0) as backup,
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": False, "accounts": 0, "auto_connect_count": 0, "auto_start_count": 0, "error": "read failed"}),
                patch.object(module, "stop_processes") as stop_processes,
                patch.object(module, "launch_shortcut") as launch_shortcut,
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                )

        self.assertEqual(exit_code, 1)
        backup.assert_called_once_with(execute=True, backup_root=backup_root)
        stop_processes.assert_not_called()
        launch_shortcut.assert_not_called()
        self.assertIn("auto-start behavior is unknown", output.getvalue())

    def test_execute_reports_success_when_only_fresh_replay_tape_is_pending(self) -> None:
        module = load_cutover_module()
        output = io.StringIO()
        replay_category = module.contract_status.Category("replay_backtester", False, ["fresh tape pending"])
        with tempfile.TemporaryDirectory() as raw_dir:
            backup_root = Path(raw_dir) / "backups"
            with (
                patch.object(module.pre_live_backup, "build_backup", return_value=0),
                patch.object(module, "shortcut_path", return_value="C:/Users/example/Desktop/Alpaca Paper Trader.lnk"),
                patch.object(module.verify_live_contract, "read_shortcut_metadata", return_value={"exists": True}),
                patch.object(module.verify_live_contract, "validate_shortcut_metadata", return_value=(True, [], {})),
                patch.object(module, "saved_auto_start_summary", return_value={"settings_read_ok": True, "accounts": 3, "auto_connect_count": 3, "auto_start_count": 2, "error": ""}),
                patch.object(module, "live_process_pids", return_value=[111]),
                patch.object(module, "stop_processes", return_value=True),
                patch.object(module, "launch_shortcut"),
                patch.object(module, "verify_until_passes", return_value={"ok": True, "summary": {}, "checks": []}),
                patch.object(module.verify_ui_display, "collect_rendered_payload", return_value=({"accounts": []}, {})),
                patch.object(module.verify_ui_display, "verify_rendered_payload", return_value={"ok": True, "summary": {}, "checks": []}),
                patch.object(module.contract_status, "run_layout_check", return_value=(True, "layout passed")),
                patch.object(module.contract_status, "run_app_data_preservation_check", return_value=(True, "preservation passed")),
                patch.object(module.contract_status, "run_audit_log_check", return_value=(True, "audit passed")),
                patch.object(module.contract_status, "run_frontend_state_coordination_check", return_value=(True, "frontend state passed")),
                patch.object(module.contract_status, "run_strategy_contract_check", return_value=(True, "strategy passed")),
                patch.object(module.contract_status, "run_regression", return_value=(True, "regression passed")),
                patch.object(module.contract_status, "run_backtest", return_value=(False, "fresh tape pending")),
                patch.object(module.contract_status, "build_categories", return_value=[replay_category]),
                redirect_stdout(output),
            ):
                exit_code = module.run_cutover(
                    execute=True,
                    url="http://127.0.0.1:8765",
                    expected_accounts=3,
                    timeout_seconds=1,
                    backup_root=backup_root,
                    allow_auto_start=True,
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("Live cutover completed", output.getvalue())
        self.assertIn("full acceptance is still pending", output.getvalue())


if __name__ == "__main__":
    unittest.main()
