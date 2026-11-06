"""The entry path follows the documented strategy: rising price, entry pacing, loss-only re-entry bar."""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import AppConfig, TraderEngine
from alpaca_desktop.strategy import StrategyState

from .test_entry_experiment_gates import candidate, experiment_config
from .test_regression_baselines import entry_ready_snapshot


class RisingPriceGateTests(unittest.TestCase):
    def test_defaults_are_on(self) -> None:
        config = AppConfig(symbols=["SPY"])
        self.assertTrue(config.require_rising_price)
        self.assertEqual(config.max_entries_per_scan, 2)
        self.assertEqual(config.entry_spacing_seconds, 0)  # a timed lock on entries: opt-in only

    def test_session_pullback_floor_is_clamped_to_the_cap(self) -> None:
        config = experiment_config(min_session_pullback_percent="2", max_session_pullback_percent="0.75")
        self.assertEqual(config.min_session_pullback_percent, Decimal("0.75"))

    def test_fresh_stream_trade_below_last_close_holds(self) -> None:
        engine = TraderEngine("rising-live")
        engine.config = experiment_config()
        snapshot = entry_ready_snapshot("10")  # last close 10, last bar +0.2%
        now = datetime.now(timezone.utc)
        engine.update_dashboard_trade({"symbol": "AAA", "price": "9.95", "size": 100, "timestamp": now.isoformat()})
        self.assertIsNone(candidate(engine, snapshot))
        self.assertIn("price slipping", engine.strategy_state.last_action["AAA"])

        engine.update_dashboard_trade({"symbol": "AAA", "price": "10.02", "size": 100, "timestamp": (now + timedelta(seconds=1)).isoformat()})
        self.assertIsNotNone(candidate(engine, snapshot))

    def test_stale_or_backfilled_trades_are_ignored(self) -> None:
        engine = TraderEngine("rising-stale")
        engine.config = experiment_config()
        old = datetime.now(timezone.utc) - timedelta(minutes=10)
        engine.update_dashboard_trade({"symbol": "AAA", "price": "9.0", "size": 100, "timestamp": old.isoformat()})
        self.assertIsNotNone(candidate(engine, entry_ready_snapshot("10")))
        # a REST backfill (count_volume=False) never feeds the rising check
        engine.update_dashboard_trade(
            {"symbol": "AAA", "price": "9.0", "size": 100, "timestamp": datetime.now(timezone.utc).isoformat()}, count_volume=False
        )
        self.assertIsNotNone(candidate(engine, entry_ready_snapshot("10")))
        # an older trade arriving late does not overwrite a newer one
        now = datetime.now(timezone.utc)
        engine.update_dashboard_trade({"symbol": "AAA", "price": "10.5", "size": 100, "timestamp": now.isoformat()})
        engine.update_dashboard_trade({"symbol": "AAA", "price": "9.0", "size": 100, "timestamp": (now - timedelta(seconds=30)).isoformat()})
        self.assertIsNotNone(candidate(engine, entry_ready_snapshot("10")))

    def test_gate_can_be_turned_off(self) -> None:
        engine = TraderEngine("rising-off")
        engine.config = experiment_config(require_rising_price=False)
        snapshot = entry_ready_snapshot()
        snapshot.last_bar_change_percent = Decimal("-0.5")
        self.assertIsNotNone(candidate(engine, snapshot))

    def test_buy_flow_floor_is_the_configured_ratio(self) -> None:
        engine = TraderEngine("flow-floor")
        engine.config = experiment_config(min_buy_volume_ratio="0.50")
        with patch.object(engine, "order_flow_ratio", return_value=Decimal("0.49")):
            self.assertIsNone(candidate(engine, entry_ready_snapshot()))
            self.assertIn("buy flow 49.0%", engine.strategy_state.last_action["AAA"])
        engine.config = experiment_config(min_buy_volume_ratio="0")
        with patch.object(engine, "order_flow_ratio", return_value=Decimal("0.10")):
            self.assertIsNotNone(candidate(engine, entry_ready_snapshot()))


class LongMomentumWarmupTests(unittest.TestCase):
    def test_long_momentum_warms_instead_of_copying_session_change(self) -> None:
        state = StrategyState()
        start = datetime(2026, 11, 6, 14, 30, tzinfo=timezone.utc)  # 09:30 ET
        for minute in range(8):
            state.add_bar("AAA", str(100 + minute), start + timedelta(minutes=minute))
        early = state.snapshot("AAA", 9, 21, momentum_period=6)
        self.assertIsNone(early.long_momentum_percent)
        self.assertIsNotNone(early.session_change_percent)
        for minute in range(8, 20):
            state.add_bar("AAA", str(100 + minute), start + timedelta(minutes=minute))
        later = state.snapshot("AAA", 9, 21, momentum_period=6)
        self.assertIsNotNone(later.long_momentum_percent)
        self.assertEqual(later.previous_close, Decimal("118"))
        self.assertEqual(later.last_bar_change_percent.quantize(Decimal("0.01")), Decimal("0.85"))


class FlatClient:
    """No positions, no orders, market open: only entries matter."""

    def get_account(self) -> dict[str, Any]:
        return {"equity": "1000", "last_equity": "1000", "buying_power": "1000", "cash": "1000"}

    def get_clock(self) -> Any:
        now = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)
        return SimpleNamespace(is_open=True, timestamp=now, next_open=now + timedelta(days=1), next_close=now + timedelta(hours=5))

    def get_all_positions(self) -> list[dict[str, Any]]:
        return []

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        return []


