"""Movers mode (entry_mode "movers"): the weighted score, its three yes/no checks, the stop, and the data worker."""

from __future__ import annotations

import json
import tempfile
import time as clock_module
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import inplay as inplay_logic  # noqa: E402
from alpaca_desktop import movers as M  # noqa: E402
from alpaca_desktop.engine import AppConfig, TraderEngine  # noqa: E402

from .test_inplay_mode import NOON, Broker  # noqa: E402

D = Decimal
TODAY = "2026-11-12"
OPEN_UTC = datetime(2026, 11, 12, 14, 30, tzinfo=timezone.utc)  # 09:30 ET


def readings(**values: Any) -> M.Readings:
    base = dict(relative_volume=D("1"), half_hour_move=D("0"), five_min_move=D("0"), vwap_distance=D("0.1"),
                session_change=D("0.1"), daily_range=D("2"), rsi=D("50"))
    base.update({key: (D(str(value)) if value is not None else None) for key, value in values.items()})
    return M.Readings(**base)


class ScoreTests(unittest.TestCase):
    def test_volume_points_are_on_a_log_scale(self) -> None:
        self.assertEqual(M.volume_fraction(D("1"), D("5")), D("0"))
        self.assertEqual(M.volume_fraction(D("5"), D("5")), D("1"))
        self.assertEqual(M.volume_fraction(D("50"), D("5")), D("1"))
        self.assertAlmostEqual(float(M.volume_fraction(D("2.236068"), D("5"))), 0.5, places=4)
        self.assertEqual(M.volume_fraction(None, D("5")), D("0"))

    def test_every_reading_at_full_strength_is_100(self) -> None:
        full = readings(relative_volume=5, half_hour_move=2, five_min_move=0.7, vwap_distance=3, session_change=5, daily_range=8)
        self.assertEqual(M.score(full, M.Weights()).total, D("100.0"))

    def test_heavy_volume_carries_a_stock_whatever_its_rsi(self) -> None:
        hot = readings(relative_volume=6, half_hour_move=1, five_min_move=0.3, vwap_distance=1.5, rsi=97)
        calm = readings(relative_volume=6, half_hour_move=1, five_min_move=0.3, vwap_distance=1.5, rsi=55)
        self.assertEqual(M.score(hot, M.Weights()).total, M.score(calm, M.Weights()).total)
        self.assertGreaterEqual(M.score(hot, M.Weights()).total, D("60"))

    def test_being_far_above_vwap_or_far_up_on_the_day_is_never_penalised(self) -> None:
        normal = readings(relative_volume=4, vwap_distance=3, session_change=5)
        stretched = readings(relative_volume=4, vwap_distance=12, session_change=40)
        self.assertEqual(M.score(stretched, M.Weights()).total, M.score(normal, M.Weights()).total)

    def test_without_volume_the_score_cannot_reach_the_default_bar(self) -> None:
        strong_but_quiet = readings(relative_volume=1, half_hour_move=5, five_min_move=2, vwap_distance=6, session_change=9, daily_range=12)
        self.assertEqual(M.score(strong_but_quiet, M.Weights()).total, D("55.0"))

    def test_rsi_is_a_weight_that_can_only_add(self) -> None:
        weights = M.Weights(rsi=D("10"))
        self.assertEqual(M.score(readings(rsi=90), weights).total - M.score(readings(rsi=50), weights).total, D("10.0"))
        self.assertEqual(M.score(readings(rsi=20), weights).total, M.score(readings(rsi=50), weights).total)

    def test_the_three_direction_checks(self) -> None:
        self.assertEqual(M.direction_hold_reason(readings()), "")
        self.assertIn("down 0.50% on the session", M.direction_hold_reason(readings(session_change=-0.5)))
        self.assertIn("under VWAP", M.direction_hold_reason(readings(vwap_distance=-0.2)))
        self.assertIn("fell 0.30% in the last 5 minutes", M.direction_hold_reason(readings(five_min_move=-0.3)))
        self.assertIn("warming up", M.direction_hold_reason(readings(five_min_move=None)))

    def test_stop_is_sized_to_the_daily_range_within_bounds(self) -> None:
        args = (D("0.35"), D("1.25"), D("6"), D("6"))
        self.assertEqual(M.stop_distance_percent(D("8"), *args), D("2.80"))
        self.assertEqual(M.stop_distance_percent(D("2"), *args), D("1.25"))
        self.assertEqual(M.stop_distance_percent(D("30"), *args), D("6"))
        self.assertEqual(M.stop_distance_percent(None, *args), D("6"))  # unknown range: the widest stop


