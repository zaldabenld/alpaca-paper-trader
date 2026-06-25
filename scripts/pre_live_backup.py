from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = REPO_ROOT / ".runtime" / "pre-live-deploy-backups"
APP_DATA_NAME = "AlpacaPaperTrader"
CORE_FILES = (
    "python-settings.json",
    "instance.json",
    "dashboard-cache.json",
)
CORE_DIRS = (
    "replay",
    "day-tape",
)


def app_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DATA_NAME


def directory_size(path: Path) -> tuple[int, int]:
    files = 0
    bytes_total = 0
    if not path.exists():
        return files, bytes_total
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            bytes_total += item.stat().st_size
            files += 1
        except OSError:
            continue
    return files, bytes_total


def format_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def existing_parent(path: Path) -> Path:
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            return current
        current = parent
    return current


def available_bytes(path: Path) -> int:
    return int(shutil.disk_usage(existing_parent(path)).free)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def latest_backup_root(backup_root: Path) -> Path | None:
    if not backup_root.exists():
        return None
    backups = [item for item in backup_root.iterdir() if item.is_dir()]
    if not backups:
        return None
    return max(backups, key=lambda item: item.stat().st_mtime)


def reusable_file(source: Path, previous: Path | None) -> bool:
    if previous is None or not previous.exists() or not previous.is_file():
        return False
    try:
        source_stat = source.stat()
        previous_stat = previous.stat()
    except OSError:
        return False
    return source_stat.st_size == previous_stat.st_size and source_stat.st_mtime_ns == previous_stat.st_mtime_ns


def core_relative_files(source_root: Path) -> list[tuple[Path, int]]:
    files: list[tuple[Path, int]] = []
    for name in CORE_FILES:
        source = source_root / name
        if source.exists() and source.is_file():
            try:
                files.append((Path(name), source.stat().st_size))
            except OSError:
                pass
    for name in CORE_DIRS:
        source = source_root / name
        if not source.exists() or not source.is_dir():
            continue
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            try:
                files.append((Path(name) / item.relative_to(source), item.stat().st_size))
            except OSError:
                continue
    return files


def reusable_backup_bytes(source_root: Path, previous_root: Path | None) -> int:
    if previous_root is None:
        return 0
    reusable = 0
    for relative, bytes_total in core_relative_files(source_root):
        if reusable_file(source_root / relative, previous_root / relative):
            reusable += bytes_total
    return reusable


def copy_file_reusing_previous(source: Path, destination: Path, previous: Path | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if reusable_file(source, previous):
        try:
            os.link(previous, destination)
            return
        except OSError:
            pass
    shutil.copy2(source, destination)


def copy_dir(source: Path, destination: Path, previous: Path | None = None) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if item.is_file():
            copy_file_reusing_previous(item, target, previous / relative if previous is not None else None)


def build_backup(execute: bool, backup_root: Path) -> int:
    source_root = app_data_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_root = backup_root / timestamp

    print(f"Source app data exists: {source_root.exists()}")
    print(f"Source app data: {source_root}")
    print(f"Backup target: {destination_root}")
    print(f"Mode: {'execute' if execute else 'dry-run'}")
    print()

    if not source_root.exists():
        print("No AlpacaPaperTrader app-data folder found.")
        return 1

    planned_files: list[tuple[Path, Path, int]] = []
    planned_dirs: list[tuple[Path, Path, int, int]] = []

    for name in CORE_FILES:
        source = source_root / name
        if source.exists() and source.is_file():
            planned_files.append((source, destination_root / name, source.stat().st_size))

    for name in CORE_DIRS:
        source = source_root / name
        if source.exists() and source.is_dir():
            count, bytes_total = directory_size(source)
            planned_dirs.append((source, destination_root / name, count, bytes_total))

    total_bytes = sum(bytes_total for _source, _destination, bytes_total in planned_files) + sum(
        bytes_total for _source, _destination, _count, bytes_total in planned_dirs
    )
    previous_root = latest_backup_root(backup_root)
    reusable_bytes = reusable_backup_bytes(source_root, previous_root)
    additional_bytes = max(0, total_bytes - reusable_bytes)
    free_bytes = available_bytes(backup_root)

    print("Planned file backups:")
    if planned_files:
        for source, _destination, bytes_total in planned_files:
            print(f"  {source.name}: {format_bytes(bytes_total)}")
    else:
        print("  none")

    print("Planned directory backups:")
    if planned_dirs:
        for source, _destination, count, bytes_total in planned_dirs:
            print(f"  {source.name}: {count:,} files, {format_bytes(bytes_total)}")
    else:
        print("  none")

    print(f"Planned backup total: {format_bytes(total_bytes)}")
    if previous_root is not None:
        print(f"Latest reusable backup: {previous_root}")
        print(f"Reusable unchanged bytes: {format_bytes(reusable_bytes)}")
    print(f"Additional disk space required: {format_bytes(additional_bytes)}")
    print(f"Available backup disk space: {format_bytes(free_bytes)}")

    if not execute:
        print()
        print("Dry run only. Re-run with --execute after live restart approval.")
        return 0

    if additional_bytes > free_bytes:
        print()
        print(
            "Backup aborted: additional backup data is larger than available destination disk space. "
            "No files were copied."
        )
        return 1

    destination_root.mkdir(parents=True, exist_ok=False)
    for source, destination, _bytes_total in planned_files:
        relative = source.relative_to(source_root)
        copy_file_reusing_previous(source, destination, previous_root / relative if previous_root is not None else None)
    for source, destination, _count, _bytes_total in planned_dirs:
        relative = source.relative_to(source_root)
        copy_dir(source, destination, previous_root / relative if previous_root is not None else None)

    print()
    print(f"Backup complete: {destination_root}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a local pre-live-deploy backup for Alpaca Paper Trader app data."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually copy files. Without this flag the script prints a dry-run plan only.",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help="Directory where timestamped backup folders are created.",
    )
    args = parser.parse_args()
    return build_backup(execute=bool(args.execute), backup_root=args.backup_root)


if __name__ == "__main__":
    raise SystemExit(main())
