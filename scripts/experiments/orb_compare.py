"""Replay opening-range-breakout (ORB) entries against the live profiles' current rules on slimmed day tapes.

Usage: LOCALAPPDATA=<scratch> TAPE_DIR=<dir with slimmed tape-YYYYMMDD.jsonl> python scripts/experiments/orb_compare.py YYYYMMDD
B's scans carry the daily relative-volume list; A's carry the top-100 most-active list.
Replay fills at 1-min bar closes and does not simulate the close flatten; open positions are marked to the last bar.
"""
from __future__ import annotations

import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import atr_caps_compare as base  # noqa: E402

ORB = {"entry_mode": "orb", "orb_minutes": 15}
VARIANTS = {
    "current rules": {},
    "ORB15 tp2.5/sl1.25": dict(ORB),
    "ORB15 tp4/sl2": dict(ORB, take_profit_percent="4", stop_loss_percent="2"),
    "ORB15 tp6/sl2": dict(ORB, take_profit_percent="6", stop_loss_percent="2"),
    "ORB15 no cap tp4/sl2": dict(ORB, orb_max_breakout_percent="0", take_profit_percent="4", stop_loss_percent="2"),
    "ORB5 tp4/sl2": dict(ORB, orb_minutes=5, take_profit_percent="4", stop_loss_percent="2"),
}


class OrbReplay(base.ProfileReplay):
    def evaluate_entries(self, event_time: str = "") -> None:
        before = len(self.accepted_trades)
        super().evaluate_entries(event_time)
        for trade in self.accepted_trades[before:]:  # live counts fills; replay counts accepted entries
            symbol = trade["symbol"]
            self.engine.entries_today_by_symbol[symbol] = self.engine.entries_today_by_symbol.get(symbol, 0) + 1


def run(day: str, letter: str, name: str, overrides: dict) -> dict:
    replay = OrbReplay(base.PROFILES[letter], overrides)
    for event in base.bt.iter_tape_events([base.HERE / f"tape-{day}.jsonl"]):
        replay.handle_event(event)
    gains = [float((Decimal(t["exit_price"]) / Decimal(t["entry_price"]) - 1) * 100) for t in replay.closed_trades]
    open_gains = [
        float((replay.last_price.get(s, p.entry_price) / p.entry_price - 1) * 100) for s, p in replay.positions.items()
    ]
    every = gains + open_gains
    return {
        "day": day, "list": "daily RVOL (B)" if letter == "B" else "top 100 (A)", "variant": name,
        "entries": len(replay.accepted_trades), "closed": len(gains),
        "wins": sum(g > 0 for g in gains), "losses": sum(g <= 0 for g in gains), "open": len(open_gains),
        "avg_pct": statistics.mean(every) if every else 0.0, "sum_pct": sum(every),
        "first_entries": [(t["time"][11:16], t["symbol"]) for t in replay.accepted_trades[:8]],
    }


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else "20261105"
    rows = [run(day, letter, name, ov) for letter in ("B", "A") for name, ov in VARIANTS.items()]
    (base.HERE / f"orb-results-{day}.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        print(f"{r['list']:<15} {r['variant']:<22} entries={r['entries']:>3} W/L={r['wins']}/{r['losses']} open={r['open']:>2} "
              f"avg/trade={r['avg_pct']:+.2f}% sum={r['sum_pct']:+.1f}%  {r['first_entries'][:5]}")


if __name__ == "__main__":
    main()
