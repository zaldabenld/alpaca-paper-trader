from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import REPO_ROOT, configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import AppConfig, TraderEngine

from .test_risk_controls import NOW, FakeTradingClient, kinds

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import day_tape_backtest as bt  # noqa: E402


def snap(vwap: str = "1.5", change: str = "2", bias: str = "Bullish", rsi: str = "82") -> SimpleNamespace:
    """A steadily climbing fund: well above VWAP, up on the session, RSI far over the entry window."""
    return SimpleNamespace(
        price=Decimal("44"),
        rsi=Decimal(rsi),
        bias=bias,
        vwap_distance_percent=None if vwap == "" else Decimal(vwap),
        session_change_percent=None if change == "" else Decimal(change),
    )


def engine_with(**config: Any) -> TraderEngine:
    engine = TraderEngine("trend")
    engine.config = AppConfig(symbols=["SQQQ", "AAA"], use_top_volume_symbols=False, **config)
    return engine


class TrendHoldEntryTests(unittest.TestCase):
    def hold(self, engine: TraderEngine, symbol: str = "SQQQ", snapshot: Any = None) -> str:
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            return engine.entry_quality_hold_reason(symbol, snapshot or snap(), engine.config)

    def test_a_climbing_inverse_fund_is_rejected_for_high_rsi_without_trend_hold(self) -> None:
        self.assertEqual(self.hold(engine_with()), "Hold (RSI 82.0 above 65)")

    def test_trend_hold_buys_the_same_fund(self) -> None:
        self.assertEqual(self.hold(engine_with(inverse_trend_hold=True)), "")

    def test_needs_to_be_clearly_above_vwap_in_an_uptrend_and_up_on_the_session(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        self.assertEqual(self.hold(engine, snapshot=snap(vwap="0.1")), "Hold (trend hold: +0.10% vs VWAP)")
        self.assertEqual(self.hold(engine, snapshot=snap(vwap="-0.4")), "Hold (trend hold: -0.40% vs VWAP)")
        self.assertEqual(self.hold(engine, snapshot=snap(bias="Bearish")), "Hold (trend Bearish)")
        self.assertEqual(self.hold(engine, snapshot=snap(change="-0.2")), "Hold (trend hold: session -0.20%)")
        self.assertEqual(self.hold(engine, snapshot=snap(vwap="")), "Hold (trend hold warming)")
        self.assertEqual(self.hold(engine, snapshot=snap(bias="Waiting")), "Hold (trend hold warming)")

    def test_other_symbols_keep_the_profile_rules(self) -> None:
        self.assertEqual(self.hold(engine_with(inverse_trend_hold=True), "AAA"), self.hold(engine_with(), "AAA"))
        self.assertEqual(self.hold(engine_with(inverse_trend_hold=True), "AAA"), "Hold (RSI 82.0 above 65)")

    def test_excluding_inverse_etfs_wins_over_trend_hold(self) -> None:
        engine = engine_with(inverse_trend_hold=True, inverse_etf_mode="exclude")
        self.assertEqual(self.hold(engine), "Hold (inverse ETF excluded)")

    def test_buys_per_fund_per_day_are_capped(self) -> None:
        engine = engine_with(inverse_trend_hold=True, inverse_trend_max_entries=2)
        engine.entries_today_by_symbol = {"SQQQ": 1}
        self.assertEqual(self.hold(engine), "")
        engine.entries_today_by_symbol = {"SQQQ": 2}
        self.assertEqual(self.hold(engine), "Hold (trend hold: bought 2x today)")

    def test_a_halted_fund_is_not_bought(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        with patch.object(engine, "halt_hold_reason", return_value="Hold (halt/status Halted)"):
            self.assertEqual(self.hold(engine), "Hold (halt/status Halted)")

    def test_candidate_ranks_ahead_of_ordinary_scores_in_momentum_and_orb_profiles(self) -> None:
        for mode in ("momentum", "orb"):
            engine = engine_with(inverse_trend_hold=True, entry_mode=mode)
            with (
                patch.object(engine, "snapshot", return_value=snap()),
                patch.object(engine, "asset_tradeability_hold_reason", return_value=""),
            ):
                candidate = engine.entry_candidate("SQQQ", 3, {"equity": "1000"}, None, 0, [], True)
            self.assertIsNotNone(candidate, mode)
            self.assertGreater(candidate["score"], Decimal("99"))
            self.assertEqual(engine.strategy_state.last_action["SQQQ"], "Candidate trend hold")
            self.assertGreaterEqual(engine.strategy_state.entry_score["SQQQ"], engine.config.min_entry_score)

    def test_settings_are_clamped_and_off_by_default(self) -> None:
        self.assertFalse(AppConfig().inverse_trend_hold)
        config = AppConfig(inverse_trend_stop_percent="0", inverse_trend_exit_percent="50", inverse_trend_max_entries=99)
        self.assertEqual(config.inverse_trend_stop_percent, Decimal("0.5"))
        self.assertEqual(config.inverse_trend_exit_percent, Decimal("5"))
        self.assertEqual(config.inverse_trend_max_entries, 10)


class TrendHoldExitTests(unittest.TestCase):
    POSITION = {"symbol": "SQQQ", "qty": "1", "avg_entry_price": "40", "current_price": "44"}

    def decide(self, engine: TraderEngine, price: str, vwap: str, has_stop: bool = True) -> str:
        with patch.object(engine, "snapshot", return_value=snap(vwap=vwap)):
            reason, _ = engine.local_protection_exit_decision(
                "SQQQ", engine.config, dict(self.POSITION, current_price=price), Decimal(price), False, has_stop
            )
        return reason

    def test_a_big_winner_above_vwap_is_held_past_take_profit_and_trailing(self) -> None:
        engine = engine_with(inverse_trend_hold=True, take_profit_percent="2.5", profit_trail_start_percent="3",
                             profit_trail_drop_percent="1")
        self.assertEqual(self.decide(engine, "44", "1.5"), "")  # +10%: no take-profit
        self.assertEqual(self.decide(engine, "43", "0.4"), "")  # gave back 2.3% from the peak: no trail
        self.assertEqual(self.decide(engine, "43", "-0.2"), "")  # inside the exit buffer

    def test_the_same_winner_is_sold_by_the_profile_rules_without_trend_hold(self) -> None:
        engine = engine_with(take_profit_percent="2.5")
        self.assertIn("local take-profit", self.decide(engine, "44", "1.5"))

    def test_hold_ends_once_the_fund_is_under_vwap_even_beside_a_live_stop(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        reason = self.decide(engine, "43", "-0.31", has_stop=True)
        self.assertEqual(reason, "trend hold ended: -0.31% under VWAP (gain 7.50%)")
        self.assertTrue(engine.is_trend_hold_exit_reason(reason))
        self.assertEqual(engine.exit_reason_label("sell", "Strategy Exit", reason), "Trend Hold Ended")

    def test_stop_is_one_wide_level_from_entry_that_never_ratchets(self) -> None:
        engine = engine_with(inverse_trend_hold=True, inverse_trend_stop_percent="3", breakeven_at_percent="1",
                             profit_trail_start_percent="3", profit_trail_drop_percent="1")
        self.assertEqual(engine.position_stop_price("SQQQ", Decimal("40"), Decimal("44"), engine.config), Decimal("38.80"))
        self.assertEqual(engine.position_stop_price("SQQQ", Decimal("40"), Decimal("41"), engine.config), Decimal("38.80"))
        self.assertEqual(engine.position_take_profit_price("SQQQ", Decimal("40"), engine.config), Decimal("0"))
        # An ordinary stock on the same profile still ratchets and keeps its target.
        self.assertGreater(engine.position_stop_price("AAA", Decimal("40"), Decimal("44"), engine.config), Decimal("40"))
        self.assertGreater(engine.position_take_profit_price("AAA", Decimal("40"), engine.config), Decimal("40"))

    def test_hard_stop_sells_locally_when_no_broker_stop_is_working(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        self.assertIn("local stop-loss 3%", self.decide(engine, "38.7", "0.5", has_stop=False))
        self.assertEqual(self.decide(engine, "38.7", "0.5", has_stop=True), "")  # the broker stop handles it


class SqqqClient(FakeTradingClient):
    """One long SQQQ position whose shares are all held by the app's own stop."""

    def get_all_positions(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "SQQQ",
                "qty": "0.5",
                "qty_available": "0" if self.open_orders else "0.5",
                "avg_entry_price": self.entry,
                "current_price": self.price,
                "market_value": str(Decimal(self.price) * Decimal("0.5")),
                "unrealized_pl": "0",
                "side": "long",
            }
        ]


def live_engine(client: FakeTradingClient, closes: list[float], **config: Any) -> TraderEngine:
    engine = TraderEngine("trend-live")
    engine.config = AppConfig(
        symbols=["SQQQ"], use_top_volume_symbols=False, dry_run=False, inverse_trend_hold=True,
        stop_loss_percent="1.25", take_profit_percent="2.5", **config,
    )
    engine.connected = True
    engine.trading_client = client  # type: ignore[assignment]
    engine.data_client = object()  # type: ignore[assignment]
    for index, close in enumerate(closes):
        stamp = NOW - timedelta(minutes=len(closes) - index)
        engine.strategy_state.add_bar("SQQQ", close, stamp, 1000, close, close)
    return engine


def refresh(engine: TraderEngine) -> None:
    with (
        patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
        patch.object(engine, "record_day_tape_scan"),
        patch.object(engine, "record_day_tape_bars"),
        patch.object(engine, "entry_open_guard_message", return_value=""),
        patch.object(engine, "wait_for_symbol_app_orders_cleared", return_value=True),
    ):
        engine.refresh(run_strategy=False, shared_bars={"SQQQ": []})


STOP = {"id": "s1", "symbol": "SQQQ", "side": "sell", "type": "stop", "qty": "0.5", "filled_qty": "0",
        "stop_price": "38.80", "client_order_id": "apt-protect-sl-sqqq-1"}


class TrendHoldLiveOrderTests(unittest.TestCase):
    def test_new_position_gets_the_wide_stop_and_no_profit_target(self) -> None:
        client = SqqqClient(is_open=True, price="44", entry="40")
        engine = live_engine(client, [40 + step * 0.1 for step in range(41)])
        refresh(engine)
        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(str(client.submitted[0].stop_price), "38.8")

    def test_held_above_vwap_nothing_is_sent(self) -> None:
        client = SqqqClient(is_open=True, price="44", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [40 + step * 0.1 for step in range(41)])
        refresh(engine)
        self.assertEqual(client.cancelled, [])
        self.assertEqual(client.submitted, [])

    def test_under_vwap_cancels_its_stop_and_sells_every_share_in_one_pass(self) -> None:
        # qty_available is 0 because the stop holds the shares; the sell must still be for all 0.5.
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        refresh(engine)
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "0.5")

    def test_trend_exit_waits_out_the_opening_guard(self) -> None:
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        with (
            patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
            patch.object(engine, "record_day_tape_scan"),
            patch.object(engine, "record_day_tape_bars"),
            patch.object(engine, "entry_open_guard_message", return_value="open guard: 10 min left"),
        ):
            engine.refresh(run_strategy=False, shared_bars={"SQQQ": []})
        self.assertEqual(client.cancelled, [])
        self.assertEqual(client.submitted, [])
        self.assertEqual(engine.strategy_state.last_action["SQQQ"], "Hold (open guard trend exit)")


class ReplayEntryCountTests(unittest.TestCase):
    def test_replay_counts_buys_per_symbol_and_resets_each_session(self) -> None:
        replay = bt.DayTapeBacktester()
        replay.reset_entry_counts_for_session("2026-11-05T15:00:00+00:00")
        replay.engine.entries_today_by_symbol["SQQQ"] = 2
        replay.reset_entry_counts_for_session("2026-11-05T19:00:00+00:00")
        self.assertEqual(replay.engine.entries_today_by_symbol, {"SQQQ": 2})
        replay.reset_entry_counts_for_session("2026-11-06T15:00:00+00:00")
        self.assertEqual(replay.engine.entries_today_by_symbol, {})


if __name__ == "__main__":
    unittest.main()
