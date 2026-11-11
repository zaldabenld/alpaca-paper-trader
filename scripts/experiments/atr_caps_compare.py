"""Replay each live profile (A/B/C) on slimmed day tapes with current rules vs. extension-cap variants.
Usage: python scripts/experiments/atr_caps_slim_tape.py <tape-YYYYMMDD.jsonl> $TAPE_DIR/tape-YYYYMMDD.jsonl
       LOCALAPPDATA=<scratch> TAPE_DIR=<dir> python scripts/experiments/atr_caps_compare.py YYYYMMDD ...

Per profile, only that profile's recorded strategy_scan events drive entries, so the base config is the
live config of that account. Today's B/C runs use the recorded daily RVOL picks (the live universe).
Sizing stays on the replay harness defaults (AGENTS.md); only stock-selection knobs vary.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE / "scripts"))
sys.path.insert(0, str(WORKTREE / "python_app"))

import day_tape_backtest as bt  # noqa: E402

HERE = Path(os.environ.get("TAPE_DIR") or Path(__file__).resolve().parent)  # slimmed tapes + results.json
INVERSE = {"SQQQ", "SPXU", "SDS", "SH", "PSQ", "TZA", "SOXS", "LABD", "QID", "DOG", "SPDN", "TECS", "FAZ", "SRTY"}
PROFILES = {"A": "test-a---control", "B": "test-b---anti-chase", "C": "test-c---cutoff--cap"}
VARIANTS = {
    "current": {},
    "atr_ref_0.15": {"extension_atr_reference_percent": "0.15"},
    "atr_ref_0.30": {"extension_atr_reference_percent": "0.30"},
    "atr_ref_0.60": {"extension_atr_reference_percent": "0.60"},
    "vwap_cap_3.5": {"max_vwap_distance_percent": "3.5"},
}
B_ONLY = {
    "rsi_ceiling_off": {"max_entry_rsi": "0"},
    "rsi_off+vwap_2.25": {"max_entry_rsi": "0", "max_vwap_distance_percent": "2.25"},
}


class ProfileReplay(bt.DayTapeBacktester):
    def __init__(self, profile: str, overrides: dict) -> None:
        super().__init__(strategy_overrides=overrides)
        self.profile = profile
        self.last_price: dict[str, Decimal] = {}

    def update_config(self, payload: dict) -> None:
        raw = payload.get("config") or {}
        super().update_config(payload)
        if raw.get("universe_mode") == "daily_rvol":
            self.engine.config = self.engine.config.model_copy(update={"universe_mode": "daily_rvol"})

    def handle_event(self, event: dict) -> None:
        kind = event.get("kind")
        payload = event.get("payload") or {}
        if kind == "strategy_scan" and (payload.get("config") or {}).get("profile") != self.profile:
            # another account's scan: keep its most-active list context, but no entries
            self.apply_strategy_scan_top_volume(payload)
            return
        if kind in ("daily_universe_pick", "daily_universe_recheck"):
            self.engine.apply_daily_universe(list(payload.get("symbols") or []), {"status": "picked"})
            return
        if kind == "market_bar" and payload.get("close") is not None:
            self.last_price[str(payload.get("symbol") or "").upper()] = Decimal(str(payload["close"]))
        super().handle_event(event)


def run(job: tuple[str, str, str, dict]) -> dict:
    day, letter, variant, overrides = job
    replay = ProfileReplay(PROFILES[letter], overrides)
    for event in bt.iter_tape_events([HERE / f"tape-{day}.jsonl"]):
        replay.handle_event(event)
    realized = sum((Decimal(t["realized_pl"]) for t in replay.closed_trades), Decimal("0"))
    unrealized = sum(
        ((replay.last_price.get(s, p.entry_price) - p.entry_price) * p.qty for s, p in replay.positions.items()),
        Decimal("0"),
    )
    entries = replay.accepted_trades
    return {
        "day": day,
        "profile": letter,
        "variant": variant,
        "entries": len(entries),
        "inverse_entries": sum(1 for t in entries if t["symbol"] in INVERSE),
        "wins": sum(1 for t in replay.closed_trades if t["winner"]),
        "losses": sum(1 for t in replay.closed_trades if not t["winner"]),
        "open": len(replay.positions),
        "realized": float(realized),
        "unrealized": float(unrealized),
        "total": float(realized + unrealized),
        "inverse_symbols": sorted({t["symbol"] for t in entries if t["symbol"] in INVERSE}),
        "hold_reasons": top_reasons(replay.rejected_candidates),
    }


def top_reasons(rejected: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rejected:
        reason = str(row.get("reason") or "").split(" ")[1].strip("(") if " " in str(row.get("reason")) else str(row.get("reason"))
        counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:6]


def main() -> None:
    days = sys.argv[1:] or ["20261104", "20261105"]
    jobs = []
    for day in days:
        for letter in PROFILES:
            variants = dict(VARIANTS, **(B_ONLY if letter == "B" else {}))
            jobs += [(day, letter, name, overrides) for name, overrides in variants.items()]
    with ProcessPoolExecutor(max_workers=min(len(jobs), 16)) as pool:
        rows = list(pool.map(run, jobs))
    (HERE / "results.json").write_text(json.dumps(rows, indent=1))
    for row in rows:
        print(f"{row['day']} {row['profile']} {row['variant']:<18} entries={row['entries']:>3} inv={row['inverse_entries']:>2} "
              f"W/L={row['wins']}/{row['losses']} open={row['open']} total=${row['total']:+.2f} {row['inverse_symbols']}")


if __name__ == "__main__":
    main()
