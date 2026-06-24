from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .runtime_diagnostics import SettingsPersistenceError, record_runtime_diagnostic


APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AlpacaPaperTrader"
SETTINGS_PATH = APP_DIR / "python-settings.json"


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        return data

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DataBlob()

    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect_bytes(data: bytes) -> bytes:
    if os.name != "nt":
        return data

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buffer = ctypes.create_string_buffer(data)
    in_blob = DataBlob(len(data), ctypes.cast(in_buffer, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DataBlob()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def protect_text(value: str) -> str:
    if not value:
        return ""
    protected = _protect_bytes(value.encode("utf-8"))
    return base64.b64encode(protected).decode("ascii")


def unprotect_text(value: str) -> str:
    if not value:
        return ""
    raw = base64.b64decode(value.encode("ascii"))
    return _unprotect_bytes(raw).decode("utf-8")


def _settings_error_payload(error: Exception, path: Path) -> dict[str, Any]:
    return {
        "settings_load_error": f"Could not load settings from {path}: {error}",
        "settings_load_error_path": str(path),
    }


def _load_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Settings file must contain a JSON object.")
    return value


def _settings_backups() -> list[Path]:
    if not APP_DIR.exists():
        return []
    return sorted(
        APP_DIR.glob(f"{SETTINGS_PATH.name}.*.bak"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def _backup_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return SETTINGS_PATH.with_name(f"{SETTINGS_PATH.name}.{stamp}.{uuid.uuid4().hex[:8]}.bak")


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return _load_json_file(SETTINGS_PATH)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        error_payload = _settings_error_payload(exc, SETTINGS_PATH)
        record_runtime_diagnostic(
            "settings",
            "Settings load failed",
            SettingsPersistenceError(str(exc) or exc.__class__.__name__),
            source="storage",
        )
        for backup in _settings_backups():
            try:
                recovered = _load_json_file(backup)
                recovered["settings_load_error"] = error_payload["settings_load_error"]
                recovered["settings_load_error_path"] = error_payload["settings_load_error_path"]
                recovered["settings_recovered_from_backup"] = str(backup)
                return recovered
            except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as backup_exc:
                record_runtime_diagnostic(
                    "settings",
                    "Settings backup recovery failed",
                    SettingsPersistenceError(str(backup_exc) or backup_exc.__class__.__name__),
                    source="storage",
                )
                continue
        return error_payload


def save_settings(settings: dict[str, Any]) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if SETTINGS_PATH.exists() and SETTINGS_PATH.is_file():
        shutil.copy2(SETTINGS_PATH, _backup_path())
    temp_path = SETTINGS_PATH.with_name(f"{SETTINGS_PATH.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, SETTINGS_PATH)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