class VolumeTests(unittest.TestCase):
    def test_slots_and_running_totals(self) -> None:
        self.assertEqual((M.slot_of(570), M.slot_of(574), M.slot_of(575), M.slot_of(955), M.slot_of(960), M.slot_of(565)), (0, 0, 1, 77, None, None))
        total = M.cumulative_volume([(570, D("100")), (580, D("50")), (955, D("10")), (1000, D("999"))])
        self.assertEqual((total[0], total[1], total[2], total[76], total[77]), (100.0, 100.0, 150.0, 150.0, 160.0))

    def test_profile_needs_enough_sessions_that_traded(self) -> None:
        day = M.cumulative_volume([(570, D("100")), (600, D("100"))])
        empty = [0.0] * M.SLOTS
        self.assertIsNone(M.average_profile([day] * 9 + [empty] * 5))
        profile = M.average_profile([day] * 10)
        self.assertEqual((profile[0], profile[6]), (100.0, 200.0))

    def test_delayed_data_decides_the_newest_readable_slot(self) -> None:
        self.assertIsNone(M.last_complete_slot(20, 16))        # 09:50: nothing readable yet
        self.assertEqual(M.last_complete_slot(21, 16), 0)      # 09:51: the 09:30 bar
        self.assertEqual(M.last_complete_slot(26, 16), 1)      # 09:56: through the 09:35 bar
        self.assertEqual(M.last_complete_slot(1000, 16), 77)

    def test_relative_volume_is_today_against_usual_by_this_time(self) -> None:
        profile = M.average_profile([M.cumulative_volume([(570, D("100")), (600, D("100"))])] * 10)
        today = M.cumulative_volume([(570, D("450")), (600, D("50"))])
        self.assertEqual(M.relative_volume(today, profile, 0), D("4.5"))
        self.assertEqual(M.relative_volume(today, profile, 6), D("2.5"))
        self.assertIsNone(M.relative_volume(today, None, 0))
        self.assertIsNone(M.relative_volume(today, profile, None))


