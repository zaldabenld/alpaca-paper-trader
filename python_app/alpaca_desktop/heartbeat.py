"""Heartbeat to the n8n watchdog, and the kill-switch flag it returns.

A background thread POSTs to ``N8N_HEARTBEAT_URL`` every 60 seconds, around the clock, with the
``X-Control-Token`` header set to ``N8N_CONTROL_TOKEN``. n8n answers ``{"ok": true, "halt": bool}``;
``halt`` becomes the process-wide ``trading_halted()`` flag that the engine checks before it sends
any order. If either variable is unset the heartbeat is off and trading is never halted. When n8n
cannot be reached the last known flag is kept. A configured process waits for its first valid
reply before making order changes.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from .runtime_diagnostics import OrderExecutionError, record_runtime_diagnostic as record_diagnostic

DEFAULT_INTERVAL_SECONDS = 60.0


class TradingHaltedError(OrderExecutionError):
    """The watchdog has halted trading or has yet to confirm its initial state."""


Poster = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def _urllib_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL from env
        return json.loads(response.read().decode("utf-8") or "{}")


class N8nHeartbeat:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        timeout: float = 10.0,
        poster: Poster | None = None,
    ) -> None:
        self.url = (url if url is not None else os.environ.get("N8N_HEARTBEAT_URL", "")).strip()
        self.token = (token if token is not None else os.environ.get("N8N_CONTROL_TOKEN", "")).strip()
        self.interval = interval
        self.timeout = timeout
        self._poster = poster or _urllib_post
        self._halted = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_ok: float | None = None
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    @property
    def halted(self) -> bool:
        return self._halted.is_set()

    @property
    def blocks_orders(self) -> bool:
        return self.halted or (self.enabled and self.last_ok is None)

    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.halted:
            return "halted"
        if self.last_error:
            return "unreachable"
        if self.last_ok is None:
            return "waiting"
        return "connected"

    def beat_once(self, source: str = "app") -> bool | None:
        """Send one heartbeat. Returns the halt flag, or None if n8n did not answer."""
        if not self.enabled:
            return None
        headers = {"Content-Type": "application/json", "X-Control-Token": self.token}
        body = json.dumps({"source": source}).encode("utf-8")
        try:
            reply = self._poster(self.url, headers, body, self.timeout)
            if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(reply.get("halt"), bool):
                raise ValueError("unexpected heartbeat reply")
        except Exception as exc:  # network, HTTP 401/5xx, bad JSON: keep the last known flag
            message = f"{type(exc).__name__}: {exc}"
            if message != self.last_error:
                record_diagnostic("n8n_heartbeat", "n8n heartbeat failed; keeping last halt state", exc,
                                  severity="warning", source="heartbeat")
            self.last_error = message
            return None
        self.last_error = None
        self._set_halted(reply["halt"])
        self.last_ok = time.time()
        return reply["halt"]

    def _set_halted(self, halted: bool) -> None:
        if halted == self.halted:
            return
        if halted:
            self._halted.set()
            record_diagnostic("n8n_heartbeat", "Trading HALTED by the n8n kill switch; no orders will be sent",
                              None, severity="error", source="heartbeat")
        else:
            self._halted.clear()
            record_diagnostic("n8n_heartbeat", "n8n kill switch cleared; orders allowed again",
                              None, severity="info", source="heartbeat")

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="n8n-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self.beat_once()
            self._stop.wait(self.interval)


HEARTBEAT = N8nHeartbeat()


def trading_halted() -> bool:
    return HEARTBEAT.blocks_orders
