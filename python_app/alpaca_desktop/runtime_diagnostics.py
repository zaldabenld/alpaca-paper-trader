from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


MAX_RUNTIME_DIAGNOSTICS = 100


class AlpacaRuntimeError(RuntimeError):
    """Base class for typed recoverable runtime failures."""


class AccountRefreshError(AlpacaRuntimeError):
    """Account refresh failed after a recoverable runtime exception."""


class CachePersistenceError(AlpacaRuntimeError):
    """Dashboard cache persistence failed."""


class MarketDataError(AlpacaRuntimeError):
    """Recoverable market-data fetch failed."""


class OrderExecutionError(AlpacaRuntimeError):
    """Live order execution or cancellation failed."""


class ReplayPersistenceError(AlpacaRuntimeError):
    """Replay or day-tape persistence failed."""


class SettingsPersistenceError(AlpacaRuntimeError):
    """Settings load or recovery failed."""


class StreamControlError(AlpacaRuntimeError):
    """Market-data stream shutdown or control failed."""


def exception_detail(error: BaseException | None) -> str:
    if error is None:
        return ""
    detail = str(error).strip() or error.__class__.__name__
    return detail[:500]


class RuntimeDiagnostics:
    def __init__(self, limit: int = MAX_RUNTIME_DIAGNOSTICS) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=limit)
        self._lock = threading.RLock()
        self._logger = logging.getLogger("alpaca_desktop.runtime")
        self._logger.addHandler(logging.NullHandler())
        self._logger.propagate = False

    def record(
        self,
        area: str,
        message: str,
        error: BaseException | None = None,
        *,
        severity: str = "warning",
        source: str = "runtime",
    ) -> dict[str, Any]:
        detail = exception_detail(error)
        now = datetime.now(timezone.utc)
        entry = {
            "time": now.isoformat(),
            "time_display": datetime.now().strftime("%H:%M:%S"),
            "severity": severity,
            "source": source,
            "area": str(area or "runtime"),
            "message": str(message or "Runtime diagnostic"),
            "exception_type": error.__class__.__name__ if error is not None else "",
            "detail": detail,
        }
        with self._lock:
            self._entries.append(entry)

        log_message = f"{entry['area']}: {entry['message']}"
        if detail:
            log_message = f"{log_message}: {detail}"
        if severity == "error":
            self._logger.error(log_message)
        elif severity == "info":
            self._logger.info(log_message)
        else:
            self._logger.warning(log_message)
        return dict(entry)

    def snapshot(self, limit: int = 50) -> dict[str, Any]:
        with self._lock:
            entries = list(self._entries)[-limit:]
        errors = [entry for entry in entries if entry.get("severity") == "error"]
        return {
            "entries": [dict(entry) for entry in entries],
            "count": len(entries),
            "error_count": len(errors),
        }

    def clear(self, *, area: str | None = None, source: str | None = None) -> None:
        with self._lock:
            if area is None and source is None:
                self._entries.clear()
                return
            kept = [
                entry
                for entry in self._entries
                if (area is not None and entry.get("area") != area)
                or (source is not None and entry.get("source") != source)
            ]
            self._entries.clear()
            self._entries.extend(kept)


runtime_diagnostics = RuntimeDiagnostics()


def record_runtime_diagnostic(
    area: str,
    message: str,
    error: BaseException | None = None,
    *,
    severity: str = "warning",
    source: str = "runtime",
) -> dict[str, Any]:
    return runtime_diagnostics.record(area, message, error, severity=severity, source=source)


def runtime_diagnostics_snapshot(limit: int = 50) -> dict[str, Any]:
    return runtime_diagnostics.snapshot(limit=limit)


def clear_runtime_diagnostics(*, area: str | None = None, source: str | None = None) -> None:
    runtime_diagnostics.clear(area=area, source=source)