def stamp(minute: int) -> str:
    return (OPEN_UTC + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")


def movers_engine(broker: Any = None, *, climb: str = "0.01", bars: int = 120, **config: Any) -> TraderEngine:
    """An account in movers mode with HOT climbing steadily from $10 since the open (RSI pinned at 100)."""
    engine = TraderEngine("movers")
    engine.config = AppConfig(entry_mode="movers", use_top_volume_symbols=False, symbols=["HOT"], dry_run=False,
                              min_entry_score="60", take_profit_percent="2.5", stop_loss_percent="1.25",
                              max_trade_percent="5", max_open_positions=20, **config)
    engine.connected = True
    engine.trading_enabled = True
    engine.trading_client = broker  # type: ignore[assignment]
    engine.data_client = SimpleNamespace(get_stock_bars=lambda request: SimpleNamespace(data={}))  # type: ignore[assignment]
    for minute in range(bars):
        price = D("10") + D(climb) * minute
        engine.strategy_state.add_bar("HOT", price, stamp(minute), 1000, price, price - D("0.01"))
    engine.mover_session = TODAY
    engine.mover_profiles = {"HOT": [1000.0] * M.SLOTS}
    engine.mover_stats = {"HOT": inplay_logic.DailyStats(atr_percent=D("8"), dollar_volume=D("90000000"))}
    engine.mover_volume = {"HOT": D("5")}
    engine.mover_volume_at = clock_module.monotonic()
    return engine


def hold(engine: TraderEngine, symbol: str = "HOT") -> str:
    with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
        return engine.movers_entry_hold_reason(symbol, engine.snapshot(symbol), engine.config)


class EntryTests(unittest.TestCase):
    def test_a_stock_climbing_on_heavy_volume_is_a_buy_at_rsi_100(self) -> None:
        engine = movers_engine()
        self.assertEqual(engine.snapshot("HOT").rsi, D("100"))
        self.assertEqual(hold(engine), "")
        self.assertGreaterEqual(engine.strategy_state.entry_score["HOT"], D("60"))

    def test_the_momentum_rules_would_have_refused_the_same_stock_for_rsi(self) -> None:
        engine = movers_engine()
        engine.config = engine.config.model_copy(update={"entry_mode": "momentum"})
        self.assertIn("RSI 100.0 above", engine.entry_quality_hold_reason("HOT", engine.snapshot("HOT"), engine.config))

    def test_below_the_bar_the_reason_shows_the_score_and_what_earned_it(self) -> None:
        engine = movers_engine()
        engine.mover_volume = {"HOT": D("1.2")}
        reason = hold(engine)
        self.assertRegex(reason, r"^Hold \(score \d+ of 60: volume 1\.2x \+\d+")
        self.assertNotIn("RSI", reason)

    def test_direction_checks_hold_a_stock_that_is_not_going_up(self) -> None:
        falling = movers_engine(climb="-0.01")
        self.assertIn("down", hold(falling))
        dipping = movers_engine()
        for minute in range(120, 126):  # six bars straight down, still up on the day
            dipping.strategy_state.add_bar("HOT", D("11.19") - D("0.03") * (minute - 119), stamp(minute), 1000)
        reason = hold(dipping)
        self.assertTrue("fell" in reason or "under VWAP" in reason, reason)

    def test_missing_volume_history_and_thin_stocks_wait(self) -> None:
        engine = movers_engine()
        engine.mover_profiles = {}
        self.assertIn("volume history loading", hold(engine))
        engine.mover_profiles = {"HOT": None}
        self.assertIn("not enough volume history", hold(engine))
        engine = movers_engine()
        engine.mover_stats = {"HOT": inplay_logic.DailyStats(atr_percent=D("8"), dollar_volume=D("3000000"))}
        self.assertIn("trades $3M a day, under $20M", hold(engine))

    def test_a_volume_reading_the_worker_could_not_refresh_earns_no_points(self) -> None:
        engine = movers_engine()
        self.assertEqual(hold(engine), "")
        engine.mover_volume_at = clock_module.monotonic() - 11 * 60
        self.assertIn("volume reading not in yet", hold(engine))

    def test_no_volume_reading_waits_and_a_stock_is_bought_once_a_day(self) -> None:
        engine = movers_engine()
        engine.mover_volume = {}
        self.assertIn("volume reading not in yet", hold(engine))
        engine = movers_engine()
        engine.entries_today_by_symbol = {"HOT": 1}
        self.assertIn("bought 1x today", hold(engine))
        engine.config = engine.config.model_copy(update={"max_entries_per_symbol_per_day": 2})
        self.assertEqual(hold(engine), "")

    def test_candidate_carries_the_weighted_score(self) -> None:
        engine = movers_engine()
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            candidate = engine.movers_entry_candidate("HOT", 3, engine.snapshot("HOT"), engine.config)
        self.assertEqual(candidate["symbol"], "HOT")
        self.assertEqual(candidate["score"], engine.strategy_state.entry_score["HOT"])
        self.assertIn("Candidate movers score", engine.strategy_state.last_action["HOT"])

    def test_price_change_looks_back_by_the_clock_not_by_bar_count(self) -> None:
        engine = movers_engine()
        price = engine.snapshot("HOT").price  # 11.19 at 11:29
        self.assertAlmostEqual(float(engine.mover_price_change("HOT", price, 30)), (11.19 / 10.89 - 1) * 100, places=3)
        self.assertAlmostEqual(float(engine.mover_price_change("HOT", price, 5)), (11.19 / 11.14 - 1) * 100, places=3)
        young = movers_engine(bars=3)
        self.assertAlmostEqual(float(young.mover_price_change("HOT", D("10.02"), 30)), 0.2, places=3)  # since the first bar


class StopTests(unittest.TestCase):
    def test_stop_is_a_fraction_of_the_daily_range_and_follows_the_peak(self) -> None:
        engine = movers_engine()
        config = engine.config
        self.assertEqual(engine.mover_stop_distance("HOT", config), D("2.80"))
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("100"), config), D("97.20"))
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("102"), config), D("97.20"))  # not up 2.8% yet
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("106"), config), D("103.00"))  # 106 less 2.8%, in 0.25 steps
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("101"), config), D("103.00"))  # never back down
        self.assertEqual(engine.position_stop_percent("HOT", config), D("2.80"))

    def test_unknown_daily_range_uses_the_widest_stop(self) -> None:
        engine = movers_engine()
        engine.mover_stats = {}
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("100"), engine.config), D("94.00"))

    def test_no_take_profit_and_a_live_stop_is_never_loosened(self) -> None:
        engine = movers_engine()
        self.assertEqual(engine.position_take_profit_price("HOT", D("100"), engine.config), D("0"))
        held = {"qty": "10", "avg_entry_price": "100", "current_price": "104"}
        self.assertEqual(engine.local_protection_exit_decision("HOT", engine.config, held, D("104"), False, True), ("", ""))
        live = {"id": "s1", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "10", "stop_price": "97.20",
                "client_order_id": "apt-protect-sl-hot-1"}
        with patch.object(engine, "cancel_open_order", return_value=True) as cancel:
            self.assertFalse(engine.cancel_stale_protective_order(live, D("10"), D("0"), D("94.00"), D("100")))
            cancel.assert_not_called()
            self.assertTrue(engine.cancel_stale_protective_order(live, D("10"), D("0"), D("103.00"), D("100")))  # raising is fine

    def test_daily_range_loading_late_never_lifts_the_stop_over_the_live_one(self) -> None:
        # A stop at 101 is live on a position bought at 100 and the stock's daily range is not on
        # record yet. When it loads (a 1.4% stop distance) the stop must not jump above the price.
        engine = movers_engine()
        engine.mover_stats = {}
        live = [{"id": "s1", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "10", "stop_price": "101.00",
                 "client_order_id": "apt-protect-sl-hot-1"}]
        engine.seed_peak_from_live_stops("HOT", D("100"), live, engine.config)
        engine.mover_stats = {"HOT": inplay_logic.DailyStats(atr_percent=D("4"), dollar_volume=D("90000000"))}
        engine.seed_peak_from_live_stops("HOT", D("100"), live, engine.config)
        stop = engine.position_stop_price("HOT", D("100"), D("101.50"), engine.config)
        self.assertLessEqual(stop, D("101.00"))
        with patch.object(engine, "cancel_open_order", return_value=True) as cancel:
            self.assertFalse(engine.cancel_stale_protective_order(live[0], D("10"), D("0"), stop, D("100")))
            cancel.assert_not_called()

    def test_restart_reads_the_peak_back_from_a_live_trailed_stop(self) -> None:
        engine = movers_engine()
        live = [{"id": "s1", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "10", "stop_price": "103.00",
                 "client_order_id": "apt-protect-sl-hot-1"}]
        engine.seed_peak_from_live_stops("HOT", D("100"), live, engine.config)
        # The peak is read back conservatively, so the computed stop is at or under the live one
        # (which is then kept), and well above the first stop at 97.20.
        stop = engine.position_stop_price("HOT", D("100"), D("101"), engine.config)
        self.assertLessEqual(stop, D("103.00"))
        self.assertGreaterEqual(stop, D("101.00"))


