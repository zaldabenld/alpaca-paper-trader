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


def engine_with(session_ready: bool = True, **config: Any) -> TraderEngine:
    engine = TraderEngine("trend")
    engine.config = AppConfig(symbols=["SQQQ", "AAA"], use_top_volume_symbols=False, **config)
    if session_ready:  # these tests feed snapshots directly; the bar-count guard has its own tests
        engine.inverse_trend_session_ready = lambda symbol: True  # type: ignore[method-assign]
    return engine


class TrendHoldEntryTests(unittest.TestCase):
    def hold(self, engine: TraderEngine, symbol: str = "SQQQ", snapshot: Any = None) -> str:
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            return engine.entry_quality_hold_reason(symbol, snapshot or snap(), engine.config)

    def test_a_climbing_inverse_fund_is_rejected_for_high_rsi_without_trend_hold(self) -> None:
        self.assertEqual(self.hold(engine_with()), "Hold (RSI 82.0 above 65)")

    def test_trend_hold_buys_the_same_fund(self) -> None:
        self.assertEqual(self.hold(engine_with(inverse_trend_hold=True)), "")

    def test_needs_to_be_above_vwap_in_an_uptrend_and_up_on_the_session(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        self.assertEqual(self.hold(engine, snapshot=snap(vwap="0")), "Hold (trend hold: +0.00% vs VWAP)")
        self.assertEqual(self.hold(engine, snapshot=snap(vwap="0.01")), "")  # above VWAP is enough, no buffer
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
        config = AppConfig(inverse_trend_stop_percent="0", inverse_trend_exit_percent="50", inverse_trend_max_entries=99,
                           inverse_trend_lock_at_percent="90", inverse_trend_trail_percent="-1")
        self.assertEqual(config.inverse_trend_stop_percent, Decimal("0.5"))
        self.assertEqual(config.inverse_trend_exit_percent, Decimal("5"))
        self.assertEqual(config.inverse_trend_max_entries, 10)
        self.assertEqual(config.inverse_trend_lock_at_percent, Decimal("50"))
        self.assertEqual(config.inverse_trend_trail_percent, Decimal("0"))

    def test_a_stop_earlier_today_does_not_block_the_rebuy_with_a_score_floor(self) -> None:
        # A trend candidate carries an ordering number, not a score: a 100-point re-entry floor left
        # by an earlier stop, or a 100 minimum score, must not hold it.
        client = FakeTradingClient(is_open=True)
        client.get_all_positions = lambda: []  # type: ignore[method-assign]
        engine = engine_with(inverse_trend_hold=True, min_entry_score="100", dry_run=True)
        engine.reentry_score_floors["SQQQ"] = Decimal("100")
        with (
            patch.object(engine, "snapshot", return_value=snap()),
            patch.object(engine, "asset_tradeability_hold_reason", return_value=""),
            patch.object(engine, "current_trade_price", return_value=Decimal("44")),
            patch.object(engine, "intent_reason", return_value="test"),
        ):
            engine.entry_candidate("SQQQ", 3, {"equity": "1000"}, None, 0, [], True)
            events, _, reservation = engine.apply_strategy(
                "SQQQ", {"equity": "1000", "buying_power": "1000"}, None, 0, [], Decimal("0")
            )
        self.assertIsNotNone(reservation, engine.strategy_state.last_action.get("SQQQ"))
        self.assertEqual(reservation["side"], "buy")


class TrendHoldSessionDataTests(unittest.TestCase):
    def engine(self, bars: int, day_offset: int = 0, clock_date: str = "2026-11-04") -> TraderEngine:
        engine = engine_with(session_ready=False, inverse_trend_hold=True)
        engine.market_clock = {"session_date": clock_date}
        for index in range(bars):
            stamp = NOW + timedelta(days=day_offset, minutes=index)
            engine.strategy_state.add_bar("SQQQ", 44 - index * 0.01, stamp, 1000, 44, 43)
        return engine

    def test_any_bar_from_today_is_enough(self) -> None:
        self.assertTrue(self.engine(bars=1).inverse_trend_session_ready("SQQQ"))

    def test_yesterdays_bars_are_not_todays_vwap(self) -> None:
        self.assertFalse(self.engine(bars=30, day_offset=-1).inverse_trend_session_ready("SQQQ"))
        # The replay has no market clock; it judges the tape's own session.
        self.assertTrue(self.engine(bars=30, day_offset=-1, clock_date="").inverse_trend_session_ready("SQQQ"))

    def test_no_exit_and_no_entry_until_the_session_is_ready(self) -> None:
        engine = self.engine(bars=30, day_offset=-1)  # only yesterday's bars so far
        with patch.object(engine, "snapshot", return_value=snap(vwap="-2")):
            self.assertEqual(engine.inverse_trend_exit_reason("SQQQ", engine.config, Decimal("1")), "")
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            self.assertEqual(engine.entry_quality_hold_reason("SQQQ", snap(), engine.config), "Hold (trend hold warming)")


class TrendHoldExitTests(unittest.TestCase):
    POSITION = {"symbol": "SQQQ", "qty": "1", "avg_entry_price": "40", "current_price": "44"}

    def decide(self, engine: TraderEngine, price: str, vwap: str, has_stop: bool = True) -> str:
        with patch.object(engine, "snapshot", return_value=snap(vwap=vwap)):
            reason, _ = engine.local_protection_exit_decision(
                "SQQQ", engine.config, dict(self.POSITION, current_price=price), Decimal(price), False, has_stop
            )
        return reason

    def test_a_big_winner_above_vwap_rides_past_take_profit_and_the_tight_trail(self) -> None:
        engine = engine_with(inverse_trend_hold=True, take_profit_percent="2.5", profit_trail_start_percent="3",
                             profit_trail_drop_percent="1")
        self.assertEqual(self.decide(engine, "44", "1.5", has_stop=False), "")  # +10%: no take-profit
        self.assertEqual(self.decide(engine, "43.3", "0.4", has_stop=False), "")  # 1.6% off the peak: the 1% trail is not used
        self.assertEqual(self.decide(engine, "43.3", "0", has_stop=False), "")  # at VWAP, not under it

    def test_locked_profit_is_taken_when_the_fund_gives_back_the_trail(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        self.assertEqual(self.decide(engine, "44", "1.5", has_stop=False), "")  # peak 44 locks the stop at 43.10
        reason = self.decide(engine, "43.05", "0.4", has_stop=False)
        self.assertEqual(reason, "local trailing stop $43.10 (gain 7.62%)")
        self.assertEqual(self.decide(engine, "43.05", "0.4", has_stop=True), "")  # the broker stop handles it

    def test_the_same_winner_is_sold_by_the_profile_rules_without_trend_hold(self) -> None:
        engine = engine_with(take_profit_percent="2.5")
        self.assertIn("local take-profit", self.decide(engine, "44", "1.5"))

    def test_hold_ends_once_the_fund_is_under_vwap_even_beside_a_live_stop(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        reason = self.decide(engine, "43", "-0.31", has_stop=True)
        self.assertEqual(reason, "trend hold ended: -0.31% under VWAP (gain 7.50%)")
        self.assertTrue(engine.is_trend_hold_exit_reason(reason))
        self.assertEqual(engine.exit_reason_label("sell", "Strategy Exit", reason), "Trend Hold Ended")

    def test_stop_stays_wide_until_the_lock_then_trails_and_never_drops_under_entry(self) -> None:
        engine = engine_with(inverse_trend_hold=True, breakeven_at_percent="1", profit_trail_start_percent="3",
                             profit_trail_drop_percent="1")
        stop = lambda price: engine.position_stop_price("SQQQ", Decimal("40"), Decimal(price), engine.config)  # noqa: E731
        self.assertEqual(stop("40.40"), Decimal("38.80"))  # +1%: the profile's breakeven does not apply
        self.assertEqual(stop("41.10"), Decimal("38.80"))  # +2.75%: still the wide stop
        self.assertEqual(stop("41.20"), Decimal("40.30"))  # +3%: locked, 2% under the peak in 0.25% steps
        self.assertEqual(stop("44.00"), Decimal("43.10"))  # trails the peak
        self.assertEqual(stop("42.00"), Decimal("43.10"))  # and never comes back down
        self.assertEqual(engine.position_take_profit_price("SQQQ", Decimal("40"), engine.config), Decimal("0"))

    def test_a_trail_wider_than_the_gain_still_locks_the_entry_price(self) -> None:
        engine = engine_with(inverse_trend_hold=True, inverse_trend_trail_percent="5")
        self.assertEqual(engine.position_stop_price("SQQQ", Decimal("40"), Decimal("41.20"), engine.config), Decimal("40.00"))

    def test_lock_can_be_switched_off_for_a_stop_that_never_moves(self) -> None:
        engine = engine_with(inverse_trend_hold=True, inverse_trend_lock_at_percent="0")
        self.assertEqual(engine.position_stop_price("SQQQ", Decimal("40"), Decimal("44"), engine.config), Decimal("38.80"))

    def test_other_symbols_keep_their_own_stop_and_target(self) -> None:
        engine = engine_with(inverse_trend_hold=True, breakeven_at_percent="1", profit_trail_start_percent="3",
                             profit_trail_drop_percent="1")
        # An ordinary stock on the same profile still ratchets and keeps its target.
        self.assertGreater(engine.position_stop_price("AAA", Decimal("40"), Decimal("44"), engine.config), Decimal("40"))
        self.assertGreater(engine.position_take_profit_price("AAA", Decimal("40"), engine.config), Decimal("40"))

    def test_hard_stop_sells_locally_when_no_broker_stop_is_working(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        self.assertIn("local stop-loss 3%", self.decide(engine, "38.7", "0.5", has_stop=False))
        self.assertEqual(self.decide(engine, "38.7", "0.5", has_stop=True), "")  # the broker stop handles it

    def test_restart_recovers_the_locked_peak_from_the_live_stop(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        live_stop = {"symbol": "SQQQ", "side": "sell", "type": "stop", "qty": "1", "stop_price": "43.10",
                     "client_order_id": "apt-protect-sl-sqqq-1"}
        engine.seed_peak_from_live_stops("SQQQ", Decimal("40"), [live_stop], engine.config)
        # Price is now lower than the old peak; the stop must not fall back to the wide level.
        self.assertGreaterEqual(engine.position_stop_price("SQQQ", Decimal("40"), Decimal("43.5"), engine.config), Decimal("43.00"))


class SqqqClient(FakeTradingClient):
    """One long SQQQ position whose shares are all held by the app's own stop."""

    qty = "0.5"

    def get_all_positions(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "SQQQ",
                "qty": self.qty,
                "qty_available": "0" if self.open_orders else self.qty,
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
        client = SqqqClient(is_open=True, price="41", entry="40")
        engine = live_engine(client, [40 + step * 0.025 for step in range(41)])
        refresh(engine)
        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(str(client.submitted[0].stop_price), "38.8")

    def test_held_above_vwap_nothing_is_sent(self) -> None:
        client = SqqqClient(is_open=True, price="41", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [40 + step * 0.025 for step in range(41)])
        refresh(engine)
        self.assertEqual(client.cancelled, [])
        self.assertEqual(client.submitted, [])

    def test_past_the_lock_the_broker_stop_is_raised_and_nothing_is_sold(self) -> None:
        client = SqqqClient(is_open=True, price="44", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [40 + step * 0.1 for step in range(41)])
        refresh(engine)  # the 38.80 stop is stale: cancelled for a replacement
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(client.submitted, [])
        refresh(engine)  # replacement at 2% under the 44 peak
        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(str(client.submitted[0].stop_price), "43.1")

    def test_under_vwap_cancels_its_stop_and_sells_every_share_in_one_pass(self) -> None:
        # qty_available is 0 because the stop holds the shares; the sell must still be for all 0.5.
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        refresh(engine)
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "0.5")

    def test_sell_is_sized_from_a_fresh_position_when_the_stop_partly_filled(self) -> None:
        # The stop sold 0.2 between the order read and the cancel; only 0.3 is left to sell.
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        client.get_open_position = lambda symbol: {"symbol": symbol, "qty": "0.3", "qty_available": "0.3"}  # type: ignore[attr-defined]
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        refresh(engine)
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "0.3")

    def test_nothing_is_sold_when_the_stop_filled_completely_first(self) -> None:
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        client.get_open_position = lambda symbol: {"symbol": symbol, "qty": "0", "qty_available": "0"}  # type: ignore[attr-defined]
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        refresh(engine)
        self.assertEqual(client.submitted, [])

    def test_a_refused_cancel_sells_nothing(self) -> None:
        client = SqqqClient(is_open=True, price="42", entry="40", orders=[dict(STOP)])
        engine = live_engine(client, [44.0] * 30 + [43.5, 43.0, 42.5, 42.0])
        with patch.object(engine, "cancel_open_order", return_value=False):
            refresh(engine)
        self.assertEqual(client.submitted, [])

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


class DailyBuyCountTests(unittest.TestCase):
    def test_a_buy_that_scrolled_out_of_the_order_window_still_counts_today(self) -> None:
        from datetime import datetime
        from alpaca_desktop.engine import MARKET_TIMEZONE

        engine = engine_with()
        now = datetime.now(MARKET_TIMEZONE).isoformat()
        buy = {"id": "b1", "symbol": "SQQQ", "side": "buy", "filled_qty": "1", "filled_at": now}
        engine.sync_entries_today_from_orders([buy, dict(buy, id="b2")])
        self.assertEqual(engine.entries_today_by_symbol, {"SQQQ": 2})
        engine.sync_entries_today_from_orders([dict(buy, id="b2")])  # b1 no longer in the newest 100
        self.assertEqual(engine.entries_today_by_symbol, {"SQQQ": 2})
        engine.entries_today_date = None  # a new trading day starts from the broker's orders again
        engine.sync_entries_today_from_orders([])
        self.assertEqual(engine.entries_today_by_symbol, {})


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
