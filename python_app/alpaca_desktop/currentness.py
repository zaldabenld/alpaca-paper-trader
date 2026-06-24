from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SOURCE_SUFFIXES = {".py", ".html", ".js", ".css", ".webmanifest"}
SOURCE_STAMP_ENV = "ALPACA_TRADER_EXPECTED_SOURCE_STAMP"

ROOT = Path(__file__).resolve().parents[1]
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()


def source_stamp(root: Path | None = None) -> str:
    source_root = root or ROOT
    latest = 0
    total_size = 0
    file_count = 0
    for path in source_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        latest = max(latest, stat.st_mtime_ns)
        total_size += stat.st_size
        file_count += 1
    return f"{latest}:{file_count}:{total_size}"


PROCESS_SOURCE_STAMP = os.environ.get(SOURCE_STAMP_ENV) or source_stamp()
os.environ.setdefault(SOURCE_STAMP_ENV, PROCESS_SOURCE_STAMP)


def currentness_payload(
    *,
    url: str = "",
    expected_source_stamp: str | None = None,
    source_root: Path | None = None,
    pid: int | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    root = source_root or ROOT
    expected = expected_source_stamp or PROCESS_SOURCE_STAMP
    actual = source_stamp(root)
    current = actual == expected
    payload: dict[str, Any] = {
        "service": "Alpaca Paper Trader",
        "status": "current" if current else "stale",
        "current": current,
        "pid": pid if pid is not None else os.getpid(),
        "url": url,
        "source_path": str(root),
        "source_stamp": actual,
        "expected_source_stamp": expected,
        "started_at": started_at or PROCESS_STARTED_AT,
    }
    if not current:
        payload["stale_reason"] = "Running process source stamp does not match the launcher/source stamp."
    return payload


def same_source_path(left: str, right: Path | str | None = None) -> bool:
    if not left:
        return False
    try:
        left_path = Path(left).resolve()
        right_path = Path(right or ROOT).resolve()
    except OSError:
        return False
    return os.path.normcase(str(left_path)) == os.path.normcase(str(right_path))
