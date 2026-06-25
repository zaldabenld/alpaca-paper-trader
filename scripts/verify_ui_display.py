from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from websockets.sync.client import connect


DEFAULT_URL = "http://127.0.0.1:8765"


@dataclass
class DisplayCheck:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def fetch_state(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/api/state", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_health(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/health", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"_error": "health payload was not an object"}
    except requests.RequestException as exc:
        return {"_error": str(exc)}


def browser_candidates() -> list[Path]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]


def find_browser() -> Path:
    for path in browser_candidates():
        if path.exists():
            return path
    for name in ("msedge", "chrome", "chromium"):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)
    raise RuntimeError("No Edge/Chrome browser executable found for rendered UI verification.")


class CdpClient:
    def __init__(self, websocket_url: str) -> None:
        self.websocket_url = websocket_url
        self._next_id = 1
        self._socket: Any | None = None

    def __enter__(self) -> "CdpClient":
        self._socket = connect(self.websocket_url, open_timeout=5)
        return self

    def __exit__(self, *_args: object) -> None:
        if self._socket is not None:
            self._socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._socket is None:
            raise RuntimeError("CDP socket is not connected.")
        message_id = self._next_id
        self._next_id += 1
        self._socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            raw = json.loads(self._socket.recv())
            if raw.get("id") == message_id:
                if "error" in raw:
                    raise RuntimeError(str(raw["error"]))
                return raw

    def evaluate(self, expression: str) -> Any:
        payload = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        )
        result = payload.get("result", {}).get("result", {})
        if "exceptionDetails" in payload.get("result", {}):
            raise RuntimeError(str(payload["result"]["exceptionDetails"]))
        return result.get("value")


def launch_browser(url: str, profile_dir: Path) -> subprocess.Popen[Any]:
    browser = find_browser()
    args = [
        str(browser),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-extensions-with-background-pages",
        "--no-first-run",
        "--no-default-browser-check",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir}",
        url,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)