def refresh(engine: TraderEngine) -> None:
    with (
        patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
        patch.object(engine, "record_day_tape_scan"),
        patch.object(engine, "record_day_tape_bars"),
        patch.object(engine, "current_trade_price", side_effect=lambda symbol, fallback: fallback),
        patch.object(engine, "asset_tradeability_hold_reason", return_value=""),
        patch.object(engine, "start_mover_worker"),
    ):
        engine.refresh(run_strategy=True, shared_bars={symbol: [] for symbol in ("HOT", "SPY", "QQQ")})


class RefreshTests(unittest.TestCase):
    def test_a_mover_is_bought_and_the_order_says_why(self) -> None:
        broker = Broker()
        engine = movers_engine(broker, bars=150)  # bars up to 11:59 ET; the broker clock says 12:00
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in broker.submitted], [("HOT", "buy")])
        reason = engine.order_intents[-1]["reason"]
        self.assertIn("movers: volume 5.0x +45", reason)

    def test_a_re_entry_floor_from_the_old_score_does_not_block(self) -> None:
        broker = Broker()
        engine = movers_engine(broker, bars=150)
        engine.reentry_score_floors["HOT"] = D("99")
        with patch.object(engine, "sync_loss_reentry_floors_from_closed_orders"):
            refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in broker.submitted], [("HOT", "buy")])

    def test_held_mover_gets_its_range_sized_stop(self) -> None:
        held = {"symbol": "HOT", "qty": "400", "qty_available": "400", "avg_entry_price": "11.00", "current_price": "11.40",
                "market_value": "4560", "side": "long"}
        broker = Broker(positions=[held])
        engine = movers_engine(broker, bars=150)
        refresh(engine)
        self.assertEqual([(order.side.value, order.type.value, float(order.stop_price)) for order in broker.submitted],
                         [("sell", "stop", 11.05)])  # 11.40 peak less 2.8% is 11.08, floored to quarter-percent steps above 11.00

    def test_momentum_accounts_never_touch_the_movers_code(self) -> None:
        engine = movers_engine()
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"])
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("100"), engine.config), D("98.75"))
        with patch.object(engine, "movers_entry_hold_reason") as movers_hold, patch.object(engine, "movers_pass") as movers_pass:
            engine.entry_quality_hold_reason("HOT", engine.snapshot("HOT"), engine.config)
            engine.trading_client = Broker()  # type: ignore[assignment]
            engine.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"], dry_run=False)
            refresh(engine)
        movers_hold.assert_not_called()
        movers_pass.assert_not_called()


