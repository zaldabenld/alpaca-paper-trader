from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pre_live_backup
import contract_status
import verify_ui_display
import verify_live_contract


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8765"
AUTO_START_OVERRIDE_ENV = "ALPACA_TRADER_DISABLE_AUTO_START"


def live_process_pids() -> list[int]:
    pids = verify_live_contract.collect_process_pids(REPO_ROOT)
    if not isinstance(pids, list):
        return []
    own_pid = os.getpid()
    return [int(pid) for pid in pids if int(pid) > 0 and int(pid) != own_pid]


def shortcut_path() -> str:
    metadata = verify_live_contract.read_shortcut_metadata()
    if not metadata.get("exists"):
        return ""
    return str(metadata.get("path") or "")


def saved_auto_start_summary() -> dict[str, Any]:
    path = pre_live_backup.app_data_dir() / "python-settings.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "settings_read_ok": False,
            "settings_path": str(path),
            "accounts": 0,
            "auto_connect_count": 0,
            "auto_start_count": 0,
            "error": str(exc) or exc.__class__.__name__,
        }
    accounts = raw.get("accounts") if isinstance(raw, dict) else []
    if not isinstance(accounts, list):
        accounts = []
    auto_connect_count = sum(
        1
        for item in accounts
        if isinstance(item, dict) and bool(item.get("auto_connect", item.get("remember", True)))
    )
    auto_start_count = sum(1 for item in accounts if isinstance(item, dict) and bool(item.get("auto_start_trading", False)))
    return {
        "settings_read_ok": True,
        "settings_path": str(path),
        "accounts": len(accounts),
        "auto_connect_count": auto_connect_count,
        "auto_start_count": auto_start_count,
        "error": "",
    }


def stop_processes(pids: list[int], timeout_seconds: float = 10.0) -> bool:
    if not pids:
        return True
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.monotonic() + timeout_seconds
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        running = set(live_process_pids())
        remaining &= running
        if not remaining:
            return True
        time.sleep(0.25)
    return not (remaining & set(live_process_pids()))


def launch_shortcut(path: str, *, disable_auto_start_for_launch: bool = False) -> None:
    if not path:
        raise RuntimeError("Desktop shortcut was not found.")
    if not hasattr(os, "startfile"):
        raise RuntimeError("Shortcut launch requires Windows os.startfile.")
    previous = os.environ.get(AUTO_START_OVERRIDE_ENV)
    if disable_auto_start_for_launch:
        os.environ[AUTO_START_OVERRIDE_ENV] = "1"
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    finally:
        if disable_auto_start_for_launch:
            if previous is None:
                os.environ.pop(AUTO_START_OVERRIDE_ENV, None)
            else:
                os.environ[AUTO_START_OVERRIDE_ENV] = previous


