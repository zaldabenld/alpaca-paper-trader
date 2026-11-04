"""Desktop notifications for trading events.

Uses Linux ``notify-send``; no-op elsewhere. Notifications are handed to a
background worker so the caller is never blocked.
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable

_APP_NAME = "Alpaca Paper Trader"
_WINDOW_SECONDS = 60.0
_URGENCIES = ("low", "normal", "critical")


class DesktopNotifier:
    """Rate-limited, deduplicated desktop alerts on a background thread."""

    def __init__(
        self,
        sender: Callable[[list[str]], None] | None = None,
        *,
        enabled: bool | None = None,
        max_per_minute: int = 5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if enabled is None:
            enabled = (
                os.name == "posix"
                and shutil.which("notify-send") is not None
                and os.environ.get("ALPACA_TRADER_DISABLE_ALERTS") != "1"
            )
        self._enabled = enabled
        self._sender = sender if sender is not None else self._run_notify_send
        self._max_per_minute = max_per_minute
        self._clock = clock
        self._queue: queue.Queue[list[str]] = queue.Queue(maxsize=50)
        self._worker: threading.Thread | None = None
        self._dedupe: dict[str, float] = {}
        self._recent: list[float] = []
        self._suppressed = 0
        self._lock = threading.Lock()

    def _run_notify_send(self, args: list[str]) -> None:
        env = os.environ.copy()
        if "DBUS_SESSION_BUS_ADDRESS" not in env:
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path=/run/user/{os.getuid()}/bus"
        try:
            subprocess.run(
                args,
                timeout=5,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except (OSError, subprocess.SubprocessError):
            pass  # alerts must never crash the trader

    def _worker_loop(self) -> None:
        while True:
            args = self._queue.get()
            try:
                self._sender(args)
            except Exception:
                pass  # a bad alert must not kill the worker
            finally:
                self._queue.task_done()

    def _ensure_worker(self) -> None:  # caller holds self._lock
        if self._worker is None:
            self._worker = threading.Thread(
                target=self._worker_loop, name="apt-alerts", daemon=True
            )
            self._worker.start()

    def notify(
        self,
        title: str,
        body: str,
        *,
        key: str = "",
        ttl_seconds: float = 0,
        urgency: str = "normal",
    ) -> bool:
        """Queue an alert; False if disabled, deduped, rate-limited, or full."""
        if not self._enabled:
            return False
        now = self._clock()
        if urgency not in _URGENCIES:
            urgency = "normal"
        with self._lock:
            if len(self._dedupe) > 200:
                self._dedupe = {k: v for k, v in self._dedupe.items() if v > now}
            if key:
                expiry = self._dedupe.get(key)
                if expiry is not None and expiry > now:
                    return False
            # drop timestamps outside the rate-limit window
            self._recent = [t for t in self._recent if t >= now - _WINDOW_SECONDS]
            if len(self._recent) >= self._max_per_minute:
                self._suppressed += 1
                return False
            # only start the dedupe window for alerts that are actually shown
            if key and ttl_seconds > 0:
                self._dedupe[key] = now + ttl_seconds
            self._ensure_worker()
            if self._suppressed:
                # tell the user what they missed, ahead of the new alert
                summary = [
                    "notify-send",
                    "-a",
                    _APP_NAME,
                    "-u",
                    "normal",
                    "--",
                    _APP_NAME,
                    f"{self._suppressed} more alerts were suppressed (rate limit).",
                ]
                try:
                    self._queue.put_nowait(summary)
                    self._recent.append(now)
                except queue.Full:
                    pass
                self._suppressed = 0
            # "--" so a title/body starting with "-" (e.g. "-0.52% ...") is not parsed as an option
            args = ["notify-send", "-a", _APP_NAME, "-u", urgency, "--", title, body]
            try:
                self._queue.put_nowait(args)
            except queue.Full:
                return False
            self._recent.append(now)
            return True

    def flush(self, timeout: float = 2.0) -> None:
        """Wait for queued alerts to drain; used by tests and before exit."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)


NOTIFIER = DesktopNotifier()  # module-level singleton