class FakeCalendar:
    """Weekdays are sessions; 2026-11-10 closes at 13:00 (a half day)."""

    def get_calendar(self, request: Any) -> list[Any]:
        from datetime import time as day_time

        days, day = [], request.start
        while day <= request.end:
            if day.weekday() < 5:
                days.append(SimpleNamespace(date=day, close=day_time(13, 0) if day == date(2026, 11, 10) else day_time(16, 0)))
            day += timedelta(days=1)
        return days


class FakeSip:
    """HOT trades 1,000 shares in each 5-minute bar on past sessions and 5,000 today; THIN has no history."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def get_stock_bars(self, request: Any) -> Any:
        self.requests.append(request)
        symbols = request.symbol_or_symbols
        start = request.start if request.start.tzinfo else request.start.replace(tzinfo=timezone.utc)
        end = request.end if request.end.tzinfo else request.end.replace(tzinfo=timezone.utc)
        if str(request.timeframe.unit.value).lower().startswith("day"):
            return SimpleNamespace(data={s: [SimpleNamespace(timestamp=datetime(2026, 10, 1, 5, tzinfo=timezone.utc) + timedelta(days=i),
                                                             open=10, high=10.5, low=9.9, close=10, volume=5_000_000) for i in range(30)]
                                         for s in symbols if s == "HOT"})
        today = start.date() == date(2026, 11, 12)
        bars = {}
        if "HOT" in symbols:
            count = int((end - start).total_seconds() // 300)
            bars["HOT"] = [SimpleNamespace(timestamp=start + timedelta(minutes=5 * i), volume=5000 if today else 1000) for i in range(count)]
        return SimpleNamespace(data=bars)


class WorkerTests(unittest.TestCase):
    def run_worker(self, engine: TraderEngine, data: FakeSip, now_et: datetime) -> None:
        real_datetime = datetime

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
                return now_et.astimezone(tz) if tz else now_et

        with (
            patch("alpaca_desktop.engine.StockHistoricalDataClient", return_value=data),
            patch("alpaca_desktop.engine.TradingClient", return_value=FakeCalendar()),
            patch("alpaca_desktop.engine.datetime", FrozenDatetime),
        ):
            engine.mover_work(date(2026, 11, 12), ["HOT", "THIN"], "key", "secret")
        del real_datetime

    def test_worker_builds_profiles_and_todays_relative_volume_from_delayed_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.object(TraderEngine, "MOVERS_PATH", Path(folder) / "movers.json"):
            engine = TraderEngine("movers")
            engine.config = AppConfig(entry_mode="movers")
            engine.mover_session = TODAY
            data = FakeSip()
            now_et = datetime(2026, 11, 12, 15, 26, tzinfo=timezone.utc)  # 10:26 ET: data readable through 10:10
            self.run_worker(engine, data, now_et)
            self.assertEqual(engine.mover_volume_slot, 7)  # the 10:05 bar
            self.assertEqual(engine.mover_volume["HOT"], D("5"))
            self.assertIsNone(engine.mover_profiles["THIN"])
            self.assertNotIn("THIN", engine.mover_volume)
            self.assertEqual(engine.mover_stats["HOT"].atr_percent, D("6"))
            self.assertTrue(all(str(request.feed.value).lower() == "sip" for request in data.requests))
            asked = {(request.start if request.start.tzinfo else request.start.replace(tzinfo=timezone.utc)).date() for request in data.requests
                     if not str(request.timeframe.unit.value).lower().startswith("day")}
            self.assertNotIn(date(2026, 11, 10), asked)  # the half day is left out of the usual-volume profile
            self.assertEqual(len(asked), 15)             # 14 full sessions plus today
            todays = [request for request in data.requests if (request.start if request.start.tzinfo else request.start.replace(tzinfo=timezone.utc)).date() == date(2026, 11, 12)
                      and not str(request.timeframe.unit.value).lower().startswith("day")]
            end = todays[-1].end if todays[-1].end.tzinfo else todays[-1].end.replace(tzinfo=timezone.utc)
            self.assertLessEqual(end, now_et - timedelta(minutes=15))  # never asks for the last 15 minutes
            # A restart the same day reads the profiles back and does not download history again.
            restarted = TraderEngine("movers")
            restarted.config = AppConfig(entry_mode="movers")
            restarted.account_id = engine.account_id
            restarted.mover_session = TODAY
            restarted.load_mover_data(date(2026, 11, 12))
            self.assertEqual(restarted.mover_stats["HOT"].atr_percent, D("6"))
            self.assertEqual(restarted.mover_profiles["HOT"][7], 8000.0)
            self.assertIn("THIN", restarted.mover_profiles)
            again = FakeSip()
            self.run_worker(restarted, again, now_et)
            self.assertEqual(len(again.requests), 1)  # only today's bars
            saved = json.loads((Path(folder) / "movers.json").read_text())
            self.assertEqual(saved[engine.account_id]["session"], TODAY)

    def test_before_the_first_readable_bar_nothing_is_fetched_for_today(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.object(TraderEngine, "MOVERS_PATH", Path(folder) / "movers.json"):
            engine = TraderEngine("movers")
            engine.config = AppConfig(entry_mode="movers")
            engine.mover_session = TODAY
            engine.mover_profiles = {"HOT": [1000.0] * M.SLOTS, "THIN": None}
            data = FakeSip()
            self.run_worker(engine, data, datetime(2026, 11, 12, 14, 45, tzinfo=timezone.utc))  # 09:45 ET
            self.assertEqual(data.requests, [])
            self.assertEqual(engine.mover_volume, {})
            self.assertGreater(engine.mover_volume_at, 0)

    def test_failed_loads_back_off(self) -> None:
        engine = TraderEngine("movers")
        engine.config = AppConfig(entry_mode="movers")
        engine.mover_session = TODAY
        with patch("alpaca_desktop.engine.StockHistoricalDataClient", side_effect=RuntimeError("down")):
            engine.mover_work(date(2026, 11, 12), ["HOT"], "k", "s")
            self.assertAlmostEqual(engine.mover_retry_at - clock_module.monotonic(), 60, delta=5)
            engine.mover_work(date(2026, 11, 12), ["HOT"], "k", "s")
            self.assertAlmostEqual(engine.mover_retry_at - clock_module.monotonic(), 120, delta=5)

    def test_pass_resets_on_a_new_session_and_asks_for_missing_symbols(self) -> None:
        engine = movers_engine()
        engine.mover_session = "2026-11-11"
        clock = SimpleNamespace(is_open=True, timestamp=NOON, next_close=NOON.replace(hour=21))
        with tempfile.TemporaryDirectory() as folder, patch.object(TraderEngine, "MOVERS_PATH", Path(folder) / "movers.json"), \
             patch.object(engine, "start_mover_worker") as start:
            status = engine.movers_pass(clock, True)
        self.assertEqual(engine.mover_session, TODAY)
        self.assertEqual(engine.mover_volume, {})
        start.assert_called_once()
        self.assertIn("HOT", start.call_args.args[1])
        self.assertIn("loading volume data", status)


class ConfigTests(unittest.TestCase):
    def test_defaults_and_bounds(self) -> None:
        config = AppConfig(entry_mode="movers")
        self.assertEqual((config.mover_weight_volume, config.mover_weight_rsi, config.mover_stop_atr_fraction), (D("45"), D("0"), D("0.35")))
        clamped = AppConfig(mover_weight_volume="500", mover_stop_min_percent="3", mover_stop_max_percent="1", mover_volume_full_at="1")
        self.assertEqual((clamped.mover_weight_volume, clamped.mover_stop_max_percent, clamped.mover_volume_full_at), (D("100"), D("3"), D("1.5")))


if __name__ == "__main__":
    unittest.main()