class EntryPacingTests(unittest.TestCase):
    def run_scan(self, engine: TraderEngine) -> list[str]:
        symbols = ["AAA", "BBB", "CCC", "DDD"]
        bought: list[str] = []

        def fake_candidate(symbol: str, rank: int, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"symbol": symbol, "rank": rank, "score": Decimal("90") - rank}

        def fake_apply(symbol: str, *args: Any, **kwargs: Any) -> tuple[list, bool, dict[str, Any]]:
            bought.append(symbol)
            return [], False, {"side": "buy", "symbol": symbol, "notional": Decimal("25")}

        with (
            patch.object(engine, "entry_candidate", side_effect=fake_candidate),
            patch.object(engine, "apply_strategy", side_effect=fake_apply),
            patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
            patch.object(engine, "record_day_tape_scan"),
            patch.object(engine, "record_day_tape_bars"),
        ):
            engine.refresh(run_strategy=True, shared_bars={symbol: [] for symbol in symbols})
        return bought

    def pacing_engine(self, **config: Any) -> TraderEngine:
        engine = TraderEngine("pacing-loop")
        engine.config = AppConfig(
            symbols=["AAA", "BBB", "CCC", "DDD"], use_top_volume_symbols=False, inverse_etf_mode="exclude",
            dry_run=True, max_open_positions=20, entry_open_guard_minutes=0, entry_close_guard_minutes=0, **config,
        )
        engine.connected = True
        engine.trading_client = FlatClient()  # type: ignore[assignment]
        engine.data_client = object()  # type: ignore[assignment]
        engine.trading_enabled = True
        return engine

    def test_per_scan_cap_limits_buys_in_one_scan(self) -> None:
        engine = self.pacing_engine(max_entries_per_scan=2)
        self.assertEqual(self.run_scan(engine), ["AAA", "BBB"])
        self.assertIn("entry cap 2/scan", engine.strategy_state.last_action["CCC"])
        engine = self.pacing_engine(max_entries_per_scan=0)
        self.assertEqual(len(self.run_scan(engine)), 4)

    def test_spacing_allows_one_buy_then_holds(self) -> None:
        engine = self.pacing_engine(max_entries_per_scan=0, entry_spacing_seconds=30)
        self.assertEqual(self.run_scan(engine), ["AAA"])
        self.assertIn("entry spacing", engine.strategy_state.last_action["BBB"])
        self.assertEqual(self.run_scan(engine), [])

    def test_per_scan_cap_and_spacing(self) -> None:
        engine = TraderEngine("pacing")
        engine.config = experiment_config(max_entries_per_scan=2, entry_spacing_seconds=30)
        self.assertEqual(engine.entry_spacing_hold_reason(engine.config), "")
        engine.last_entry_submitted_at = time.monotonic() - 5
        self.assertIn("entry spacing", engine.entry_spacing_hold_reason(engine.config))
        engine.last_entry_submitted_at = time.monotonic() - 31
        self.assertEqual(engine.entry_spacing_hold_reason(engine.config), "")
        engine.config = experiment_config(entry_spacing_seconds=0)
        engine.last_entry_submitted_at = time.monotonic()
        self.assertEqual(engine.entry_spacing_hold_reason(engine.config), "")


class LossOnlyReentryTests(unittest.TestCase):
    def closed(self, realized: Decimal | None, reason: str = "", client_id: str = "apt-exit-aaa-1") -> bool:
        engine = TraderEngine("reentry")
        item: dict[str, Any] = {"symbol": "AAA", "side": "sell", "client_order_id": client_id, "type": "market"}
        return engine.closed_sell_needs_reentry_floor(item, reason, realized)

    def test_only_losing_or_stop_exits_raise_the_bar(self) -> None:
        self.assertTrue(self.closed(Decimal("-0.30")))
        self.assertFalse(self.closed(Decimal("0.65")))
        self.assertTrue(self.closed(Decimal("0.10"), "local stop-loss 1.25% (gain 0.1%)"))  # a stop fill always counts
        self.assertFalse(self.closed(Decimal("0.65"), "local take-profit 2.5% (gain 2.6%)"))
        self.assertTrue(self.closed(None, "local stop-loss 1.25% (gain -1.3%)"))
        self.assertFalse(self.closed(None, "local take-profit 2.5% (gain 2.6%)"))
        self.assertTrue(self.closed(None, "", "apt-protect-sl-aaa-1"))
        self.assertFalse(self.closed(None, "", "apt-protect-tp-aaa-1"))

    def test_take_profit_submit_leaves_no_floor_but_stop_loss_does(self) -> None:
        engine = TraderEngine("reentry-submit")
        engine.config = experiment_config(reentry_score_boost="10")
        snapshot = entry_ready_snapshot()
        engine.record_loss_reentry_floor("AAA", snapshot, "local take-profit 2.5% (gain 2.6%)")
        self.assertNotIn("AAA", engine.reentry_score_floors)
        engine.record_loss_reentry_floor("AAA", snapshot, "local stop-loss 1.25% (gain -1.3%)")
        self.assertIn("AAA", engine.reentry_score_floors)


if __name__ == "__main__":
    unittest.main()
