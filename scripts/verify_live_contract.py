from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from verify_desktop_shortcut import read_shortcut_metadata, validate_shortcut_metadata


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_URL = "http://127.0.0.1:8765"
EXPECTED_TOP_VOLUME_SOURCE = "alpaca_most_actives_volume"
VBS_LAUNCHER = REPO_ROOT / "Launch Alpaca Paper Trader.vbs"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "severity": self.severity,
        }


def app_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader"


def instance_path() -> Path:
    return app_data_dir() / "instance.json"


def load_instance(path: Path | None = None) -> dict[str, Any]:
    target = path or instance_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return {}


def fetch_json(url: str, timeout: float = 4.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status >= 400:
                return {"_error": f"HTTP {response.status}"}
            raw = json.loads(response.read().decode("utf-8"))
            return raw if isinstance(raw, dict) else {"_error": "JSON response was not an object"}
    except urllib.error.HTTPError as exc:
        return {"_error": f"HTTP {exc.code}"}
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"_error": str(exc) or exc.__class__.__name__}


def dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
        if not text or text == "-":
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def blank(value: Any) -> bool:
    return str(value or "").strip() == ""


def near(left: Decimal, right: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    return abs(left - right) <= tolerance


def check_name(index: int, suffix: str) -> str:
    return f"account_{index}.{suffix}"


def account_label(index: int) -> str:
    return f"account {index}"


def add_check(checks: list[Check], name: str, ok: bool, detail: str, severity: str = "error") -> None:
    checks.append(Check(name=name, ok=ok, detail=detail, severity=severity))


def parse_process_pids(raw: Any) -> list[int] | None:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    pids: list[int] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        command_line = str(item.get("command_line") or item.get("CommandLine") or "")
        if "--smoke" in command_line.lower():
            continue
        try:
            pid = int(item.get("pid") or item.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.append(pid)
    return pids


def collect_process_pids(repo_root: Path = REPO_ROOT) -> list[int] | None:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    powershell = Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = f"""
$ErrorActionPreference = 'Stop'
$root = @'
{repo_root}
'@.ToLowerInvariant()
$items = Get-CimInstance Win32_Process |
  Where-Object {{
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and
    (($_.CommandLine -as [string]).ToLowerInvariant().Contains('python_app\\run.py')) -and
    (($_.CommandLine -as [string]).ToLowerInvariant().Contains($root))
  }} |
  ForEach-Object {{ [pscustomobject]@{{ pid = $_.ProcessId; command_line = $_.CommandLine }} }}
@($items) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            [
                str(powershell) if powershell.exists() else "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return parse_process_pids(raw)


def parse_pid_list(raw: Any) -> list[int] | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return [raw] if raw > 0 else []
    if not isinstance(raw, list):
        return None
    pids: list[int] = []
    for item in raw:
        try:
            pid = int(item)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            pids.append(pid)
    return sorted(set(pids))


def collect_listener_pids(base_url: str) -> list[int] | None:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    powershell = Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    escaped_host = host.replace("'", "''")
    command = f"""
$ErrorActionPreference = 'SilentlyContinue'
$hostName = '{escaped_host}'
$port = {int(port)}
$listeners = @()
try {{
  $listeners = Get-NetTCPConnection -LocalAddress $hostName -LocalPort $port -State Listen -ErrorAction Stop |
    ForEach-Object {{ [int]$_.OwningProcess }}
}} catch {{
  $listeners = @()
}}
if (@($listeners).Count -eq 0) {{
  $pattern = [regex]::Escape($hostName + ':' + $port) + '\\s+.*LISTENING\\s+(\\d+)'
  $listeners = netstat -ano -p tcp |
    ForEach-Object {{
      if ($_ -match $pattern) {{ [int]$matches[1] }}
    }}
}}
@($listeners | Sort-Object -Unique) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            [
                str(powershell) if powershell.exists() else "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return parse_pid_list(raw)


def inspect_launcher_contract(path: Path = VBS_LAUNCHER) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"exists": False, "error": str(exc)}
    return {
        "exists": True,
        "uses_health_currentness": (
            "/api/health" in text
            and "IsCurrentHealth" in text
            and "sourceRoot" in text
            and "DeleteInstanceIfUrl" in text
        ),
        "preserves_instance_while_starting": "If Len(healthText) = 0 Then Exit Function" in text,
        "hidden_backend_launch": (
            ".venv\\Scripts\\pythonw.exe" in text
            and 'shell.Run Quote(launcherPython) & " " & Quote(pythonRun) & " --no-browser", 0, False' in text
        ),
        "hidden_smoke_check": (
            "smokeExit = shell.Run" in text
            and '" --smoke", 0, True)' in text
        ),
        "edge_app_mode": (
            "--app=" in text
            and "--user-data-dir=" in text
            and "EdgeAppIconProfile" in text
            and "--window-size=1280,900" in text
        ),
    }


def collect_live_payload(base_url: str, timeout: float = 4.0) -> dict[str, Any]:
    base = base_url.rstrip("/")
    state = fetch_json(f"{base}/api/state", timeout=timeout)
    account_states: list[dict[str, Any]] = []
    account_dashboards: list[dict[str, Any]] = []
    for account in state.get("accounts", []) if isinstance(state.get("accounts"), list) else []:
        if not isinstance(account, dict):
            continue
        account_id = str(account.get("account_id") or "")
        if not account_id:
            continue
        query = urllib.parse.urlencode({"account_id": account_id})
        detail = fetch_json(f"{base}/api/state?{query}", timeout=timeout)
        if detail:
            account_states.append(detail)
        dashboard_detail = fetch_json(f"{base}/api/dashboard?{query}", timeout=timeout)
        if dashboard_detail:
            account_dashboards.append(dashboard_detail)

    shortcut_ok = False
    shortcut_issues: list[str] = []
    try:
        metadata = read_shortcut_metadata()
        shortcut_ok, shortcut_issues, _expected = validate_shortcut_metadata(metadata)
    except Exception as exc:  # pragma: no cover - platform/COM availability varies
        shortcut_issues = [str(exc) or exc.__class__.__name__]

    return {
        "health": fetch_json(f"{base}/api/health", timeout=timeout),
        "state": state,
        "dashboard": fetch_json(f"{base}/api/dashboard", timeout=timeout),
        "settings": fetch_json(f"{base}/api/settings", timeout=timeout),
        "account_states": account_states,
        "account_dashboards": account_dashboards,
        "instance": load_instance(),
        "instance_path": str(instance_path()),
        "shortcut_ok": shortcut_ok,
        "shortcut_issues": shortcut_issues,
        "launcher_contract": inspect_launcher_contract(),
        "process_pids": collect_process_pids(),
        "listener_pids": collect_listener_pids(base),
    }


def account_state_for_index(payload: dict[str, Any], index: int) -> dict[str, Any]:
    account_states = payload.get("account_states")
    if not isinstance(account_states, list) or index >= len(account_states):
        return {}
    detail = account_states[index]
    return detail if isinstance(detail, dict) else {}


def account_dashboard_for_index(payload: dict[str, Any], index: int) -> dict[str, Any]:
    account_dashboards = payload.get("account_dashboards")
    if not isinstance(account_dashboards, list) or index >= len(account_dashboards):
        return {}
    detail = account_dashboards[index]
    return detail if isinstance(detail, dict) else {}


def selected_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    selected = detail.get("selected")
    return selected if isinstance(selected, dict) else {}


def check_trade_size(checks: list[Check], config: dict[str, Any], index: int) -> None:
    mode = str(config.get("trade_size_mode") or "").strip()
    notional = dec(config.get("max_trade_notional")) or Decimal("0")
    percent = dec(config.get("max_trade_percent")) or Decimal("0")
    if mode == "percent":
        ok = percent > 0 and notional == 0
        detail = f"{account_label(index)} percent sizing has percent={percent} and notional={notional}"
    elif mode == "notional":
        ok = notional > 0 and percent == 0
        detail = f"{account_label(index)} notional sizing has notional={notional} and percent={percent}"
    elif mode == "exposure_slot":
        ok = notional == 0 and percent == 0
        detail = f"{account_label(index)} exposure-slot sizing has no percent/notional cap"
    else:
        ok = False
        detail = f"{account_label(index)} has invalid trade_size_mode={mode or 'missing'}"
    add_check(checks, check_name(index, "sizing_mode"), ok, detail)


def check_daily_pl(checks: list[Check], selected: dict[str, Any], index: int) -> None:
    account = selected.get("account")
    account = account if isinstance(account, dict) else {}
    required = (
        "daily_pl_raw",
        "daily_pl_display",
        "daily_pl_pct_raw",
        "daily_pl_pct_display",
        "daily_pl_session_date",
        "daily_pl_account_basis_raw",
        "daily_pl_source",
        "realized_pl_raw",
        "realized_pl_display",
        "realized_pl_session_date",
    )
    missing = [key for key in required if blank(account.get(key))]
    add_check(
        checks,
        check_name(index, "daily_pl_fields"),
        not missing,
        f"{account_label(index)} daily P/L fields present" if not missing else f"{account_label(index)} missing {', '.join(missing)}",
    )

    market_clock = selected.get("market_clock") if isinstance(selected.get("market_clock"), dict) else {}
    clock_session = str(market_clock.get("session_date") or "").strip()
    daily_session = str(account.get("daily_pl_session_date") or "").strip()
    realized_session = str(account.get("realized_pl_session_date") or "").strip()
    add_check(
        checks,
        check_name(index, "daily_pl_session_date"),
        bool(clock_session) and daily_session == clock_session,
        f"{account_label(index)} daily P/L session={daily_session or 'missing'}, market_clock_session={clock_session or 'missing'}",
    )
    add_check(
        checks,
        check_name(index, "realized_pl_session_date"),
        bool(clock_session) and realized_session == clock_session,
        f"{account_label(index)} realized P/L session={realized_session or 'missing'}, market_clock_session={clock_session or 'missing'}",
    )

    source = str(account.get("daily_pl_source") or "").strip()
    source_ok = source == "alpaca_portfolio_history"
    add_check(
        checks,
        check_name(index, "daily_pl_source"),
        source_ok,
        f"{account_label(index)} daily P/L source is {source or 'missing'}",
    )

    daily_raw = dec(account.get("daily_pl_raw"))
    daily_pct = dec(account.get("daily_pl_pct_raw"))
    basis = dec(account.get("daily_pl_account_basis_raw"))
    if daily_raw is None or daily_pct is None or basis is None or basis <= 0:
        add_check(
            checks,
            check_name(index, "daily_pl_percent_source"),
            False,
            f"{account_label(index)} does not expose usable source P/L, basis, and percent values",
        )
        return

    expected_pct = daily_raw / basis * Decimal("100")
    nonzero_source_not_flat = daily_raw != 0 and daily_pct != 0
    add_check(
        checks,
        check_name(index, "daily_pl_percent_source"),
        source_ok and near(daily_pct, expected_pct, Decimal("0.05")) and (daily_raw == 0 or nonzero_source_not_flat),
        f"{account_label(index)} daily P/L percent is tied to portfolio-history source basis",
    )


def check_account_surfaces(
    checks: list[Check],
    selected: dict[str, Any],
    detail: dict[str, Any],
    dashboard: dict[str, Any],
    index: int,
) -> None:
    trading_enabled = selected.get("trading_enabled")
    add_check(
        checks,
        check_name(index, "trading_enabled"),
        isinstance(trading_enabled, bool),
        f"{account_label(index)} trading_enabled is a boolean",
    )
    market_clock = selected.get("market_clock")
    clock_detail = "missing"
    if isinstance(market_clock, dict):
        clock_detail = (
            f"is_open={market_clock.get('is_open')!r}, "
            f"status={market_clock.get('status') or 'missing'}, "
            f"session={market_clock.get('session_date') or 'missing'}, "
            f"next_open={market_clock.get('next_open') or 'missing'}, "
            f"next_close={market_clock.get('next_close') or 'missing'}"
        )
    add_check(
        checks,
        check_name(index, "market_clock"),
        isinstance(market_clock, dict) and isinstance(market_clock.get("is_open"), bool) and not blank(market_clock.get("status")),
        f"{account_label(index)} market clock {clock_detail}",
    )

    list_fields = ("positions", "orders", "protection", "trade_history", "order_intents", "strategy", "logs", "trading_symbols")
    missing_lists = [field for field in list_fields if not isinstance(selected.get(field), list)]
    add_check(
        checks,
        check_name(index, "state_surfaces"),
        not missing_lists,
        f"{account_label(index)} state lists present" if not missing_lists else f"{account_label(index)} missing list fields: {', '.join(missing_lists)}",
    )

    replay = detail.get("replay")
    replay_ok = isinstance(replay, dict) and isinstance(replay.get("events"), list) and not blank(replay.get("path"))
    add_check(
        checks,
        check_name(index, "replay_surface"),
        replay_ok,
        f"{account_label(index)} exposes replay path and events list",
    )

    dashboard_error = str(dashboard.get("_error") or "")
    dashboard_ok = (
        not dashboard_error
        and isinstance(dashboard.get("market_clock"), dict)
        and isinstance(dashboard.get("top_volume"), list)
        and isinstance(dashboard.get("halt_summary"), dict)
        and isinstance(dashboard.get("market_stream"), dict)
        and isinstance(dashboard.get("replay"), dict)
    )
    add_check(
        checks,
        check_name(index, "dashboard_surface"),
        dashboard_ok,
        f"{account_label(index)} dashboard surface available" if dashboard_ok else f"{account_label(index)} dashboard surface missing or errored",
    )


def verify_payload(
    payload: dict[str, Any],
    *,
    expected_accounts: int = 3,
    expected_url: str = DEFAULT_URL,
    require_connected: bool = True,
) -> dict[str, Any]:
    checks: list[Check] = []
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    dashboard = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else {}
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
    top_rows = dashboard.get("top_volume") if isinstance(dashboard.get("top_volume"), list) else []
    top_symbols = {
        str(row.get("symbol") or "").strip().upper()
        for row in top_rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }
    market_stream = dashboard.get("market_stream") if isinstance(dashboard.get("market_stream"), dict) else {}

    add_check(checks, "shortcut.path", bool(payload.get("shortcut_ok")), "desktop shortcut points to wscript/VBS path")
    if payload.get("shortcut_issues"):
        add_check(checks, "shortcut.issues", False, "; ".join(str(item) for item in payload.get("shortcut_issues", [])[:3]))
    launcher_contract = payload.get("launcher_contract") if isinstance(payload.get("launcher_contract"), dict) else {}
    add_check(
        checks,
        "launcher.vbs_exists",
        bool(launcher_contract.get("exists")),
        "VBS launcher file is present",
    )
    add_check(
        checks,
        "launcher.health_currentness",
        bool(launcher_contract.get("uses_health_currentness")),
        "VBS launcher checks /api/health currentness before reuse",
    )
    add_check(
        checks,
        "launcher.instance_startup_guard",
        bool(launcher_contract.get("preserves_instance_while_starting")),
        "VBS launcher keeps instance.json while the backend is still starting",
    )
    add_check(
        checks,
        "launcher.hidden_backend",
        bool(launcher_contract.get("hidden_backend_launch")),
        "VBS launcher starts backend hidden with --no-browser",
    )
    add_check(
        checks,
        "launcher.hidden_smoke",
        bool(launcher_contract.get("hidden_smoke_check")),
        "VBS launcher runs startup smoke check hidden",
    )
    add_check(
        checks,
        "launcher.edge_app_mode",
        bool(launcher_contract.get("edge_app_mode")),
        "VBS launcher opens Edge app-mode window",
    )

    health_error = str(health.get("_error") or "")
    add_check(checks, "backend.health_reachable", not health_error, "health endpoint reachable" if not health_error else health_error)
    add_check(checks, "backend.current", health.get("current") is True, f"health current={health.get('current')!r}, status={health.get('status')!r}")
    add_check(checks, "backend.url", str(health.get("url") or "").rstrip("/") == expected_url.rstrip("/"), f"health url should be {expected_url}")
    add_check(
        checks,
        "backend.paper_only",
        health.get("paper_trading_only") is True and str(health.get("broker_mode") or "").lower() == "paper",
        f"paper_trading_only={health.get('paper_trading_only')!r}, broker_mode={health.get('broker_mode')!r}",
    )
    add_check(checks, "instance.present", bool(instance), f"instance.json present at {payload.get('instance_path')}")
    add_check(checks, "instance.url", str(instance.get("url") or "").rstrip("/") == expected_url.rstrip("/"), f"instance url should be {expected_url}")
    if health.get("pid") and instance.get("pid"):
        add_check(checks, "instance.pid", str(health.get("pid")) == str(instance.get("pid")), "instance pid matches health pid")
    else:
        add_check(checks, "instance.pid", False, "health and instance pid must both be present")

    listener_pids = payload.get("listener_pids")
    process_pids = payload.get("process_pids")
    if isinstance(listener_pids, list):
        add_check(checks, "backend.single_process", len(listener_pids) == 1, f"found {len(listener_pids)} listening backend process(es)")
        if health.get("pid"):
            add_check(
                checks,
                "backend.health_pid_process",
                int(health.get("pid") or 0) in {int(pid) for pid in listener_pids},
                "health pid owns the expected backend listener",
            )
    elif isinstance(process_pids, list):
        add_check(checks, "backend.single_process", len(process_pids) == 1, f"found {len(process_pids)} repo launcher process(es)")
        if health.get("pid"):
            add_check(
                checks,
                "backend.health_pid_process",
                int(health.get("pid") or 0) in {int(pid) for pid in process_pids},
                "health pid is the repo launcher process",
            )
    else:
        add_check(checks, "backend.process_scan", False, "could not inspect local launcher processes", severity="warning")

    accounts = state.get("accounts") if isinstance(state.get("accounts"), list) else []
    add_check(checks, "accounts.count", len(accounts) >= expected_accounts, f"loaded {len(accounts)} account(s), expected at least {expected_accounts}")
    settings_accounts = settings.get("accounts") if isinstance(settings.get("accounts"), list) else []
    add_check(checks, "settings.accounts_count", len(settings_accounts) >= expected_accounts, f"settings loaded {len(settings_accounts)} account(s)")

    settings_diag = state.get("settings_diagnostics") or settings.get("settings_diagnostics") or {}
    settings_error_count = int((settings_diag if isinstance(settings_diag, dict) else {}).get("error_count") or 0)
    add_check(checks, "settings.load_errors", settings_error_count == 0, f"settings diagnostic errors={settings_error_count}")

    runtime_diag = state.get("runtime_diagnostics") or health.get("runtime_diagnostics") or {}
    runtime_error_count = int((runtime_diag if isinstance(runtime_diag, dict) else {}).get("error_count") or 0)
    add_check(checks, "runtime.errors", runtime_error_count == 0, f"runtime diagnostic errors={runtime_error_count}")

    stream_status = str(market_stream.get("status") or "").strip()
    stream_connected = market_stream.get("connected")
    try:
        dashboard_symbol_count = int(market_stream.get("dashboard_symbols") or 0)
    except (TypeError, ValueError):
        dashboard_symbol_count = 0
    try:
        bar_symbol_count = int(market_stream.get("bar_symbols") or 0)
    except (TypeError, ValueError):
        bar_symbol_count = 0
    stream_error = str(market_stream.get("last_error") or "").strip()
    add_check(
        checks,
        "market_stream.surface",
        isinstance(market_stream, dict) and bool(market_stream),
        "market stream health surface is present",
    )
    add_check(
        checks,
        "market_stream.status",
        bool(stream_status) and isinstance(stream_connected, bool),
        f"market stream status={stream_status or 'missing'}, connected={stream_connected!r}",
    )
    add_check(
        checks,
        "market_stream.error",
        blank(stream_error),
        "market stream last_error is empty" if blank(stream_error) else "market stream last_error is set",
    )
    add_check(
        checks,
        "market_stream.dashboard_symbols",
        len(top_rows) == 25 and dashboard_symbol_count == len(top_rows),
        f"market stream dashboard_symbols={dashboard_symbol_count}, top_volume_rows={len(top_rows)}",
    )
    add_check(
        checks,
        "market_stream.bar_symbols",
        dashboard_symbol_count > 0 and bar_symbol_count >= dashboard_symbol_count,
        f"market stream bar_symbols={bar_symbol_count}, dashboard_symbols={dashboard_symbol_count}",
    )

    for index, summary in enumerate(accounts, start=1):
        if not isinstance(summary, dict):
            add_check(checks, check_name(index, "summary"), False, f"{account_label(index)} summary is not an object")
            continue
        detail = account_state_for_index(payload, index - 1)
        account_dashboard = account_dashboard_for_index(payload, index - 1)
        selected = selected_from_detail(detail) or summary
        connected = bool(selected.get("connected", summary.get("connected")))
        add_check(
            checks,
            check_name(index, "connected"),
            connected or not require_connected,
            f"{account_label(index)} connected={connected}",
        )
        check_account_surfaces(checks, selected, detail, account_dashboard, index)
        config = selected.get("config") if isinstance(selected.get("config"), dict) else {}
        check_trade_size(checks, config, index)
        check_daily_pl(checks, selected, index)
        if bool(config.get("use_top_volume_symbols", True)):
            symbol_source = str(selected.get("symbol_source") or summary.get("symbol_source") or "")
            count = int(selected.get("trading_symbol_count") or summary.get("trading_symbol_count") or 0)
            inverse_mode = str(config.get("inverse_etf_mode") or "allow").strip().lower()
            trading_symbols = selected.get("trading_symbols") if isinstance(selected.get("trading_symbols"), list) else []
            if inverse_mode == "inverse_only":
                universe_ok = symbol_source == "inverse_only" and count > 0
                universe_detail = f"{account_label(index)} symbol_source={symbol_source or 'missing'}, trading_symbol_count={count}"
            else:
                listed_symbols = {
                    str(symbol or "").strip().upper()
                    for symbol in trading_symbols
                    if str(symbol or "").strip()
                }
                exact_count_ok = len(top_rows) == 25 and count == len(top_symbols)
                if listed_symbols:
                    universe_ok = (
                        symbol_source == "top_volume"
                        and exact_count_ok
                        and listed_symbols == top_symbols
                    )
                    extra_count = len(listed_symbols - top_symbols)
                    missing_count = len(top_symbols - listed_symbols)
                    universe_detail = (
                        f"{account_label(index)} symbol_source={symbol_source or 'missing'}, "
                        f"trading_symbol_count={count}, extras={extra_count}, missing={missing_count}"
                    )
                else:
                    universe_ok = symbol_source == "top_volume" and exact_count_ok
                    universe_detail = f"{account_label(index)} symbol_source={symbol_source or 'missing'}, trading_symbol_count={count}"
            add_check(
                checks,
                check_name(index, "top_volume_universe"),
                universe_ok,
                universe_detail,
            )

    top_source = str(dashboard.get("top_volume_source") or "")
    add_check(checks, "top_volume.source", top_source == EXPECTED_TOP_VOLUME_SOURCE, f"top-volume source={top_source or 'missing'}")
    add_check(checks, "top_volume.count", len(top_rows) == 25, f"top-volume rows={len(top_rows)}")
    add_check(checks, "top_volume.error", blank(dashboard.get("top_volume_error")), f"top-volume error={dashboard.get('top_volume_error') or ''}")
    cache_seconds = dec(dashboard.get("top_volume_cache_seconds"))
    add_check(
        checks,
        "top_volume.cache_seconds",
        cache_seconds is not None and cache_seconds <= Decimal("60"),
        f"top-volume cache seconds={cache_seconds}",
    )

    ok = all(check.ok or check.severity == "warning" for check in checks)
    return {
        "ok": ok,
        "summary": {
            "expected_url": expected_url,
            "account_count": len(accounts),
            "top_volume_count": len(top_rows),
            "health_current": health.get("current"),
            "health_status": health.get("status"),
            "health_pid": health.get("pid"),
            "listener_pids": payload.get("listener_pids"),
        },
        "checks": [check.as_dict() for check in checks],
    }


def print_human(report: dict[str, Any]) -> None:
    print("Live contract verification")
    print(f"  ok: {report['ok']}")
    summary = report.get("summary", {})
    print(f"  backend: {summary.get('expected_url')} current={summary.get('health_current')} status={summary.get('health_status')} pid={summary.get('health_pid')} listeners={summary.get('listener_pids')}")
    print(f"  accounts: {summary.get('account_count')}")
    print(f"  top-volume rows: {summary.get('top_volume_count')}")
    failures = [item for item in report.get("checks", []) if not item.get("ok")]
    if not failures:
        print("  failures: none")
        return
    print("  failures:")
    for item in failures:
        prefix = "warning" if item.get("severity") == "warning" else "error"
        print(f"    - [{prefix}] {item.get('name')}: {item.get('detail')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only, sanitized verifier for the live Alpaca Paper Trader desktop contract."
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="Expected local backend URL.")
    parser.add_argument("--expected-accounts", type=int, default=3)
    parser.add_argument("--allow-disconnected", action="store_true", help="Do not fail disconnected accounts.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    payload = collect_live_payload(args.url)
    report = verify_payload(
        payload,
        expected_accounts=args.expected_accounts,
        expected_url=args.url,
        require_connected=not args.allow_disconnected,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
