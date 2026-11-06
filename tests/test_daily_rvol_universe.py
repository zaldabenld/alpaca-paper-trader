from __future__ import annotations

import os
import stat
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop import universe as rvol
from alpaca_desktop.engine import MARKET_TIMEZONE, AppConfig, TraderManager

INVERSE = ["SQQQ", "SPXU", "SDS", "SH", "TZA"]
SESSION = date(2026, 11, 5)  # a Thursday


def et(hour: int, minute: int, day: date = SESSION) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MARKET_TIMEZONE)


def daily_bar(day: date, volume: float) -> SimpleNamespace:
    # Alpaca stamps daily bars at midnight US/Eastern (04:00 or 05:00 UTC).
    return SimpleNamespace(timestamp=datetime(day.year, day.month, day.day, tzinfo=MARKET_TIMEZONE).astimezone(timezone.utc), volume=volume)


def prior_sessions(count: int, end: date = SESSION) -> list[date]:
    days: list[date] = []
    current = end
    while len(days) < count:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            days.append(current)
    return sorted(days)


class FakeDataClient:
    """Daily bars: every symbol averages `avg[symbol]` over 20 sessions. Snapshots: `today[symbol]`."""

    def __init__(self, avg: dict[str, float], today: dict[str, float]) -> None:
        self.avg = avg
        self.today = today
        self.bar_requests: list[list[str]] = []
        self.bar_starts: list[Any] = []
        self.snapshot_requests: list[list[str]] = []

    def get_stock_bars(self, request: Any) -> Any:
        symbols = list(request.symbol_or_symbols)
        self.bar_requests.append(symbols)
        self.bar_starts.append(request.start)
        days = prior_sessions(20)
        return SimpleNamespace(
            data={symbol: [daily_bar(day, self.avg[symbol]) for day in days] for symbol in symbols if symbol in self.avg}
        )

    def get_stock_snapshot(self, request: Any) -> dict[str, Any]:
        symbols = list(request.symbol_or_symbols)
        self.snapshot_requests.append(symbols)
        return {
            symbol: SimpleNamespace(daily_bar=daily_bar(SESSION, self.today[symbol]))
            for symbol in symbols
            if symbol in self.today
        }


def top_rows(today: dict[str, float], bar_day: date = SESSION) -> list[dict[str, Any]]:
    return [
        {"symbol": symbol, "feed_daily_volume_raw": volume, "feed_daily_bar_date": bar_day.isoformat()}
        for symbol, volume in today.items()
    ]