def verify_until_passes(url: str, expected_accounts: int, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_report: dict[str, Any] = {}
    while time.monotonic() < deadline:
        payload = verify_live_contract.collect_live_payload(url)
        last_report = verify_live_contract.verify_payload(
            payload,
            expected_accounts=expected_accounts,
            expected_url=url,
        )
        if last_report.get("ok"):
            return last_report
        time.sleep(1)
    return last_report


def verify_auto_start_override(url: str, expected_accounts: int) -> tuple[bool, str]:
    payload = verify_live_contract.collect_live_payload(url)
    states = payload.get("account_states")
    summaries = payload.get("state", {}).get("accounts") if isinstance(payload.get("state"), dict) else []
    if not isinstance(states, list):
        states = []
    if not isinstance(summaries, list):
        summaries = []

    enabled: list[int] = []
    unknown: list[int] = []
    inspected = 0
    for index in range(expected_accounts):
        detail = states[index] if index < len(states) and isinstance(states[index], dict) else {}
        selected = verify_live_contract.selected_from_detail(detail)
        if not selected and index < len(summaries) and isinstance(summaries[index], dict):
            selected = summaries[index]
        value = selected.get("trading_enabled") if isinstance(selected, dict) else None
        if isinstance(value, bool):
            inspected += 1
            if value:
                enabled.append(index + 1)
        else:
            unknown.append(index + 1)

    ok = inspected >= expected_accounts and not enabled and not unknown
    detail = (
        f"auto-start override {'passed' if ok else 'failed'}: "
        f"inspected={inspected}/{expected_accounts}, "
        f"trading_enabled_accounts={','.join(str(item) for item in enabled) or 'none'}, "
        f"unknown_accounts={','.join(str(item) for item in unknown) or 'none'}"
    )
    return ok, detail


def run_cutover(
    *,
    execute: bool,
    url: str,
    expected_accounts: int,
    timeout_seconds: float,
    backup_root: Path,
    allow_auto_start: bool = False,
    disable_auto_start_for_launch: bool = False,
) -> int:
    print(f"Mode: {'execute' if execute else 'dry-run'}")
    print(f"Repo: {REPO_ROOT}")
    print()

    print("Step 1: pre-live app-data backup")
    backup_exit = pre_live_backup.build_backup(execute=execute, backup_root=backup_root)
    if backup_exit != 0:
        return backup_exit
    print()

    path = shortcut_path()
    shortcut_metadata = verify_live_contract.read_shortcut_metadata()
    shortcut_ok, shortcut_issues, _expected = verify_live_contract.validate_shortcut_metadata(shortcut_metadata)
    print("Step 2: desktop shortcut")
    print(f"  shortcut: {path or 'missing'}")
    print(f"  valid: {shortcut_ok}")
    for issue in shortcut_issues:
        print(f"  issue: {issue}")
    if not shortcut_ok:
        return 1
    print()

    auto_start = saved_auto_start_summary()
    auto_start_count = int(auto_start.get("auto_start_count") or 0)
    print("Step 3: saved auto-start preflight")
    print(f"  settings readable: {bool(auto_start.get('settings_read_ok'))}")
    print(f"  accounts: {int(auto_start.get('accounts') or 0)}")
    print(f"  auto-connect enabled: {int(auto_start.get('auto_connect_count') or 0)}")
    print(f"  auto-start trading enabled: {auto_start_count}")
    print(f"  launch auto-start override: {bool(disable_auto_start_for_launch)}")
    if auto_start.get("error"):
        print(f"  issue: {auto_start.get('error')}")
    if execute and not bool(auto_start.get("settings_read_ok")):
        print()
        print("Execute aborted: saved settings could not be read, so auto-start behavior is unknown.")
        return 1
    if execute and auto_start_count > 0 and not allow_auto_start and not disable_auto_start_for_launch:
        print()
        print(
            "Execute aborted: saved accounts would auto-start paper trading on launch. "
            "Re-run with --allow-auto-start only after explicitly approving that behavior, "
            "or use --disable-auto-start-for-launch to suppress auto-start for this relaunch "
            "without changing saved settings."
        )
        return 1
    if execute and auto_start_count > 0 and disable_auto_start_for_launch:
        print("  saved auto-start settings will be left unchanged; this relaunch will set a process-level skip flag.")
    print()

    pids = live_process_pids()
    print("Step 4: current repo launcher processes")
    print(f"  count: {len(pids)}")
    print(f"  pids: {', '.join(str(pid) for pid in pids) if pids else 'none'}")
    if not execute:
        print()
        print(
            "Dry run only. Re-run with --execute after approving live backup, stop, relaunch, "
            "verification, and either saved auto-start behavior or the launch auto-start override shown above."
        )
        return 0

    print("  stopping current repo launcher processes...")
    if not stop_processes(pids):
        print("  stop failed or timed out; launch was not attempted.")
        return 1
    print("  stopped.")
    print()

    print("Step 5: launch through desktop shortcut")
    launch_shortcut(path, disable_auto_start_for_launch=disable_auto_start_for_launch)
    print("  launched; waiting for live verifier")
    print()

    print("Step 6: post-launch live contract verifier")
    report = verify_until_passes(url, expected_accounts, timeout_seconds)
    verify_live_contract.print_human(report)
    if not report.get("ok"):
        return 1
    print()

    if disable_auto_start_for_launch and auto_start_count > 0:
        print("Step 7: launch auto-start override verifier")
        override_ok, override_detail = verify_auto_start_override(url, expected_accounts)
        print(f"  {override_detail}")
        if not override_ok:
            return 1
        print()

    print("Step 8: rendered UI display verifier")
    state, rendered = verify_ui_display.collect_rendered_payload(url, timeout_seconds=timeout_seconds)
    ui_report = verify_ui_display.verify_rendered_payload(
        state,
        rendered,
        expected_accounts=expected_accounts,
    )
    verify_ui_display.print_human(ui_report)
    if not ui_report.get("ok"):
        return 1
    print()

    print("Step 9: aggregate contract status")
    layout_result = contract_status.run_layout_check()
    preservation_result = contract_status.run_app_data_preservation_check()
    audit_result = contract_status.run_audit_log_check()
    frontend_state_result = contract_status.run_frontend_state_coordination_check()
    strategy_result = contract_status.run_strategy_contract_check()
    regression_result = contract_status.run_regression()
    backtest_result = contract_status.run_backtest()
    aggregate = contract_status.build_categories(
        report,
        ui_report,
        layout_result,
        preservation_result,
        frontend_state_result,
        regression_result,
        backtest_result,
        audit_result,
        strategy_result,
    )
    acceptance = contract_status.build_acceptance(aggregate)
    aggregate_report = {
        "ok": all(category.ok for category in aggregate),
        "summary": {
            "url": url,
            "expected_accounts": expected_accounts,
            "live_ok": bool(report.get("ok")),
            "ui_ok": bool(ui_report.get("ok")),
            "layout_included": True,
            "preservation_included": True,
            "audit_included": True,
            "frontend_state_included": True,
            "strategy_contract_included": True,
            "regression_included": True,
            "backtest_included": True,
            "acceptance_ok": all(item.ok for item in acceptance),
        },
        "categories": [category.as_dict() for category in aggregate],
        "acceptance": [item.as_dict() for item in acceptance],
    }
    contract_status.print_human(aggregate_report)
    if aggregate_report.get("ok"):
        return 0
    failing_categories = [category.name for category in aggregate if not category.ok]
    if failing_categories == ["replay_backtester"]:
        print()
        print(
            "Live cutover completed; full acceptance is still pending fresh "
            "alpaca_most_actives_volume replay tape."
        )
        print("Rerun scripts\\contract_status.py --include-regression --include-backtest after market-hours tape is recorded.")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Guarded Alpaca Paper Trader live cutover: backup, stop old repo process, launch shortcut, verify."
    )
    parser.add_argument("--execute", action="store_true", help="Actually back up, stop, launch, and verify.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expected-accounts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--backup-root", type=Path, default=pre_live_backup.DEFAULT_BACKUP_ROOT)
    parser.add_argument(
        "--allow-auto-start",
        action="store_true",
        help="Allow execute mode to launch normally even when saved accounts have auto-start trading enabled.",
    )
    parser.add_argument(
        "--disable-auto-start-for-launch",
        action="store_true",
        help=(
            "Set ALPACA_TRADER_DISABLE_AUTO_START=1 for the relaunched desktop process "
            "without changing saved account settings."
        ),
    )
    args = parser.parse_args(argv)
    return run_cutover(
        execute=bool(args.execute),
        url=args.url,
        expected_accounts=args.expected_accounts,
        timeout_seconds=args.timeout,
        backup_root=args.backup_root,
        allow_auto_start=bool(args.allow_auto_start),
        disable_auto_start_for_launch=bool(args.disable_auto_start_for_launch),
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
