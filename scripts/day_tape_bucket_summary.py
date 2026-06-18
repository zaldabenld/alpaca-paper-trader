from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def tape_file_date(path: Path) -> str:
    name = path.name
    if name.startswith("tape-") and name.endswith(".jsonl"):
        return name[5:13]
    return ""


def selected_files(path: Path, days: int, end_date: str) -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)
    if end_date:
        files = [item for item in files if tape_file_date(item) <= end_date]
    return files[-max(1, days) :]


def line_is_strategy_scan(line: str) -> bool:
    return '"kind":"strategy_scan"' in line or '"kind": "strategy_scan"' in line


def bucket_label(payload: dict[str, Any]) -> str:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    return (
        f"profile={config.get('profile')}, "
        f"max_trade={config.get('max_trade_notional')}, "
        f"max_positions={config.get('max_open_positions')}, "
        f"top_volume={config.get('use_top_volume_symbols')}, "
        f"dry_run={config.get('dry_run')}"
    )


def summarize(files: list[Path]) -> tuple[Counter[str], dict[str, Counter[str]]]:
    totals: Counter[str] = Counter()
    by_file: dict[str, Counter[str]] = defaultdict(Counter)
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                if not line_is_strategy_scan(raw_line):
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                label = bucket_label(payload)
                totals[label] += 1
                by_file[path.name][label] += 1
    return totals, by_file


def main() -> int:
    parser = argparse.ArgumentParser(description="List strategy-scan buckets in completed day tapes.")
    parser.add_argument("--path", type=Path, default=default_tape_dir())
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    files = selected_files(args.path, args.days, str(args.end_date or ""))
    if not files:
        print("No day-tape files found.")
        return 0
    totals, by_file = summarize(files)
    print(f"Files: {', '.join(path.name for path in files)}")
    print()
    print("Totals")
    for label, count in totals.most_common():
        print(f"{count:>8}  {label}")
    print()
    print("By file")
    for file_name in sorted(by_file):
        print(file_name)
        for label, count in by_file[file_name].most_common():
            print(f"  {count:>8}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