class RankingTests(unittest.TestCase):
    def test_ranks_by_ratio_to_normal_volume_not_raw_volume(self) -> None:
        today = {"BIG": (5_000_000.0, SESSION), "SPIKE": (50_000.0, SESSION), "STALE": (9e9, SESSION - timedelta(days=1))}
        adv = {"BIG": (2_500_000.0, 20), "SPIKE": (5_000.0, 20), "STALE": (1.0, 20)}
        ranked = rvol.rank_by_rvol(today, adv, SESSION)
        self.assertEqual([row["symbol"] for row in ranked], ["SPIKE", "BIG"])  # 10x beats 2x; no trade today is skipped
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertAlmostEqual(ranked[0]["rvol"], 10.0)

    def test_average_uses_prior_twenty_sessions_and_needs_five(self) -> None:
        days = prior_sessions(25)
        bars = {
            "OLD": [daily_bar(day, 1_000_000 if index < 5 else 100) for index, day in enumerate(days)]
            + [daily_bar(SESSION, 9e9)],  # today's bar never counts
            "NEW": [daily_bar(day, 500) for day in days[-4:]],
        }
        averages = rvol.average_daily_volumes(bars, SESSION, MARKET_TIMEZONE)
        self.assertEqual(averages["OLD"], (100.0, 20))  # the five oldest sessions fall outside the window
        self.assertIsNone(averages["NEW"])

    def test_pick_waits_for_fifteen_minutes_after_the_open_on_open_days(self) -> None:
        self.assertFalse(rvol.pick_due(None, et(9, 44), True))
        self.assertTrue(rvol.pick_due(None, et(9, 45), True))
        self.assertTrue(rvol.pick_due(None, et(13, 0), True))  # late start picks on the first refresh
        self.assertFalse(rvol.pick_due(None, et(10, 0), False))  # holiday or weekend: clock closed
        today = rvol.DailyUniverse(session_date=SESSION.isoformat(), feed="iex", symbols=["A"])
        self.assertFalse(rvol.pick_due(today, et(10, 0), True))
        yesterday = rvol.DailyUniverse(session_date="2026-11-04", feed="iex", symbols=["A"])
        self.assertTrue(rvol.pick_due(yesterday, et(10, 0), True))

    def test_recheck_adds_newcomers_removes_nothing_and_caps(self) -> None:
        ranked = [{"symbol": f"S{i:02d}", "rvol": 100 - i, "today_volume": 1, "avg_volume": 1, "sessions": 20, "rank": i + 1} for i in range(30)]
        universe = rvol.new_universe(ranked, et(9, 45), "iex")
        self.assertEqual(universe.symbols, [f"S{i:02d}" for i in range(25)])
        self.assertFalse(rvol.recheck_due(universe, et(10, 14), True))
        self.assertTrue(rvol.recheck_due(universe, et(10, 15), True))

        # Ten new names jump to the top; S20-S24 drop out of the current top 25 but stay on the list.
        reranked = [{"symbol": f"N{i}", "rvol": 500 - i, "today_volume": 1, "avg_volume": 1, "sessions": 20, "rank": i + 1} for i in range(10)]
        reranked += [dict(row, rank=row["rank"] + 10) for row in ranked]
        added = rvol.merge_additions(universe, reranked, et(10, 15))
        self.assertEqual(added, [f"N{i}" for i in range(10)])
        self.assertEqual(len(universe.symbols), 35)
        # The 9:45 pick keeps the streamed slots all day; additions follow it.
        self.assertEqual(universe.stream_symbols(), [f"S{i:02d}" for i in range(25)])
        self.assertEqual(universe.symbols[25:], added)
        self.assertEqual(universe.ranks["S00"]["rank"], 11)
        self.assertEqual(universe.last_check_at, et(10, 15).isoformat(timespec="seconds"))

        more = [{"symbol": f"M{i:02d}", "rvol": 900 - i, "today_volume": 1, "avg_volume": 1, "sessions": 20, "rank": i + 1} for i in range(25)]
        added = rvol.merge_additions(universe, more, et(10, 45))
        self.assertEqual(len(added), 5)  # capped at MAX_SYMBOLS
        self.assertEqual(len(universe.symbols), rvol.MAX_SYMBOLS)
        self.assertEqual(rvol.merge_additions(universe, more, et(11, 15)), [])

    def test_bad_saved_times_and_ranks_do_not_raise(self) -> None:
        naive = rvol.DailyUniverse(session_date=SESSION.isoformat(), feed="iex", symbols=["A"], last_check_at="2026-11-05T09:45:00")
        self.assertTrue(rvol.recheck_due(naive, et(9, 50), True))
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "daily-universe.json"
            path.write_text('{"version": 1, "session_date": "2026-11-05", "feed": "iex", "symbols": ["A"], "ranks": "bad"}', encoding="utf-8")
            self.assertIsNone(rvol.load_daily_universe(path, SESSION.isoformat(), "iex"))

    def test_saved_list_reloads_only_for_the_same_session_and_feed(self) -> None:
        universe = rvol.DailyUniverse(session_date=SESSION.isoformat(), feed="iex", symbols=["AAA"], picked=["AAA"])
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "daily-universe.json"
            engine_module.write_private_json(path, rvol.universe_payload(universe))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
            self.assertEqual(rvol.load_daily_universe(path, SESSION.isoformat(), "iex"), universe)
            self.assertIsNone(rvol.load_daily_universe(path, "2026-11-06", "iex"))
            self.assertIsNone(rvol.load_daily_universe(path, SESSION.isoformat(), "sip"))
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(rvol.load_daily_universe(path, SESSION.isoformat(), "iex"))


def ranked_rows(names: list[str]) -> list[dict[str, Any]]:
    return [{"symbol": name, "rvol": 1000 - i, "today_volume": 1, "avg_volume": 1, "sessions": 20, "rank": i + 1} for i, name in enumerate(names)]


class ListSizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.universe = rvol.new_universe(ranked_rows([f"S{i:02d}" for i in range(60)]), et(9, 45), "iex")
        rvol.merge_additions(self.universe, ranked_rows([f"N{i}" for i in range(12)] + [f"S{i:02d}" for i in range(60)]), et(10, 15))

    def test_default_size_replays_the_stored_list(self) -> None:
        self.assertEqual(self.universe.list_for(), self.universe.symbols)
        self.assertEqual(self.universe.list_for(rvol.PICK_COUNT, rvol.MAX_SYMBOLS), self.universe.symbols)
        self.assertEqual(self.universe.picked, [f"S{i:02d}" for i in range(25)])

    def test_each_size_is_its_own_pick_plus_its_own_additions(self) -> None:
        # A 10-name list adds the ten newcomers in its top 10; a 5-name list only the top 5.
        self.assertEqual(self.universe.list_for(10, 40), [f"S{i:02d}" for i in range(10)] + [f"N{i}" for i in range(10)])
        self.assertEqual(self.universe.list_for(5, 8), [f"S{i:02d}" for i in range(5)] + ["N0", "N1", "N2"])
        self.assertEqual(self.universe.picked_for(10), [f"S{i:02d}" for i in range(10)])
        self.assertEqual(self.universe.stream_symbols(10), [f"S{i:02d}" for i in range(10)])
        # The list never shrinks below its own pick, even with a lower cap.
        self.assertEqual(len(self.universe.list_for(50, 10)), 50)

    def test_legacy_file_without_rankings_loads_the_same_list(self) -> None:
        legacy = {
            "version": 1, "session_date": SESSION.isoformat(), "feed": "iex",
            "picked_at": et(9, 45).isoformat(timespec="seconds"), "last_check_at": et(10, 15).isoformat(timespec="seconds"),
            "symbols": ["A", "B", "C", "D"], "picked": ["A", "B"],
            "added": [{"symbol": "C", "at": "t1"}, {"symbol": "D", "at": "t2"}], "ranks": {},
        }
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "daily-universe.json"
            path.write_text(__import__("json").dumps(legacy), encoding="utf-8")
            universe = rvol.load_daily_universe(path, SESSION.isoformat(), "iex")
        assert universe is not None
        self.assertEqual(universe.list_for(), ["A", "B", "C", "D"])
        self.assertEqual(universe.params, rvol.default_list_params())
        # A recheck after loading keeps the old list and adds on top of it.
        added = rvol.merge_additions(universe, ranked_rows(["E", "A"]), et(10, 45))
        self.assertEqual(added, ["E"])
        self.assertEqual(universe.symbols, ["A", "B", "C", "D", "E"])

    def test_saved_file_stays_version_one_with_the_default_list_on_top(self) -> None:
        payload = rvol.universe_payload(self.universe)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["symbols"], self.universe.list_for())
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "daily-universe.json"
            engine_module.write_private_json(path, payload)
            self.assertEqual(rvol.load_daily_universe(path, SESSION.isoformat(), "iex"), self.universe)

    def test_pick_time_and_recheck_follow_the_settings(self) -> None:
        self.assertFalse(rvol.pick_due(None, et(9, 59), True, minutes_after_open=30))
        self.assertTrue(rvol.pick_due(None, et(10, 0), True, minutes_after_open=30))
        universe = rvol.new_universe(ranked_rows(["A"]), et(10, 0), "iex", params=rvol.default_list_params() | {"recheck_seconds": 600})
        self.assertFalse(rvol.recheck_due(universe, et(10, 9), True))
        self.assertTrue(rvol.recheck_due(universe, et(10, 10), True))
        self.assertEqual(rvol.daily_bars_lookback_days(rvol.LOOKBACK_SESSIONS), rvol.DAILY_BARS_LOOKBACK_DAYS)


class ManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path_patch = patch.object(engine_module, "DAILY_UNIVERSE_PATH", Path(self.tmp.name) / "daily-universe.json")
        path_patch.start()
        self.addCleanup(path_patch.stop)
        stream_patch = patch.object(TraderManager, "ensure_market_data_stream")
        self.ensure_stream = stream_patch.start()
        self.addCleanup(stream_patch.stop)

        # 30 base symbols: B00 has the highest ratio, B29 the lowest.
        self.avg = {f"B{i:02d}": 1000.0 for i in range(30)}
        self.today = {f"B{i:02d}": 1000.0 * (60 - i) for i in range(30)}
        self.client = FakeDataClient(self.avg, self.today)
        self.manager = TraderManager()
        with self.manager.lock:
            self.manager.accounts = {}
        self.daily = self.add_account("Daily", "daily_rvol")
        self.live = self.add_account("Live", "most_active")
        self.manager.selected_account_id = self.daily.account_id

    def add_account(self, name: str, mode: str) -> Any:
        engine = self.manager.create_account(
            name, AppConfig(use_top_volume_symbols=True, inverse_etf_mode="allow", universe_mode=mode, use_market_stream=True)
        )
        engine.connected = True
        engine.data_client = self.client
        engine.market_clock = {"is_open": True}
        engine.top_volume_rows = top_rows(self.today)
        engine.top_volume_symbols = list(self.today)
        return engine

    def test_pending_until_the_pick_then_every_account_gets_the_list(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 40))
        self.assertEqual(self.daily.trading_symbol_source(), "daily_rvol_pending")
        self.assertEqual(self.daily.trading_symbols(), INVERSE)
        self.assertEqual(self.daily.state()["daily_universe"]["status"], "pending")
        self.assertEqual(self.client.bar_requests, [])

        self.manager.update_daily_universe(self.daily, et(9, 45))
        expected = [f"B{i:02d}" for i in range(25)]
        self.assertEqual(self.daily.trading_symbol_source(), "daily_rvol")
        self.assertEqual(self.daily.trading_symbols(), expected + INVERSE)
        state = self.daily.state()["daily_universe"]
        self.assertEqual((state["status"], state["picked_count"], state["picked_at"]), ("picked", 25, "9:45 AM ET"))
        self.assertEqual(len(self.client.bar_requests), 1)  # one batched daily-bars request for the base list
        # The most-active account is unchanged.
        self.assertEqual(self.live.trading_symbol_source(), "top_volume")
        self.assertEqual(self.live.trading_symbols()[:30], list(self.today))

    def test_restart_reloads_the_saved_list_without_refetching(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 45))
        restarted = TraderManager()
        with restarted.lock:
            restarted.accounts = {self.daily.account_id: self.daily}
        self.daily.apply_daily_universe([], engine_module.pending_daily_universe_meta())
        requests_before = len(self.client.bar_requests)
        restarted.update_daily_universe(self.daily, et(10, 0))
        self.assertEqual(self.daily.trading_symbols()[:25], [f"B{i:02d}" for i in range(25)])
        self.assertEqual(len(self.client.bar_requests), requests_before)

    def test_recheck_adds_newcomers_and_only_fetches_uncached_averages(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 45))
        self.avg["NEWS"] = 100.0
        self.today["NEWS"] = 1_000_000.0  # 10,000x normal volume
        for engine in (self.daily, self.live):
            engine.top_volume_rows = top_rows(self.today)
        self.manager.update_daily_universe(self.daily, et(10, 0))  # too soon to recheck
        self.assertNotIn("NEWS", self.daily.trading_symbols())

        self.manager.update_daily_universe(self.daily, et(10, 15))
        symbols = self.daily.trading_symbols()
        self.assertEqual(symbols[25], "NEWS")  # added after the 9:45 pick
        self.assertIn("B24", symbols)  # pushed out of the current top 25 but never removed
        self.assertEqual(self.client.bar_requests[-1], ["NEWS"])
        self.assertEqual(self.daily.state()["daily_universe"]["added_count"], 1)

    def test_closed_market_never_picks(self) -> None:
        self.daily.market_clock = {"is_open": False}
        self.manager.update_daily_universe(self.daily, et(10, 0))
        self.assertEqual(self.daily.trading_symbol_source(), "daily_rvol_pending")
        self.assertEqual(self.client.bar_requests, [])

    def test_failed_pick_retries_after_a_minute(self) -> None:
        for engine in (self.daily, self.live):
            engine.top_volume_rows = []
        self.manager.update_daily_universe(self.daily, et(9, 45))
        self.assertEqual(self.daily.trading_symbol_source(), "daily_rvol_pending")
        self.assertGreater(self.manager.daily_universe_retry_at, 0)

    def test_stream_slots_go_to_the_daily_list_and_inverse_set_before_positions(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 45))
        # market_data_symbols uses the real clock: treat the fixture session as today.
        self.manager.daily_universe.session_date = datetime.now(MARKET_TIMEZONE).date().isoformat()
        self.daily.positions = [{"symbol": "HELD", "qty_raw": "1"}]
        _dashboard, bar_symbols = self.manager.market_data_symbols()
        self.assertEqual(bar_symbols[:25], [f"B{i:02d}" for i in range(25)])
        self.assertEqual(bar_symbols[25:30], INVERSE)
        self.assertEqual(len(bar_symbols), engine_module.MARKET_STREAM_SYMBOL_LIMIT)
        self.assertNotIn("HELD", bar_symbols)
        self.assertIn("HELD", self.daily.scan_symbols())  # still scanned through REST bars

    def fake_stream(self, bar_symbols: list[str]) -> None:
        self.manager.market_stream = SimpleNamespace(
            thread=SimpleNamespace(is_alive=lambda: True),
            stop_event=SimpleNamespace(is_set=lambda: False),
            bar_symbols=sorted(bar_symbols),
        )

    def today_universe(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 45))
        self.manager.daily_universe.session_date = datetime.now(MARKET_TIMEZONE).date().isoformat()

    def test_stream_moves_to_the_daily_list_after_a_restart_and_back_when_switched_off(self) -> None:
        self.today_universe()
        self.fake_stream(["HELD", "SPY", "QQQ"] + INVERSE)  # subscribed at startup, before the list was loaded
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_called_once_with(resubscribe=True)

        self.ensure_stream.reset_mock()
        self.fake_stream([f"B{i:02d}" for i in range(25)] + INVERSE)  # now carrying the list
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_not_called()

        self.daily.config = self.daily.config.model_copy(update={"universe_mode": "most_active"})
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_called_once_with(resubscribe=True)
        self.ensure_stream.reset_mock()
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_not_called()

    def test_no_running_stream_means_no_resubscribe(self) -> None:
        self.today_universe()
        self.manager.market_stream = None
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_not_called()

    def test_daily_list_errors_never_skip_the_account_refresh(self) -> None:
        with patch.object(TraderManager, "update_daily_universe", side_effect=RuntimeError("boom")), \
                patch.object(engine_module.TraderEngine, "refresh_top_volume"):
            self.manager.refresh_trading_universe_for(self.daily)  # must not raise
        self.assertTrue(any("boom" in str(entry.get("message")) for entry in self.daily.logs))

    def test_most_active_only_keeps_positions_first(self) -> None:
        self.daily.config = self.daily.config.model_copy(update={"universe_mode": "most_active"})
        self.daily.positions = [{"symbol": "HELD", "qty_raw": "1"}]
        _dashboard, bar_symbols = self.manager.market_data_symbols()
        self.assertEqual(bar_symbols[0], "HELD")


