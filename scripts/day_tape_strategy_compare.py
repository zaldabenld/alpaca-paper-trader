from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_PATH = REPO_ROOT / "scripts" / "day_tape_backtest.py"


CANDIDATE_PROFILES: dict[str, dict[str, Any]] = {
    "current_h2": {},
    "strict_h2_live_20260626": {
        "buy_rsi_min": 42,
        "buy_rsi_max": 68,
        "min_entry_score": 44,
        "min_momentum_percent": 0.08,
        "min_recent_momentum_percent": 0.05,
        "min_long_momentum_percent": 0.05,
        "min_session_change_percent": 1.35,
        "min_vwap_distance_percent": 0.05,
        "max_vwap_distance_percent": 2.25,
        "max_session_pullback_percent": 0.9,
        "max_recent_pullback_percent": 0.55,
        "late_momentum_floor_percent": 0,
        "min_smi": 40,
        "volume_multiplier": 1.5,
        "reentry_score_boost": 12,
        "take_profit_percent": 2.5,
        "stop_loss_percent": 1.25,
    },
    "riskbox_open_smi_40_session_0_05_score_30": {
        "buy_rsi_min": 42,
        "buy_rsi_max": 65,
        "min_entry_score": 30,
        "min_momentum_percent": 0.15,
        "min_recent_momentum_percent": 0.08,
        "min_long_momentum_percent": 0.12,
        "min_session_change_percent": 0.05,
        "min_vwap_distance_percent": 0.05,
        "max_vwap_distance_percent": 2.25,
        "max_session_pullback_percent": 0.75,
        "max_recent_pullback_percent": 0.5,
        "late_momentum_floor_percent": 0,
        "min_smi": 40,
        "volume_multiplier": 1.0,
        "reentry_score_boost": 10,
        "take_profit_percent": 2.5,
        "stop_loss_percent": 1.25,
    },
    "session_0_5": {"min_session_change_percent": 0.5},
    "rsi_35_75": {"buy_rsi_min": 35, "buy_rsi_max": 75},
    "pullback_3_1_5": {"max_session_pullback_percent": 3.0, "max_recent_pullback_percent": 1.5},
    "momentum_zero": {
        "min_momentum_percent": 0,
        "min_recent_momentum_percent": 0,
        "min_long_momentum_percent": 0,
    },
    "moderate_frequency": {
        "buy_rsi_min": 35,
        "buy_rsi_max": 75,
        "min_session_change_percent": 0.5,
        "volume_multiplier": 0.75,
        "max_session_pullback_percent": 3.0,
        "max_recent_pullback_percent": 1.5,
        "min_smi": 20,
        "min_momentum_percent": 0,
        "min_recent_momentum_percent": 0,
        "min_long_momentum_percent": -0.25,
    },
    "loose_frequency_diagnostic": {
        "buy_rsi_min": 30,
        "buy_rsi_max": 80,
        "min_session_change_percent": 0,
        "volume_multiplier": 0.5,
        "max_session_pullback_percent": 5.0,
        "max_recent_pullback_percent": 2.0,
        "min_smi": 0,
        "min_momentum_percent": -0.05,
        "min_recent_momentum_percent": -0.05,
        "min_long_momentum_percent": -0.5,
        "min_vwap_distance_percent": -0.25,
        "max_vwap_distance_percent": 4.0,
    },
}


def load_backtester() -> Any:
    spec = importlib.util.spec_from_file_location("day_tape_backtest_compare", BACKTEST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BACKTEST_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def realized_pl(summary: dict[str, Any]) -> Decimal:
    return sum(
        (Decimal(str(row.get("realized_pl") or "0")) for row in summary.get("closed_trades", [])),
        Decimal("0"),
    )


def winner_count(summary: dict[str, Any]) -> int:
    return sum(1 for row in summary.get("closed_trades", []) if row.get("winner"))


def loser_count(summary: dict[str, Any]) -> int:
    return sum(1 for row in summary.get("closed_trades", []) if not row.get("winner"))


def symbol_counts(summary: dict[str, Any]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in summary.get("accepted_trades", []):
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            counts[symbol] = counts.get(symbol, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def compare_profile(
    backtester: Any,
    files: list[Path],
    name: str,
    overrides: dict[str, Any],
    *,
    max_events: int,
    latest_events: bool,
    warmup_events: int,
) -> dict[str, Any]:
    summary = backtester.run_backtest(
        files,
        max_events=max_events,
        latest_events=latest_events,
        warmup_events=warmup_events if latest_events else 0,
        strategy_overrides=overrides,
    )
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return {
        "name": name,
        "strategy_overrides": overrides,
        "accepted_trades": int(counts.get("accepted_trades") or 0),
        "closed_trades": int(counts.get("closed_trades") or 0),
        "open_positions": int(counts.get("open_positions") or 0),
        "rejected_candidates": int(counts.get("rejected_candidates") or 0),
        "evaluations": int(counts.get("evaluations") or 0),
        "warmup_events": int(counts.get("warmup_events") or 0),
        "realized_pl": str(realized_pl(summary).quantize(Decimal("0.000001"))),
        "winners": winner_count(summary),
        "losers": loser_count(summary),
        "symbols": symbol_counts(summary)[:12],
        "accepted_sample": summary.get("accepted_trades", [])[:10],
        "closed_sample": summary.get("closed_trades", [])[:10],
    }


def main() -> int:
    backtester = load_backtester()
    parser = argparse.ArgumentParser(description="Compare named app-engine strategy overrides on day tape.")
    parser.add_argument("--path", type=Path, default=backtester.default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=1, help="Most recent tape files when --path is a directory.")
    parser.add_argument("--max-events", type=int, default=80000, help="Events to evaluate. 0 means full selected file set.")
    parser.add_argument("--latest-events", action="store_true", help="Compare the latest event window.")
    parser.add_argument("--warmup-events", type=int, default=50000, help="Latest-window warm-up events.")
    parser.add_argument("--profiles", default=",".join(CANDIDATE_PROFILES), help="Comma-separated profile names.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a compact table.")
    args = parser.parse_args()

    files = backtester.selected_files(args.path, args.days)
    names = [name.strip() for name in args.profiles.split(",") if name.strip()]
    unknown = [name for name in names if name not in CANDIDATE_PROFILES]
    if unknown:
        raise SystemExit(f"Unknown profile(s): {', '.join(unknown)}")
    if not files:
        raise SystemExit(f"No day-tape files found in {args.path}")

    rows = [
        compare_profile(
            backtester,
            files,
            name,
            CANDIDATE_PROFILES[name],
            max_events=max(0, args.max_events),
            latest_events=bool(args.latest_events),
            warmup_events=max(0, args.warmup_events),
        )
        for name in names
    ]
    if args.json:
        print(json.dumps({"files": [item.name for item in files], "profiles": rows}, indent=2, sort_keys=True))
        return 0

    print(f"Files: {', '.join(item.name for item in files)}")
    print("profile accepted closed open realized_pl wins losses symbols")
    for row in rows:
        symbols = ",".join(f"{symbol}:{count}" for symbol, count in row["symbols"][:6]) or "-"
        print(
            f"{row['name']} {row['accepted_trades']} {row['closed_trades']} "
            f"{row['open_positions']} {row['realized_pl']} {row['winners']} {row['losers']} {symbols}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
