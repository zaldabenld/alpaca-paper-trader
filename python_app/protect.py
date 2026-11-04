"""Headless stop protection, for when the desktop app is not running.

Run by the alpaca-protect systemd --user timer (deploy/systemd/). If the app is running it
holds the engine lock and this exits immediately. Otherwise each saved account that is not in
dry run is connected once with trading OFF, which runs the same exit management the app does:
during market hours it keeps the DAY stop-loss in place and sells positions already below their
stop; outside market hours it only queues a DAY stop for the next open. It never buys.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpaca_desktop.alerts import NOTIFIER  # noqa: E402
from alpaca_desktop.server import acquire_engine_lock, load_saved_settings_to_manager, manager  # noqa: E402
from alpaca_desktop.storage import APP_DIR, ensure_private_app_dir  # noqa: E402

LOG_PATH = APP_DIR / "protect.log"


def log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line)
    try:
        ensure_private_app_dir()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    if not acquire_engine_lock():
        log("App is running; it manages stops itself. Nothing to do.")
        return 0
    load_saved_settings_to_manager()
    for engine in manager.list_engines():
        settings = engine.settings(include_keys=True)
        if not settings.get("api_key") or not settings.get("secret_key"):
            continue
        if engine.config.dry_run:
            log(f"{engine.name}: dry run; skipped.")
            continue
        try:
            engine.connect_saved()  # connects with trading off and runs one refresh (exit management)
            state = engine.state()
            rows = state.get("protection") or []
            summary = ", ".join(f"{row.get('symbol')}={row.get('status')}" for row in rows) or "no positions"
            log(f"{engine.name}: {state.get('market_clock', {}).get('status', '')}; {summary}")
            if state.get("last_error"):
                log(f"{engine.name}: error: {state.get('last_error')}")
            for entry in (state.get("logs") or [])[-10:]:
                if entry.get("level") in {"warn", "error"}:
                    log(f"{engine.name}: {entry.get('level')}: {entry.get('message')}")
            # Rejections already alert from the engine; also alert on sells this job submitted.
            for intent in engine.order_intents:
                if (
                    intent.get("role") == "Strategy Exit"
                    and intent.get("status") == "submitted"
                    and not str(intent.get("client_order_id") or "").startswith("apt-exit-limit-")
                ):
                    log(f"{engine.name}: sold {intent.get('qty')} {intent.get('symbol')} ({intent.get('reason')})")
                    engine.alert("trade", f"Protect job sold {intent.get('symbol')}",
                                 f"{intent.get('qty')} shares while the app was closed")
        except Exception as exc:  # keep protecting the other accounts
            log(f"{engine.name}: protect failed: {exc}")
        finally:
            engine.disconnect()
    NOTIFIER.flush(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
