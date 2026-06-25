from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SHORTCUT_NAME = "Alpaca Paper Trader.lnk"
VBS_NAME = "Launch Alpaca Paper Trader.vbs"
ICON_NAME = "alpaca-paper-trader.ico"


def _powershell_path() -> str:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    candidate = Path(windir) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell"


def _normalize_path(value: object) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return os.path.normcase(os.path.normpath(text))


def expected_shortcut_contract(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    launcher = repo_root / VBS_NAME
    icon = repo_root / "assets" / ICON_NAME
    return {
        "target_path": str(Path(windir) / "System32" / "wscript.exe"),
        "arguments": f'"{launcher}"',
        "working_directory": str(repo_root),
        "icon_path": str(icon),
    }


def read_shortcut_metadata(shortcut_path: str = "") -> dict[str, Any]:
    path_literal = shortcut_path
    script = f"""
$ErrorActionPreference = 'Stop'
$lnk = @'
{path_literal}
'@
if ([string]::IsNullOrWhiteSpace($lnk)) {{
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '{SHORTCUT_NAME}'
}}
if (-not (Test-Path -LiteralPath $lnk)) {{
    [pscustomobject]@{{
        exists = $false
        path = $lnk
    }} | ConvertTo-Json -Compress
    exit 0
}}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
[pscustomobject]@{{
    exists = $true
    path = $lnk
    target_path = $shortcut.TargetPath
    arguments = $shortcut.Arguments
    working_directory = $shortcut.WorkingDirectory
    icon_location = $shortcut.IconLocation
    description = $shortcut.Description
}} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [
            _powershell_path(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return json.loads(result.stdout)


def validate_shortcut_metadata(
    metadata: dict[str, Any], repo_root: Path = REPO_ROOT
) -> tuple[bool, list[str], dict[str, str]]:
    expected = expected_shortcut_contract(repo_root)
    issues: list[str] = []

    if not metadata.get("exists"):
        issues.append(f"Desktop shortcut is missing: {metadata.get('path') or SHORTCUT_NAME}")
        return False, issues, expected

    if _normalize_path(metadata.get("target_path")) != _normalize_path(expected["target_path"]):
        issues.append(
            f"TargetPath should be {expected['target_path']}, got {metadata.get('target_path')!r}"
        )

    if str(metadata.get("arguments") or "").strip() != expected["arguments"]:
        issues.append(f"Arguments should be {expected['arguments']}, got {metadata.get('arguments')!r}")

    if _normalize_path(metadata.get("working_directory")) != _normalize_path(
        expected["working_directory"]
    ):
        issues.append(
            "WorkingDirectory should be "
            f"{expected['working_directory']}, got {metadata.get('working_directory')!r}"
        )

    icon_location = str(metadata.get("icon_location") or "")
    icon_path = icon_location.split(",", 1)[0]
    if icon_path and _normalize_path(icon_path) != _normalize_path(expected["icon_path"]):
        issues.append(f"IconLocation should use {expected['icon_path']}, got {icon_location!r}")

    return not issues, issues, expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the read-only desktop shortcut contract without launching the app."
    )
    parser.add_argument("--shortcut", default="", help="Optional explicit .lnk path to inspect.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable verification output.")
    args = parser.parse_args(argv)

    metadata = read_shortcut_metadata(args.shortcut)
    ok, issues, expected = validate_shortcut_metadata(metadata)
    payload = {
        "ok": ok,
        "issues": issues,
        "shortcut": metadata,
        "expected": expected,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif ok:
        print(f"Desktop shortcut OK: {metadata.get('path')}")
        print(f"Target: {metadata.get('target_path')}")
        print(f"Arguments: {metadata.get('arguments')}")
        print(f"Working directory: {metadata.get('working_directory')}")
    else:
        print("Desktop shortcut verification failed:")
        for issue in issues:
            print(f"- {issue}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
