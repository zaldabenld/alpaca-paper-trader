from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca_desktop.currentness import (  # noqa: E402
    ROOT as SOURCE_ROOT,
    same_source_path,
    source_stamp,
)
from alpaca_desktop.server import app  # noqa: E402


APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader"
INSTANCE_PATH = APP_DATA_DIR / "instance.json"
DEFAULT_PORT = 8765


def find_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def preferred_port(host: str) -> int:
    raw_port = os.environ.get("ALPACA_TRADER_PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        port = DEFAULT_PORT
    if port > 0 and port_is_free(host, port):
        return port
    return find_port(host)


def load_instance() -> dict[str, Any]:
    try:
        raw = json.loads(INSTANCE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return {}


def instance_url(raw: dict[str, Any]) -> str:
    return str(raw.get("url") or "")


def instance_pid(raw: dict[str, Any]) -> int:
    try:
        return int(raw.get("pid") or 0)
    except (TypeError, ValueError):
        return 0


def fetch_health(url: str, timeout: float = 1.0) -> dict[str, Any]:
    if not url:
        return {}
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as response:
            if response.status >= 400:
                return {}
            raw = json.loads(response.read().decode("utf-8"))
            return raw if isinstance(raw, dict) else {}
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return {}


def url_is_alive(url: str, timeout: float = 1.0) -> bool:
    if not url:
        return False
    for endpoint in ("/api/health", "/api/state"):
        try:
            with urllib.request.urlopen(f"{url}{endpoint}", timeout=timeout) as response:
                return response.status < 500
        except urllib.error.HTTPError as exc:
            return exc.code < 500
        except (OSError, urllib.error.URLError, TimeoutError):
            continue
    return False


def health_matches_current_source(health: dict[str, Any]) -> bool:
    if health.get("current") is not True:
        return False
    if str(health.get("source_stamp") or "") != source_stamp():
        return False
    return same_source_path(str(health.get("source_path") or ""), SOURCE_ROOT)


def describe_health(health: dict[str, Any], raw: dict[str, Any]) -> str:
    pid = health.get("pid") or raw.get("pid") or "unknown"
    status = health.get("status") or "missing health"
    running_stamp = health.get("source_stamp") or raw.get("source_stamp") or "unknown"
    expected_stamp = source_stamp()
    source_path = health.get("source_path") or "unknown source path"
    return (
        f"status={status}; pid={pid}; source_stamp={running_stamp}; "
        f"expected_source_stamp={expected_stamp}; source_path={source_path}"
    )


def stop_instance(raw: dict[str, Any], url: str) -> bool:
    pid = instance_pid(raw)
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        safe_print(f"Could not stop stale Alpaca Paper Trader backend pid {pid}: {exc}")
        return False

    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not url_is_alive(url, timeout=0.3):
            return True
        time.sleep(0.25)
    return not url_is_alive(url, timeout=0.3)


def active_instance_url(restart_stale: bool = True) -> str:
    try:
        raw = load_instance()
        url = instance_url(raw)
        if not url:
            return ""
        if not url_is_alive(url):
            return ""
        health = fetch_health(url)
        if health_matches_current_source(health):
            return url

        stale_detail = describe_health(health, raw)
        safe_print(f"Existing Alpaca Paper Trader backend is stale or from a different source; {stale_detail}.")
        if restart_stale:
            if stop_instance(raw, url):
                return ""
            safe_print(
                "Stale backend did not stop cleanly. Starting a separate current instance instead of reusing it."
            )
        return ""
    except (OSError, RuntimeError, ValueError):
        return ""


def save_instance_url(url: str) -> None:
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        INSTANCE_PATH.write_text(
            json.dumps(
                {
                    "url": url,
                    "pid": os.getpid(),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "source_stamp": source_stamp(),
                    "source_path": str(SOURCE_ROOT),
                }
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        safe_print(f"Could not save Alpaca Paper Trader instance file: {exc}")


def clear_instance_url(url: str) -> None:
    try:
        raw = json.loads(INSTANCE_PATH.read_text(encoding="utf-8"))
        if str(raw.get("url") or "") == url:
            INSTANCE_PATH.unlink(missing_ok=True)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        pass


def safe_print(message: str) -> None:
    try:
        print(message)
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Alpaca Paper Trader")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-restart-stale", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        safe_print("Alpaca Paper Trader Python app imports OK.")
        return

    existing_url = active_instance_url(restart_stale=not args.no_restart_stale)
    if existing_url:
        if not args.no_browser:
            webbrowser.open(existing_url)
        safe_print(f"Alpaca Paper Trader already running at {existing_url}")
        return

    if args.port is None:
        port = preferred_port(args.host)
    elif args.port == 0:
        port = find_port(args.host)
    else:
        port = args.port
    url = f"http://{args.host}:{port}"
    save_instance_url(url)
    app.state.runtime_url = url
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    safe_print(f"Alpaca Paper Trader running at {url}")
    try:
        uvicorn.run(app, host=args.host, port=port, log_level="warning", log_config=None, access_log=False)
    finally:
        clear_instance_url(url)


if __name__ == "__main__":
    main()
