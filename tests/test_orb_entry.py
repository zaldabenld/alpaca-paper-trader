from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AppConfig, TraderEngine
from alpaca_desktop.strategy import StrategyState, opening_range


OPEN_UTC = datetime(2026, 11, 5, 14, 30, tzinfo=timezone.utc)  # 09:30 ET


def stamp(minute: int, day_offset: int = 0) -> str:
    return (OPEN_UTC + timedelta(days=day_offset, minutes=minute)).isoformat().replace("+00:00", "Z")


def add_range(state: StrategyState, symbol: str = "AAA", bars: int = 15) -> None:
    # 09:30-09:44: closes 10.00-10.28, highs +0.2 (range high 10.48), lows -0.2 (range low 9.80)
    for minute in range(bars):
        close = 10 + minute * 0.02
        state.add_bar(symbol, close, stamp(minute), 1000, close + 0.2, close - 0.2)


class OpeningRangeTests(unittest.TestCase):
    def test_range_is_high_and_low_of_first_minutes_and_completes_at_cutoff(self) -> None:
        state = StrategyState()
        state.add_bar("AAA", 50, stamp(0, day_offset=-1), 1000, 60, 40)  # yesterday is ignored
        add_range(state)
        forming = state.opening_range("AAA", 15)
        self.assertIsNotNone(forming)
        self.assertFalse(forming.complete)
        state.add_bar("AAA", 10.3, stamp(15), 1000, 10.3, 10.3)
        done = state.opening_range("AAA", 15)
        self.assertTrue(done.complete)
        self.assertAlmostEqual(float(done.high), 10.48)
        self.assertAlmostEqual(float(done.low), 9.80)
        self.assertEqual(done.bars, 15)

    def test_sparse_range_is_not_trusted(self) -> None:
        state = StrategyState()
        add_range(state, bars=5)
        state.add_bar("AAA", 10.3, stamp(20), 1000, 10.3, 10.3)
        self.assertIsNone(opening_range(state.histories["AAA"], 15))


class OrbEntryTests(unittest.TestCase):
    def engine_with_range(self, **config: object) -> TraderEngine:
        engine = TraderEngine("orb")
        engine.config = AppConfig(symbols=["AAA"], use_top_volume_symbols=False, **{"entry_mode": "orb", **config})
        add_range(engine.strategy_state)
        return engine

    def hold(self, engine: TraderEngine) -> str:
        with (
            patch.object(engine, "order_flow_hold_reason", return_value=""),
            patch.object(engine, "asset_tradeability_hold_reason", return_value=""),
        ):
            return engine.orb_entry_hold_reason("AAA", engine.snapshot("AAA"), engine.config)

    def test_breakout_above_range_high_and_vwap_is_a_candidate(self) -> None:
        engine = self.engine_with_range()
        engine.strategy_state.add_bar("AAA", 10.55, stamp(16), 1000, 10.55, 10.5)
        self.assertEqual(self.hold(engine), "")

    def test_range_still_forming_holds(self) -> None:
        engine = TraderEngine("orb")
        engine.config = AppConfig(symbols=["AAA"], use_top_volume_symbols=False, entry_mode="orb")
        add_range(engine.strategy_state, bars=10)
        self.assertEqual(self.hold(engine), "Hold (opening range forming)")

    def test_inside_range_holds(self) -> None:
        engine = self.engine_with_range()
        engine.strategy_state.add_bar("AAA", 10.4, stamp(16), 1000, 10.45, 10.35)
        self.assertIn("inside opening range", self.hold(engine))

    def test_breakout_too_far_past_range_holds(self) -> None:
        engine = self.engine_with_range(orb_max_breakout_percent="1")
        engine.strategy_state.add_bar("AAA", 10.7, stamp(16), 1000, 10.7, 10.6)
        self.assertIn("breakout extended", self.hold(engine))

    def test_breakout_below_vwap_holds(self) -> None:
        engine = self.engine_with_range()
        for minute in range(15, 30):  # heavy volume up at 12 drags VWAP above the later breakout price
            engine.strategy_state.add_bar("AAA", 12, stamp(minute), 50000, 12, 12)
        engine.strategy_state.add_bar("AAA", 10.55, stamp(31), 1000, 10.55, 10.5)
        self.assertEqual(self.hold(engine), "Hold (below VWAP)")

    def test_one_entry_per_symbol_per_day(self) -> None:
        engine = self.engine_with_range()
        engine.strategy_state.add_bar("AAA", 10.55, stamp(16), 1000, 10.55, 10.5)
        engine.entries_today_by_symbol = {"AAA": 1}
        self.assertEqual(self.hold(engine), "Hold (ORB: one entry per day)")

    def test_orb_settings_are_profile_keys_and_presets_default_to_the_scored_style_with_trend_checks(self) -> None:
        for key in ("entry_mode", "orb_minutes", "orb_max_breakout_percent"):
            self.assertIn(key, engine_module.PROFILE_STRATEGY_KEYS)
        for preset in engine_module.PROFILE_PRESETS.values():
            self.assertEqual(preset.get("entry_mode"), "scored")
            self.assertIs(preset.get("use_trend_checks"), True)
            self.assertEqual(preset.get("reentry_rule"), "floor")
            self.assertEqual(float(preset.get("mover_weight_volume")), 0.0)

    def test_momentum_mode_never_calls_the_orb_path(self) -> None:
        engine = self.engine_with_range(entry_mode="momentum")
        engine.strategy_state.add_bar("AAA", 10.55, stamp(16), 1000, 10.55, 10.5)
        with patch.object(engine, "orb_entry_candidate") as orb:
            engine.entry_candidate("AAA", 0, {}, None, 0, [], True)
        orb.assert_not_called()

    def test_entry_mode_is_validated(self) -> None:
        self.assertEqual(AppConfig(entry_mode=" ORB ").entry_mode, "orb")
        with self.assertRaises(ValueError):
            AppConfig(entry_mode="breakout")


if __name__ == "__main__":
    unittest.main()