class SelectionSettingsManagerTests(ManagerTests):
    """Per-account list sizes and app-wide list settings, on the ManagerTests fixture."""

    def set_config(self, engine: Any, **changes: Any) -> None:
        engine.config = AppConfig.model_validate(engine.config.model_dump() | changes)

    def test_each_account_gets_its_own_list_size_from_one_ranking(self) -> None:
        small = self.add_account("Small", "daily_rvol")
        large = self.add_account("Large", "daily_rvol")
        self.set_config(small, daily_pick_count=10)
        self.set_config(large, daily_pick_count=28, daily_max_symbols=60)
        self.manager.update_daily_universe(self.daily, et(9, 45))
        self.assertEqual(len(self.client.bar_requests), 1)
        self.assertEqual(self.daily.trading_symbols(), [f"B{i:02d}" for i in range(25)] + INVERSE)
        self.assertEqual(small.trading_symbols(), [f"B{i:02d}" for i in range(10)] + INVERSE)
        self.assertEqual(large.trading_symbols(), [f"B{i:02d}" for i in range(28)] + INVERSE)
        state = small.state()["daily_universe"]
        self.assertEqual((state["pick_count"], state["picked_count"], state["added_count"]), (10, 10, 0))

        # A newcomer ranked 1st joins every list on the recheck.
        self.avg["NEWS"] = 100.0
        self.today["NEWS"] = 1_000_000.0
        for engine in (self.daily, self.live, small, large):
            engine.top_volume_rows = top_rows(self.today)
        self.manager.update_daily_universe(self.daily, et(10, 15))
        self.assertEqual(small.trading_symbols()[10], "NEWS")
        self.assertEqual(large.trading_symbols()[28], "NEWS")
        self.assertEqual(small.state()["daily_universe"]["added_count"], 1)

    def test_pick_time_comes_from_the_app_settings(self) -> None:
        self.manager.set_app_settings(engine_module.app_settings.AppWideSettings(daily_pick_minutes_after_open=30))
        self.manager.update_daily_universe(self.daily, et(9, 45))
        state = self.daily.state()["daily_universe"]
        self.assertEqual((state["status"], state["pick_time"]), ("pending", "10:00 AM ET"))
        self.manager.update_daily_universe(self.daily, et(10, 0))
        self.assertEqual(self.daily.state()["daily_universe"]["status"], "picked")

    def test_settings_changed_after_the_pick_wait_for_the_next_day(self) -> None:
        self.manager.update_daily_universe(self.daily, et(9, 45))
        self.manager.set_app_settings(engine_module.app_settings.AppWideSettings(daily_recheck_minutes=5, rvol_lookback_sessions=10))
        self.avg["NEWS"] = 100.0
        self.today["NEWS"] = 1_000_000.0
        for engine in (self.daily, self.live):
            engine.top_volume_rows = top_rows(self.today)
        self.manager.update_daily_universe(self.daily, et(9, 55))  # today's recheck is still every 30 minutes
        self.assertNotIn("NEWS", self.daily.trading_symbols())
        self.manager.update_daily_universe(self.daily, et(10, 15))
        self.assertIn("NEWS", self.daily.trading_symbols())
        # The recheck's daily bars still use the pick's 20-session lookback (45 days).
        self.assertEqual(self.manager.daily_universe.params["lookback_sessions"], 20)
        self.assertLess(abs((self.client.bar_starts[-1] - self.client.bar_starts[0]).total_seconds()), 60)

    def test_lookback_sets_the_daily_bars_window(self) -> None:
        self.manager.set_app_settings(engine_module.app_settings.AppWideSettings(rvol_lookback_sessions=10, rvol_min_sessions=5))
        before = datetime.now(timezone.utc)
        self.manager.update_daily_universe(self.daily, et(9, 45))
        start = self.client.bar_starts[0]
        start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        self.assertAlmostEqual((before - start).total_seconds(), timedelta(days=rvol.daily_bars_lookback_days(10)).total_seconds(), delta=60)
        self.assertEqual(self.manager.daily_universe.params["lookback_sessions"], 10)

    def test_stream_limit_is_an_app_setting(self) -> None:
        self.today_universe()
        self.daily.positions = [{"symbol": "HELD", "qty_raw": "1"}]
        self.manager.set_app_settings(engine_module.app_settings.AppWideSettings(market_stream_symbol_limit=40))
        _dashboard, bar_symbols = self.manager.market_data_symbols()
        self.assertGreater(len(bar_symbols), engine_module.MARKET_STREAM_SYMBOL_LIMIT)
        self.assertIn("HELD", bar_symbols)
        self.assertEqual(self.manager.market_stream_state()["symbol_limit"], 40)

    def test_a_pick_larger_than_the_stream_limit_does_not_resubscribe_every_refresh(self) -> None:
        self.manager.set_app_settings(engine_module.app_settings.AppWideSettings(market_stream_symbol_limit=20))
        self.today_universe()
        _dashboard, bar_symbols = self.manager.market_data_symbols()
        self.assertEqual(bar_symbols, [f"B{i:02d}" for i in range(20)])
        self.fake_stream(bar_symbols)
        self.manager.sync_daily_universe_stream()
        self.manager.sync_daily_universe_stream()
        self.ensure_stream.assert_not_called()

    def test_stream_carries_every_daily_accounts_inverse_set(self) -> None:
        other = self.add_account("Other", "daily_rvol")
        self.set_config(self.daily, inverse_etf_symbols=["SH"])
        self.set_config(other, inverse_etf_symbols=["SQQQ", "PSQ"])
        self.today_universe()
        _dashboard, bar_symbols = self.manager.market_data_symbols()
        self.assertEqual(bar_symbols[25:28], ["SH", "SQQQ", "PSQ"])
        self.assertEqual(self.daily.trading_symbols()[25:], ["SH"])


class ConfigTests(unittest.TestCase):
    def test_universe_mode_is_a_validated_profile_key(self) -> None:
        self.assertEqual(AppConfig().universe_mode, "most_active")
        self.assertEqual(AppConfig(universe_mode=" Daily_RVOL ").universe_mode, "daily_rvol")
        with self.assertRaises(ValueError):
            AppConfig(universe_mode="random")
        self.assertIn("universe_mode", engine_module.PROFILE_STRATEGY_KEYS)
        for preset in engine_module.PROFILE_PRESETS.values():
            self.assertEqual(preset.get("universe_mode"), "most_active")


if __name__ == "__main__":
    unittest.main()
