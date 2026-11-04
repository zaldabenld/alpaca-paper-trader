from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AppConfig, TraderEngine

from .test_regression_baselines import entry_ready_snapshot


def experiment_config(**overrides: Any) -> AppConfig:
    payload: dict[str, Any] = {
        "symbols": ["AAA"],
        "inverse_etf_mode": "exclude",
        "trade_size_mode": "notional",
        "max_trade_notional": "25",
        "buy_rsi_min": "40",
        "buy_rsi_max": "80",
        "min_entry_score": "1",
        "min_recent_momentum_percent": "0",
        "min_long_momentum_percent": "0",
        "min_session_change_percent": "0.5",
        "min_vwap_distance_percent": "0",
        "max_vwap_distance_percent": "5",
        "dry_run": True,
    }
    payload.update(overrides)
    return AppConfig(**payload)


def candidate(engine: TraderEngine, snapshot: Any) -> dict[str, Any] | None:
    with patch.object(engine, "snapshot", return_value=snapshot):
        return engine.entry_candidate(
            "AAA",
            0,
            {"equity": "1000", "buying_power": "1000"},
            None,
            open_position_count=0,
            open_orders=[],
            entries_allowed=True,
        )


class EntryExperimentGateTests(unittest.TestCase):
    def test_new_gates_default_off_and_survive_round_trip(self) -> None:
        config = AppConfig(symbols=["SPY"])
        self.assertEqual(config.min_session_pullback_percent, Decimal("0"))
        self.assertEqual(config.max_entry_rsi, Decimal("0"))
        self.assertEqual(config.max_entries_per_symbol_per_day, 0)

        tuned = experiment_config(
            min_session_pullback_percent="0.15", max_entry_rsi="60", max_entries_per_symbol_per_day=2
        )
        restored = engine_module.retune_strategy_config(AppConfig(**tuned.model_dump(mode="json")))
        self.assertEqual(restored.min_session_pullback_percent, Decimal("0.15"))
        self.assertEqual(restored.max_entry_rsi, Decimal("60"))
        self.assertEqual(restored.max_entries_per_symbol_per_day, 2)

    def test_switching_profiles_sets_and_clears_the_new_gates(self) -> None:
        tuned = experiment_config(
            min_session_pullback_percent="0.15", max_entry_rsi="60", max_entries_per_symbol_per_day=2
        )
        catalog = dict(engine_module.PROFILE_PRESETS)
        catalog["test-b"] = tuned.model_copy(update={"profile": "test-b"}).model_dump(mode="json")
        current = experiment_config(trade_size_mode="notional", max_trade_notional="25").model_dump(mode="json")

        switched = engine_module.config_from_profile("test-b", current, catalog)
        self.assertEqual(switched.min_session_pullback_percent, Decimal("0.15"))
        self.assertEqual(switched.max_entry_rsi, Decimal("60"))
        self.assertEqual(switched.max_entries_per_symbol_per_day, 2)
        self.assertEqual(switched.max_trade_notional, Decimal("25"))

        back = engine_module.config_from_profile("neutral", switched.model_dump(mode="json"), catalog)
        self.assertEqual(back.min_session_pullback_percent, Decimal("0"))
        self.assertEqual(back.max_entry_rsi, Decimal("0"))
        self.assertEqual(back.max_entries_per_symbol_per_day, 0)
        self.assertEqual(back.max_trade_notional, Decimal("25"))

    def test_defaults_leave_entry_selection_unchanged(self) -> None:
        engine = TraderEngine("experiment-defaults")
        engine.config = experiment_config()
        self.assertIsNotNone(candidate(engine, entry_ready_snapshot()))

    def test_max_entry_rsi_blocks_hot_entries(self) -> None:
        engine = TraderEngine("experiment-rsi")
        engine.config = experiment_config(max_entry_rsi="50")
        self.assertIsNone(candidate(engine, entry_ready_snapshot()))
        self.assertIn("above 50", engine.strategy_state.last_action["AAA"])

    def test_min_session_pullback_requires_a_pullback(self) -> None:
        engine = TraderEngine("experiment-pullback")
        engine.config = experiment_config(min_session_pullback_percent="0.15")
        snapshot = entry_ready_snapshot()
        self.assertIsNone(candidate(engine, snapshot))
        self.assertIn("no pullback", engine.strategy_state.last_action["AAA"])

        snapshot.session_pullback_percent = Decimal("0.2")
        self.assertIsNotNone(candidate(engine, snapshot))

    def test_daily_entry_cap_counts_todays_filled_buys(self) -> None:
        engine = TraderEngine("experiment-cap")
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        orders = [
            {"id": "1", "symbol": "AAA", "side": "buy", "filled_qty": "1", "filled_at": now.isoformat()},
            {"id": "2", "symbol": "AAA", "side": "buy", "filled_qty": "1", "filled_at": now.isoformat()},
            {"id": "2", "symbol": "AAA", "side": "buy", "filled_qty": "1", "filled_at": now.isoformat()},
            {"id": "3", "symbol": "AAA", "side": "buy", "filled_qty": "1", "filled_at": yesterday.isoformat()},
            {"id": "4", "symbol": "AAA", "side": "sell", "filled_qty": "1", "filled_at": now.isoformat()},
            {"id": "5", "symbol": "AAA", "side": "buy", "filled_qty": "0", "submitted_at": now.isoformat()},
        ]
        engine.sync_entries_today_from_orders(orders)
        self.assertEqual(engine.entries_today_by_symbol, {"AAA": 2})

        engine.config = experiment_config(max_entries_per_symbol_per_day=2)
        self.assertIsNone(candidate(engine, entry_ready_snapshot()))
        self.assertIn("bought 2x today", engine.strategy_state.last_action["AAA"])

        engine.config = experiment_config(max_entries_per_symbol_per_day=3)
        self.assertIsNotNone(candidate(engine, entry_ready_snapshot()))


if __name__ == "__main__":
    unittest.main()