def stop_browser(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def devtools_port(profile_dir: Path, timeout_seconds: float = 10.0) -> int:
    port_file = profile_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if port_file.exists():
            lines = port_file.read_text(encoding="utf-8").splitlines()
            if lines:
                return int(lines[0])
        time.sleep(0.1)
    raise RuntimeError("Headless browser did not expose a DevTools port.")


def page_websocket_url(port: int, target_url: str) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            pages = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
            for page in pages:
                if not isinstance(page, dict):
                    continue
                if page.get("type") == "page" and str(page.get("url") or "").startswith(target_url.rstrip("/")):
                    return str(page["webSocketDebuggerUrl"])
                if page.get("type") == "page" and page.get("webSocketDebuggerUrl"):
                    return str(page["webSocketDebuggerUrl"])
        except (requests.RequestException, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise RuntimeError("Could not find a browser page DevTools target.")


DOM_SNAPSHOT_SCRIPT = r"""
(() => {
  const text = (selector) => (document.querySelector(selector)?.textContent || "").trim();
  const runtimeBanner = document.querySelector("#runtimeHealthBanner");
  const runtimeTitle = document.querySelector("#runtimeHealthTitle") || runtimeBanner?.querySelector("strong");
  return {
    statusText: text("#statusText"),
    equity: text("#equity"),
    dailyPl: text("#dailyPl"),
    dailyPlDetail: text("#dailyPlDetail"),
    realizedPl: text("#realizedPl"),
    realizedPlDetail: text("#realizedPlDetail"),
    buyingPower: text("#buyingPower"),
    cash: text("#cash"),
    lastRefresh: text("#lastRefresh"),
    accountCards: document.querySelectorAll("#accountCards .account-card").length,
    activeCardDailyPl: text("#accountCards .account-card.active em"),
    runtimeWarningVisible: runtimeBanner ? !runtimeBanner.hidden : false,
    runtimeWarningTitle: runtimeTitle ? runtimeTitle.textContent.trim() : ""
  };
})()
"""


def expected_from_state(state: dict[str, Any]) -> dict[str, Any]:
    selected = state.get("selected") if isinstance(state.get("selected"), dict) else {}
    account = selected.get("account") if isinstance(selected.get("account"), dict) else {}
    daily_amount = str(account.get("daily_pl_display") or account.get("daily_pl") or "$0.00")
    daily_pct = str(account.get("daily_pl_pct_display") or "0.00%")
    daily_session = str(account.get("daily_pl_session_date") or "")
    realized_session = str(account.get("realized_pl_session_date") or "")
    return {
        "account_count": len(state.get("accounts") or []),
        "equity": str(account.get("equity_display") or "$0.00"),
        "dailyPl": f"{daily_amount} ({daily_pct})",
        "dailyPlDetail": f"Session {daily_session}" if daily_session else "",
        "realizedPl": str(account.get("realized_pl_display") or "$0.00"),
        "realizedPlDetail": f"Session {realized_session}" if realized_session else "",
        "buyingPower": str(account.get("buying_power_display") or "$0.00"),
        "cash": str(account.get("cash_display") or "$0.00"),
        "lastRefresh": str(selected.get("last_refresh") or "-"),
    }


def verify_rendered_payload(state: dict[str, Any], rendered: dict[str, Any], expected_accounts: int = 3) -> dict[str, Any]:
    expected = expected_from_state(state)
    health = state.get("_runtime_health") if isinstance(state.get("_runtime_health"), dict) else {}
    health_current = health.get("current")
    health_error = str(health.get("_error") or "")
    runtime_visible = bool(rendered.get("runtimeWarningVisible"))
    runtime_title = str(rendered.get("runtimeWarningTitle") or "")
    stale_warning_visible = runtime_visible and "stale runtime" in runtime_title.lower()
    checks: list[DisplayCheck] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append(DisplayCheck(name=name, ok=ok, detail=detail))

    add(
        "accounts.count",
        int(expected["account_count"]) >= expected_accounts,
        f"API returned {expected['account_count']} account(s)",
    )
    add(
        "ui.account_cards",
        int(rendered.get("accountCards") or 0) >= expected_accounts,
        f"UI rendered {int(rendered.get('accountCards') or 0)} account card(s)",
    )
    for key in ("equity", "dailyPl", "dailyPlDetail", "realizedPl", "realizedPlDetail", "buyingPower", "cash", "lastRefresh"):
        add(f"ui.{key}", rendered.get(key) == expected[key], f"{key} matches /api/state")
    add(
        "ui.active_card_daily_pl",
        rendered.get("activeCardDailyPl") == expected["dailyPl"],
        "active account card Daily P/L matches /api/state",
    )
    add(
        "ui.runtime_warning_visible",
        isinstance(rendered.get("runtimeWarningVisible"), bool),
        "runtime warning visibility was read from the rendered DOM",
    )
    if not health_error and health_current is True:
        add(
            "ui.stale_runtime_warning_hidden",
            not stale_warning_visible,
            "current backend must not render a stale runtime warning",
        )
    elif not health_error and health_current is False:
        add(
            "ui.stale_runtime_warning_visible",
            stale_warning_visible,
            "stale backend must render a stale runtime warning",
        )
    else:
        add(
            "ui.runtime_health_available",
            False,
            health_error or "runtime health currentness was unavailable",
        )
    ok = all(check.ok for check in checks)
    return {
        "ok": ok,
        "summary": {
            "account_count": expected["account_count"],
            "rendered_account_cards": int(rendered.get("accountCards") or 0),
            "runtime_warning_visible": bool(rendered.get("runtimeWarningVisible")),
            "runtime_warning_title": runtime_title,
            "health_current": health_current,
        },
        "checks": [check.as_dict() for check in checks],
    }


def collect_rendered_payload(base_url: str, timeout_seconds: float = 20.0) -> tuple[dict[str, Any], dict[str, Any]]:
    state = fetch_state(base_url)
    health = fetch_health(base_url)
    state["_runtime_health"] = health
    expected = expected_from_state(state)
    with tempfile.TemporaryDirectory(prefix="alpaca-ui-verify-", ignore_cleanup_errors=True) as raw_profile:
        profile_dir = Path(raw_profile)
        process = launch_browser(base_url, profile_dir)
        try:
            port = devtools_port(profile_dir)
            ws_url = page_websocket_url(port, base_url)
            with CdpClient(ws_url) as cdp:
                deadline = time.monotonic() + timeout_seconds
                rendered: dict[str, Any] = {}
                while time.monotonic() < deadline:
                    rendered = cdp.evaluate(DOM_SNAPSHOT_SCRIPT) or {}
                    current_state = fetch_state(base_url)
                    current_state["_runtime_health"] = health
                    current_expected = expected_from_state(current_state)
                    state = current_state
                    if (
                        int(rendered.get("accountCards") or 0) >= int(expected["account_count"])
                        and rendered.get("dailyPl") == current_expected["dailyPl"]
                        and rendered.get("lastRefresh") == current_expected["lastRefresh"]
                    ):
                        return state, rendered
                    time.sleep(0.25)
                return state, rendered
        finally:
            stop_browser(process)


def print_human(report: dict[str, Any]) -> None:
    print("Rendered UI display verification")
    print(f"  ok: {report['ok']}")
    summary = report.get("summary", {})
    print(f"  accounts: {summary.get('account_count')}")
    print(f"  rendered account cards: {summary.get('rendered_account_cards')}")
    print(f"  runtime warning visible: {summary.get('runtime_warning_visible')}")
    print(f"  runtime warning title: {summary.get('runtime_warning_title')}")
    print(f"  health current: {summary.get('health_current')}")
    failures = [item for item in report.get("checks", []) if not item.get("ok")]
    if not failures:
        print("  failures: none")
        return
    print("  failures:")
    for item in failures:
        print(f"    - {item.get('name')}: {item.get('detail')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify rendered Alpaca Paper Trader UI metric cards against /api/state without printing account identifiers."
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--expected-accounts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    state, rendered = collect_rendered_payload(args.url, timeout_seconds=args.timeout)
    report = verify_rendered_payload(state, rendered, expected_accounts=args.expected_accounts)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
