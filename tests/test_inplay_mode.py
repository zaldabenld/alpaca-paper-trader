"""Day-trade mode (entry_mode "inplay"): ranking, entries, stops, the data worker, and isolation."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import inplay as P  # noqa: E402
from alpaca_desktop.engine import AppConfig, TraderEngine  # noqa: E402

D = Decimal


def rng(o: str, h: str, l: str, c: str, v: str) -> P.RangeBar:
    return P.RangeBar(D(o), D(h), D(l), D(c), D(v))


def stats(atr: str = "4", dollars: str = "50000000") -> P.DailyStats:
    return P.DailyStats(atr_percent=D(atr), dollar_volume=D(dollars))


def rank(today: dict[str, P.RangeBar], history: dict[str, list[Decimal]], daily: dict[str, P.DailyStats], **kw: Any):
    params = dict(min_relative_volume=D("2.5"), min_atr_percent=D("3"), min_dollar_volume=D("20000000"), max_picks=10, stop_mode="range_mid")
    params.update(kw)
    return P.rank_picks(today, history, daily, **params)


class RankingTests(unittest.TestCase):
    def test_ranks_by_relative_range_volume_and_applies_every_filter(self) -> None:
        history = {s: [D("1000")] * 14 for s in ("HOT", "WARM", "THIN", "QUIET", "SLOW", "RED", "SPY", "NEW")}
        history["NEW"] = [D("1000")] * 5
        today = {
            "HOT": rng("10", "10.6", "9.9", "10.5", "5000"),     # 5x
            "WARM": rng("20", "20.4", "19.9", "20.3", "3000"),   # 3x
            "THIN": rng("5", "5.2", "4.9", "5.1", "9000"),       # not liquid
            "QUIET": rng("50", "50.2", "49.9", "50.1", "9000"),  # daily range too small
            "SLOW": rng("8", "8.2", "7.9", "8.1", "2000"),       # only 2x
            "RED": rng("30", "30.5", "29.5", "29.8", "9000"),    # closed under its open
            "SPY": rng("700", "702", "699", "701", "9000"),      # index fund
            "NEW": rng("12", "12.5", "11.9", "12.4", "9000"),    # too little history
        }
        daily = {s: stats() for s in today}
        daily["THIN"] = stats(dollars="5000000")
        daily["QUIET"] = stats(atr="1.2")
        picks, rejected = rank(today, history, daily)
        self.assertEqual([pick.symbol for pick in picks], ["HOT", "WARM"])
        self.assertEqual(picks[0].relative_volume, D("5"))
        self.assertEqual(picks[0].stop, D("10.25"))  # range middle
        self.assertEqual(rejected, {"no data": 1, "liquidity": 1, "daily range": 1, "range volume": 1, "red range": 1, "index fund": 1})

    def test_max_picks_and_range_low_stop(self) -> None:
        history = {s: [D("100")] * 14 for s in "ABC"}
        today = {"A": rng("1", "1.2", "0.9", "1.1", "500"), "B": rng("1", "1.2", "0.9", "1.1", "900"), "C": rng("1", "1.2", "0.9", "1.1", "700")}
        picks, _ = rank(today, history, {s: stats() for s in today}, max_picks=2, stop_mode="range_low")
        self.assertEqual([pick.symbol for pick in picks], ["B", "C"])
        self.assertEqual(picks[0].stop, D("0.89"))

    def test_daily_stats(self) -> None:
        bars = [(D("10"), D("11"), D("9"), D("10"), D("1000000"))] * 21
        stat = P.daily_stats(bars)
        self.assertEqual(stat.atr_percent, D("20"))
        self.assertEqual(stat.dollar_volume, D("10000000"))
        self.assertIsNone(P.daily_stats(bars[:20]))

    def test_entry_waits_for_the_break_and_skips_a_chase(self) -> None:
        pick = P.Pick("HOT", 0, D("10.60"), D("9.90"), D("10"), D("10.5"), D("5"), D("4"), D("5e7"), D("10.25"))
        self.assertIn("waiting for a break", P.entry_hold_reason(pick, D("10.60"), D("1")))
        self.assertEqual(P.entry_hold_reason(pick, D("10.65"), D("1")), "")
        self.assertIn("past the range high", P.entry_hold_reason(pick, D("10.75"), D("1")))
        self.assertIn("waiting for a price", P.entry_hold_reason(pick, None, D("1")))


def pick(symbol: str = "HOT", high: str = "10.60", low: str = "9.90", rank_: int = 0) -> P.Pick:
    return P.Pick(symbol, rank_, D(high), D(low), D("10"), D("10.5"), D("5"), D("4"), D("50000000"), (D(high) + D(low)) / 2)


NOON = datetime(2026, 11, 12, 17, 0, tzinfo=timezone.utc)  # 12:00 ET


class Broker:
    def __init__(self, positions: list[dict[str, Any]] | None = None) -> None:
        self.positions = list(positions or [])
        self.submitted: list[Any] = []

    def get_account(self) -> dict[str, Any]:
        return {"equity": "100000", "last_equity": "100000", "cash": "100000", "buying_power": "100000"}

    def get_clock(self) -> Any:
        return SimpleNamespace(is_open=True, timestamp=NOON, next_close=NOON.replace(hour=21), next_open=NOON + timedelta(days=1))

    def get_all_positions(self) -> list[dict[str, Any]]:
        return list(self.positions)

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        return []

    def submit_order(self, order: Any) -> Any:
        self.submitted.append(order)
        return SimpleNamespace(id=f"o{len(self.submitted)}", client_order_id=order.client_order_id)

    def cancel_order_by_id(self, order_id: str) -> None:
        pass


def day_engine(broker: Broker, picks: list[P.Pick], prices: dict[str, str], **config: Any) -> TraderEngine:
    engine = TraderEngine("day")
    engine.config = AppConfig(entry_mode="inplay", use_top_volume_symbols=False, symbols=["SPY"], dry_run=False,
                              trade_size_mode="percent", max_trade_percent="10", max_total_exposure_percent="100",
                              max_open_positions=10, max_entries_per_scan=10, take_profit_percent="0", stop_loss_percent="3",
                              entry_open_guard_minutes=15, entry_close_guard_minutes=60, flatten_before_close_minutes=10, **config)
    engine.connected = True
    engine.trading_enabled = True
    engine.trading_client = broker  # type: ignore[assignment]
    engine.data_client = SimpleNamespace(get_stock_bars=lambda request: SimpleNamespace(data={}))  # type: ignore[assignment]
    engine.inplay_picks = {item.symbol: item for item in picks}
    engine.inplay_picks_session = "2026-11-12"
    engine.inplay_history = ("2026-11-12", {}, {})
    for symbol, price in prices.items():
        # A falling series: RSI near zero and a bearish trend, so the momentum gates would all say no.
        for minute in range(60):
            engine.strategy_state.add_bar(symbol, D(price) + D(60 - minute) / 100, NOON - timedelta(minutes=60 - minute), 1000)
    return engine


def refresh(engine: TraderEngine, symbols: tuple[str, ...]) -> None:
    with (
        patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
        patch.object(engine, "record_day_tape_scan"),
        patch.object(engine, "record_day_tape_bars"),
        patch.object(engine, "current_trade_price", side_effect=lambda symbol, fallback: fallback),
        patch.object(engine, "asset_tradeability_hold_reason", return_value=""),
    ):
        engine.refresh(run_strategy=True, shared_bars={symbol: [] for symbol in symbols + ("SPY", "QQQ")})


class EngineTests(unittest.TestCase):
    def test_a_pick_that_breaks_out_is_bought_without_the_momentum_gates(self) -> None:
        broker = Broker()
        engine = day_engine(broker, [pick("HOT")], {"HOT": "10.64"})
        refresh(engine, ("HOT",))
        self.assertEqual([(order.symbol, order.side.value) for order in broker.submitted], [("HOT", "buy")])
        self.assertAlmostEqual(float(broker.submitted[0].qty) * 10.65, 10000, delta=15)  # 10% of equity

    def test_inside_the_range_or_past_the_chase_limit_nothing_is_bought(self) -> None:
        for price in ("10.40", "10.80"):
            with self.subTest(price=price):
                broker = Broker()
                engine = day_engine(broker, [pick("HOT")], {"HOT": price})
                refresh(engine, ("HOT",))
                self.assertEqual(broker.submitted, [])

    def test_only_picks_are_considered_and_in_rank_order(self) -> None:
        engine = day_engine(Broker(), [pick("B", rank_=1), pick("A", rank_=0)], {})
        self.assertEqual(engine.mode_entry_symbols(), ["A", "B"])
        self.assertEqual(engine.scan_symbols(set())[:2], ["A", "B"])

    def test_once_a_day_per_symbol(self) -> None:
        broker = Broker()
        engine = day_engine(broker, [pick("HOT")], {"HOT": "10.64"})
        engine.entries_today_by_symbol = {"HOT": 1}
        with patch.object(engine, "sync_entries_today_from_orders"):
            refresh(engine, ("HOT",))
        self.assertEqual(broker.submitted, [])

    def test_the_stop_is_the_range_middle_and_falls_back_to_percent_without_a_pick(self) -> None:
        engine = day_engine(Broker(), [pick("HOT")], {})
        self.assertEqual(engine.position_stop_price("HOT", D("10.65"), D("10.9"), engine.config), D("10.25"))
        self.assertEqual(engine.position_stop_price("ZZZ", D("100"), D("100"), engine.config), D("95.00"))  # never under 5% away

    def test_held_pick_gets_a_broker_stop_at_the_range_middle(self) -> None:
        held = {"symbol": "HOT", "qty": "939", "qty_available": "939", "avg_entry_price": "10.65", "current_price": "10.80",
                "market_value": "10141", "side": "long"}
        broker = Broker(positions=[held])
        engine = day_engine(broker, [pick("HOT")], {"HOT": "10.80"})
        refresh(engine, ("HOT",))
        self.assertEqual([(order.side.value, order.type.value, float(order.stop_price)) for order in broker.submitted], [("sell", "stop", 10.25)])

    def test_day_trades_always_sell_before_the_close_and_ignore_take_profit(self) -> None:
        engine = day_engine(Broker(), [pick("HOT")], {}, )
        engine.config = engine.config.model_copy(update={"flatten_before_close_minutes": 0, "take_profit_percent": D("2.5")})
        clock = SimpleNamespace(is_open=True, timestamp=NOON.replace(hour=20, minute=55), next_close=NOON.replace(hour=21))
        self.assertIn("selling everything 10 min before the close", engine.close_flatten_message(clock, engine.config))
        self.assertEqual(engine.position_take_profit_price("HOT", D("10.65"), engine.config), D("0"))
        held = {"qty": "10", "avg_entry_price": "10", "current_price": "11"}
        self.assertEqual(engine.local_protection_exit_decision("HOT", engine.config, held, D("11"), False, True), ("", ""))

    def test_a_restart_reloads_todays_picks_before_any_stop_is_checked(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "inplay_picks.json"
            with patch.object(TraderEngine, "INPLAY_PICKS_PATH", path):
                first = day_engine(Broker(), [pick("HOT")], {})
                first.save_inplay_picks(date(2026, 11, 12), [pick("HOT")], 300, {"range volume": 250})
                held = {"symbol": "HOT", "qty": "939", "qty_available": "939", "avg_entry_price": "10.65", "current_price": "10.30",
                        "market_value": "9672", "side": "long"}
                broker = Broker(positions=[held])
                restarted = day_engine(broker, [], {"HOT": "10.30"})
                restarted.inplay_picks = {}
                restarted.inplay_picks_session = ""
                with patch.object(restarted, "start_inplay_worker") as worker:
                    refresh(restarted, ("HOT",))
                worker.assert_not_called()
        self.assertEqual(list(restarted.inplay_picks), ["HOT"])
        # The stop placed is the range middle (10.25), so a price of 10.30 is not sold by a tighter fallback.
        self.assertEqual([(order.side.value, order.type.value, float(order.stop_price)) for order in broker.submitted], [("sell", "stop", 10.25)])

    def test_a_live_day_trade_stop_is_never_loosened_but_momentum_keeps_its_rule(self) -> None:
        stop = {"id": "s1", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "10", "stop_price": "10.25",
                "client_order_id": "apt-protect-sl-hot-1"}
        engine = day_engine(Broker(), [], {})
        with patch.object(engine, "cancel_open_order", return_value=True) as cancel:
            self.assertFalse(engine.cancel_stale_protective_order(stop, D("10"), D("0"), D("10.11"), D("10.65")))
            cancel.assert_not_called()
        momentum = TraderEngine("momentum")
        momentum.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"])
        with patch.object(momentum, "cancel_open_order", return_value=True) as cancel:
            self.assertTrue(momentum.cancel_stale_protective_order(stop, D("10"), D("0"), D("10.11"), D("10.65")))

    def test_failed_loads_back_off(self) -> None:
        engine = TraderEngine("day")
        engine.config = AppConfig(entry_mode="inplay")
        with patch.object(engine, "inplay_universe", side_effect=RuntimeError("down")), \
             patch("alpaca_desktop.engine.StockHistoricalDataClient"), patch("alpaca_desktop.engine.TradingClient"):
            engine.inplay_work(date(2026, 11, 12), True, "k", "s")
            import time as clock
            self.assertAlmostEqual(engine.inplay_retry_at - clock.monotonic(), 60, delta=5)
            engine.inplay_work(date(2026, 11, 12), True, "k", "s")
            self.assertAlmostEqual(engine.inplay_retry_at - clock.monotonic(), 120, delta=5)
        self.assertEqual(engine.inplay_failures, 2)

    def test_momentum_accounts_are_untouched(self) -> None:
        engine = TraderEngine("momentum")
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["AAA", "BBB"])
        engine.inplay_picks = {"HOT": pick("HOT")}
        self.assertEqual(engine.mode_entry_symbols(), engine.trading_symbols())
        self.assertEqual(engine.position_stop_price("HOT", D("100"), D("100"), engine.config), D("98.75"))
        with patch.object(engine, "inplay_entry_hold_reason") as day_hold:
            engine.entry_quality_hold_reason("AAA", engine.snapshot("AAA"), engine.config)
        day_hold.assert_not_called()


class FakeCalendarClient:
    def get_calendar(self, request: Any) -> list[Any]:
        days, day = [], request.start
        while day <= request.end:
            if day.weekday() < 5:
                days.append(SimpleNamespace(date=day))
            day += timedelta(days=1)
        return days


class FakeSipData:
    """Opening ranges: HOT trades 5x its usual range volume today, COLD 1x."""

    def __init__(self) -> None:
        self.requests: list[Any] = []

    def get_stock_bars(self, request: Any) -> Any:
        self.requests.append(request)
        symbols = request.symbol_or_symbols
        if request.timeframe.amount == 1 and str(request.timeframe.unit.value).lower().startswith("day"):
            bars = {s: [SimpleNamespace(timestamp=datetime(2026, 10, 1, 5, tzinfo=timezone.utc) + timedelta(days=i),
                                        open=10, high=10.5, low=9.9, close=10, volume=5_000_000) for i in range(30)] for s in symbols}
            return SimpleNamespace(data=bars)
        start = request.start if request.start.tzinfo else request.start.replace(tzinfo=timezone.utc)  # the request stores UTC
        today = start.date() == date(2026, 11, 12)
        bars = {}
        for s in symbols:
            volume = 5000 if (today and s == "HOT") else 1000
            bars[s] = [SimpleNamespace(timestamp=start + timedelta(minutes=5 * i), open=10 + i * 0.1, high=10.5 + i * 0.1,
                                       low=9.9, close=10.2 + i * 0.1, volume=volume / 3) for i in range(3)]
        return SimpleNamespace(data=bars)


class WorkerTests(unittest.TestCase):
    def test_worker_loads_history_then_ranks_todays_picks(self) -> None:
        engine = TraderEngine("day")
        engine.config = AppConfig(entry_mode="inplay")
        data = FakeSipData()
        with (
            patch("alpaca_desktop.engine.StockHistoricalDataClient", return_value=data),
            patch("alpaca_desktop.engine.TradingClient", return_value=FakeCalendarClient()),
            patch.object(engine, "inplay_universe", return_value=["HOT", "COLD"]),
            patch.object(engine, "remember_inplay_actives"),
            patch.object(engine, "save_inplay_picks"),
        ):
            engine.inplay_work(date(2026, 11, 12), False, "key", "secret")
            self.assertEqual(engine.inplay_picks, {})
            self.assertEqual(len(engine.inplay_history[1]["HOT"]), 14)
            engine.inplay_work(date(2026, 11, 12), True, "key", "secret")
        self.assertEqual(list(engine.inplay_picks), ["HOT"])
        self.assertEqual(engine.inplay_picks["HOT"].high, D("10.7"))
        sip = [request for request in data.requests if str(request.feed.value).lower() == "sip"]
        self.assertEqual(len(sip), len(data.requests))

    def test_universe_adds_recent_most_actives_from_the_tapes(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        engine = TraderEngine("day")
        engine.config = AppConfig(entry_mode="inplay")
        with tempfile.TemporaryDirectory() as folder:
            tape_dir = Path(folder)
            lines = [json.dumps({"kind": "market_trade", "payload": {"symbol": "X"}})] * 50
            lines.insert(10, json.dumps({"kind": "top_volume_snapshot", "payload": {"symbols": ["ZZZA", "ZZZB"]}}))
            (tape_dir / "tape-20261111.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (tape_dir / "tape-20261112.jsonl").write_text(json.dumps({"kind": "top_volume_snapshot", "payload": {"symbols": ["TODAY"]}}) + "\n")
            with patch("alpaca_desktop.engine.DAY_TAPE_DIR", tape_dir), patch.object(engine, "inplay_recent_actives", return_value=[]):
                universe = engine.inplay_universe(date(2026, 11, 12))
        self.assertIn("ZZZA", universe)
        self.assertIn("ZZZB", universe)
        self.assertNotIn("TODAY", universe)  # only earlier sessions
        self.assertIn("NVDA", universe)

    def test_picks_wait_for_the_range_plus_the_data_delay(self) -> None:
        engine = TraderEngine("day")
        engine.config = AppConfig(entry_mode="inplay", inplay_range_minutes=15)
        ready = engine.inplay_ready_at(date(2026, 11, 12), engine.config)
        self.assertEqual((ready.hour, ready.minute), (10, 1))


if __name__ == "__main__":
    unittest.main()
