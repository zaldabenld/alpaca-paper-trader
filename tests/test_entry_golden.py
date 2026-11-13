"""Golden record of buy decisions: hold reasons, scores and candidates for fixed price paths.

The record was written by the code as it stood before the momentum and movers buy paths were merged
into one scored engine. Every later change to the buy path has to reproduce it exactly, for a movers
account and for the old gate-based styles alike. Regenerate only on purpose:
    GOLDEN_WRITE=1 .venv/bin/python -m unittest tests.test_entry_golden
"""

from __future__ import annotations

import json
import os
import random
import time as clock_module
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import inplay as inplay_logic  # noqa: E402
from alpaca_desktop import movers as M  # noqa: E402
from alpaca_desktop.engine import MARKET_TIMEZONE, AppConfig, TraderEngine, config_from_profile  # noqa: E402

D = Decimal
GOLDEN = Path(__file__).resolve().parent / "golden" / "entry_golden.json"
OPEN_UTC = datetime(2026, 11, 12, 14, 30, tzinfo=timezone.utc)  # 09:30 ET
CHECK_AT = (45, 75, 110, 149)

# Each config is given the way a settings file saved before the merge spells it.
CONFIGS: dict[str, dict[str, Any]] = {
    "movers-live": dict(entry_mode="movers", min_entry_score="60", stop_loss_percent="1.25", reentry_score_boost="20",
                        mover_weight_volume="45", mover_weight_half_hour_move="15", mover_weight_vwap="15",
                        mover_weight_five_min_move="10", mover_weight_range="10", mover_weight_session="5",
                        mover_weight_rsi="0", mover_volume_full_at="5", mover_weight_spread="40", mover_volume_current=True,
                        profit_trail_start_percent="2", profit_trail_drop_percent="1"),
    "movers-plain": dict(entry_mode="movers", min_entry_score="55", stop_loss_percent="2", reentry_score_boost="10",
                         mover_weight_volume="45", mover_weight_half_hour_move="15", mover_weight_vwap="15",
                         mover_weight_five_min_move="10", mover_weight_range="10", mover_weight_session="5",
                         mover_weight_rsi="5", mover_volume_full_at="5", mover_weight_spread="0", mover_volume_current=False),
    "neutral": dict(entry_mode="momentum"),
    "aggressive": dict(profile="aggressive"),
    "conservative-loose": dict(profile="conservative", buy_rsi_min="30", min_entry_score="20", min_smi="-100",
                               min_momentum_percent="-5", require_rising_price=False),
    # The old gates opened wide, so the old score, its minimum and the re-entry floor decide.
    "momentum-loose": dict(entry_mode="momentum", buy_rsi_min="0", buy_rsi_max="100", min_entry_score="35", min_smi="-100",
                           min_momentum_percent="-5", min_recent_momentum_percent="-5", min_long_momentum_percent="-5",
                           min_session_change_percent="-5", min_vwap_distance_percent="-5", max_vwap_distance_percent="50",
                           max_session_pullback_percent="50", max_recent_pullback_percent="50", require_rising_price=False,
                           volume_multiplier="0", min_buy_volume_ratio="0", reentry_score_boost="12"),
    "orb": dict(entry_mode="orb"),
}


def build_config(name: str) -> AppConfig:
    values = dict(CONFIGS[name])
    profile = values.pop("profile", None)
    base = dict(use_top_volume_symbols=False, symbols=["HOT"], dry_run=False)
    if profile:
        preset = config_from_profile(profile, AppConfig(**base).model_dump(mode="json")).model_dump(mode="json")
        return AppConfig(**(preset | values))
    return AppConfig(**(base | values))


def price_path(seed: int) -> list[tuple[D, D, D, int]]:
    """150 one-minute bars (close, high, low, volume): a seeded walk with its own drift and noise."""
    rng = random.Random(seed)
    price = D(str(rng.choice([1.2, 3.4, 11.0, 48.0, 190.0])))
    drift = rng.uniform(-0.0006, 0.0016)
    noise = rng.uniform(0.0004, 0.004)
    bars = []
    for _ in range(150):
        step = D(str(round(drift + rng.gauss(0, noise), 6)))
        price = max(D("0.2"), price * (D("1") + step))
        close = price.quantize(D("0.0001"))
        spread = (close * D(str(round(abs(rng.gauss(0, noise)), 6)))).quantize(D("0.0001"))
        bars.append((close, close + spread, max(D("0.01"), close - spread), rng.randint(200, 9000)))
    return bars


def stamp(minute: int) -> str:
    return (OPEN_UTC + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def record_for(name: str, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed * 7919 + 13)
    engine = TraderEngine("golden")
    engine.config = build_config(name)
    engine.connected = True
    engine.trading_enabled = True
    engine.mover_session = "2026-11-12"
    engine.mover_profiles = {"HOT": [1000.0] * M.SLOTS}
    engine.mover_stats = {"HOT": inplay_logic.DailyStats(atr_percent=D(str(rng.choice([1.5, 4, 8, 12]))), dollar_volume=D("90000000"))}
    engine.mover_volume = {"HOT": D(str(rng.choice([0.6, 1.4, 2.5, 5, 23])))}
    engine.mover_volume_recent = {"HOT": D(str(rng.choice([0.5, 1.4, 3, 9])))}
    today = datetime.now(MARKET_TIMEZONE).date()
    losses = rng.choice([0, 0, 1, 2])
    if losses:
        engine.reentry_losses_date = today
        engine.reentry_losses_today = {"HOT": {f"b{index}" for index in range(losses)}}
    if rng.random() < 0.3:
        engine.reentry_score_floors["HOT"] = D(str(rng.choice([55, 70, 85])))
    if rng.random() < 0.25:
        engine.mover_quotes["HOT"] = (D("1"), D("1.02"), clock_module.monotonic())  # a wide quote on record
    account = {"equity": "1000", "last_equity": "1000", "cash": "1000", "buying_power": "1000"}
    out: list[dict[str, Any]] = []
    for minute, (close, high, low, volume) in enumerate(price_path(seed)):
        engine.strategy_state.add_bar("HOT", close, stamp(minute), volume, high, low)
        if minute not in CHECK_AT:
            continue
        engine.mover_volume_at = clock_module.monotonic()
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            engine.clear_entry_score("HOT")
            hold = engine.entry_quality_hold_reason("HOT", engine.snapshot("HOT"), engine.config)
            score_after_hold = engine.strategy_state.entry_score.get("HOT")
            candidate = engine.entry_candidate("HOT", 3, account, None, 0, [], True)
        out.append({
            "config": name, "seed": seed, "minute": minute, "hold": hold,
            "score_after_hold": None if score_after_hold is None else str(score_after_hold),
            "candidate": None if candidate is None else {key: str(value) for key, value in sorted(candidate.items())},
            "last_action": engine.strategy_state.last_action.get("HOT", ""),
            "stop": str(engine.position_stop_price("HOT", close, close, engine.config)),
        })
    return out


def build_record() -> list[dict[str, Any]]:
    return [row for name in CONFIGS for seed in range(40) for row in record_for(name, seed)]


class EntryGoldenTests(unittest.TestCase):
    maxDiff = None

    def test_buy_decisions_match_the_record(self) -> None:
        record = build_record()
        if os.environ.get("GOLDEN_WRITE") == "1":
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(json.dumps(record, indent=0) + "\n", encoding="utf-8")
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(len(record), len(expected))
        for got, want in zip(record, expected):
            self.assertEqual(got, want)

    def test_the_record_covers_buys_and_every_kind_of_hold(self) -> None:
        expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
        by_config: dict[str, list[dict[str, Any]]] = {}
        for row in expected:
            by_config.setdefault(row["config"], []).append(row)
        for name in ("movers-live", "movers-plain", "momentum-loose", "orb"):
            self.assertTrue(any(row["candidate"] for row in by_config[name]), name)
        for name, rows in by_config.items():
            self.assertGreaterEqual(len({row["last_action"][:16] for row in rows}), 3, name)
        loose = by_config["momentum-loose"]
        self.assertTrue(any("re-entry needs" in row["last_action"] for row in loose))
        self.assertTrue(any(row["last_action"].startswith("Hold (score") for row in loose))


if __name__ == "__main__":
    unittest.main()
