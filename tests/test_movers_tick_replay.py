"""scripts/movers_tick_replay.py: buys at the ask, sells at the bid that reaches the stop, and applies
the settings under test. Driven with made-up bars and quotes; no network."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import movers as M  # noqa: E402
from alpaca_desktop.engine import MARKET_TIMEZONE, AppConfig  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
D = Decimal


def load_replay() -> Any:
    spec = importlib.util.spec_from_file_location("movers_tick_replay_under_test", REPO_ROOT / "scripts" / "movers_tick_replay.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = load_replay()
DAY = date(2026, 11, 13)
OPEN = datetime.combine(DAY, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30).astimezone(timezone.utc)
BASE = AppConfig(entry_mode="movers", min_entry_score="60", stop_loss_percent="1.25", profit_trail_start_percent="2",
                 profit_trail_drop_percent="1", take_profit_percent="0", max_trade_percent="5", max_open_positions=20,
                 entry_open_guard_minutes=30, entry_close_guard_minutes=30, flatten_before_close_minutes=10)
STRONG = M.Readings(relative_volume=D("5"), half_hour_move=D("0"), five_min_move=D("0.7"), vwap_distance=D("3"),
                    session_change=D("5"), daily_range=D("8"), stop_percent=D("1.25"), price=D("1.25"))   # scores 85


class FakeMarket:
    """Quotes by (symbol, minute index); a flat default otherwise."""

    def __init__(self, bid: str = "1.24", ask: str = "1.25") -> None:
        self.default = (D(bid), D(ask))
        self.at: dict[int, tuple[D, D]] = {}
        self.minute: dict[int, list[tuple[int, str, str]]] = {}
        self.minute_reads = 0

    def index(self, moment: datetime) -> int:
        return int((moment - OPEN).total_seconds() // 60)

    def quote_at(self, symbol: str, at: datetime) -> tuple[D, D]:
        return self.at.get(self.index(at), self.default)

    def quotes_in_minute(self, symbol: str, start: datetime) -> list[tuple[datetime, D, D]]:
        self.minute_reads += 1
        return [(start + timedelta(seconds=second), D(bid), D(ask)) for second, bid, ask in self.minute.get(self.index(start), [])]


def day(bars: dict[int, tuple[str, str, str]], signal_minutes: set[int], reading: M.Readings = STRONG, not_buyable: set[str] | None = None) -> Any:
    """HOT with (high, low, close) bars by minute index; a buy signal at the end of each listed minute."""
    by_minute: list[dict[str, Any]] = [{} for _ in range(390)]
    for index, (high, low, close) in bars.items():
        by_minute[index]["HOT"] = (OPEN + timedelta(minutes=index), D(close), D(high), D(low), D(close), D("1000"))
    readings: list[dict[str, M.Readings]] = [({"HOT": reading} if index in signal_minutes else {}) for index in range(390)]
    return SimpleNamespace(day=DAY, open=OPEN, close=OPEN + timedelta(hours=6, minutes=30), by_minute=by_minute,
                           readings=readings, not_buyable=not_buyable or set())


def run(data: Any, market: FakeMarket, **options: Any) -> list[Any]:
    settings = dict(boost="0", spread="0", volume_current=False, new_high=False)
    settings.update(options)
    return R.replay_day(data, market, BASE, settings)


class ReplayTests(unittest.TestCase):
    def test_buys_at_the_ask_and_the_stop_sells_at_the_bid_that_reaches_it(self) -> None:
        market = FakeMarket()
        market.minute[41] = [(5, "1.24", "1.25"), (20, "1.23", "1.24"), (40, "1.22", "1.23")]
        trades = run(day({40: ("1.25", "1.24", "1.25"), 41: ("1.25", "1.22", "1.22")}, {40}), market)
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual((trade.entry, trade.exit, trade.reason), (D("1.25"), D("1.23"), "stop loss"))   # stop $1.23: two ticks under
        self.assertEqual(trade.bought_at, "10:11:02")
        self.assertEqual(trade.sold_at, "10:11:20")
        self.assertEqual(trade.pnl, (D("1.23") - D("1.25")) * (D("50") / D("1.25")))

    def test_a_quiet_minute_is_not_stepped_through(self) -> None:
        market = FakeMarket(bid="10.00", ask="10.01")
        reading = M.Readings(**{**STRONG.__dict__, "price": D("10.01")})
        bars = {40: ("10.01", "10.00", "10.01"), 41: ("10.05", "10.00", "10.03"), 380: ("10.03", "10.02", "10.03")}
        trades = run(day(bars, {40}, reading), market)
        self.assertEqual(market.minute_reads, 0)
        self.assertEqual([(trade.reason, trade.exit) for trade in trades], [("sold before the close", D("10.00"))])

    def test_the_trail_follows_the_bid_and_sells_at_a_gain(self) -> None:
        market = FakeMarket(bid="10.00", ask="10.01")
        reading = M.Readings(**{**STRONG.__dict__, "price": D("10.01")})
        market.minute[42] = [(10, "10.30", "10.31"), (30, "10.18", "10.19")]   # trail stop $10.18
        bars = {40: ("10.01", "10.00", "10.01"), 41: ("10.31", "10.05", "10.30"), 42: ("10.31", "10.18", "10.18")}
        trades = run(day(bars, {40}, reading), market)
        self.assertEqual([(trade.reason, trade.exit) for trade in trades], [("trailing stop", D("10.18"))])
        self.assertGreater(trades[0].pnl, 0)

    def test_no_buys_inside_the_open_and_close_guards_or_of_a_stock_the_app_cannot_buy(self) -> None:
        bars = {index: ("1.25", "1.25", "1.25") for index in (10, 40, 365)}
        self.assertEqual(run(day(bars, {10, 365}), FakeMarket()), [])
        self.assertEqual(run(day(bars, {40}, not_buyable={"HOT"}), FakeMarket()), [])

    def test_the_spread_setting_holds_a_stock_quoted_a_cent_wide_at_this_price(self) -> None:
        bars = {40: ("1.25", "1.24", "1.25"), 380: ("1.25", "1.24", "1.25")}
        self.assertEqual(len(run(day(bars, {40}), FakeMarket())), 1)
        self.assertEqual(run(day(bars, {40}), FakeMarket(), spread="40"), [])     # 85 less 26 is under 60

    def test_each_losing_exit_raises_the_score_needed(self) -> None:
        market = FakeMarket()
        for index in (41, 51):
            market.minute[index] = [(20, "1.22", "1.23")]
        bars = {40: ("1.25", "1.24", "1.25"), 41: ("1.25", "1.22", "1.22"), 50: ("1.25", "1.24", "1.25"),
                51: ("1.25", "1.22", "1.22"), 60: ("1.25", "1.24", "1.25"), 380: ("1.25", "1.24", "1.25")}
        self.assertEqual(len(run(day(bars, {40, 50, 60}), market)), 3)                        # no bar: bought every time
        self.assertEqual(len(run(day(bars, {40, 50, 60}), market, boost="20")), 2)            # 85 clears 80, not 100

    def test_a_sale_at_a_gain_needs_the_boost_until_a_new_high(self) -> None:
        market = FakeMarket(bid="10.00", ask="10.01")
        reading = M.Readings(**{**STRONG.__dict__, "price": D("10.01")})          # scores 85, under 60 + 30
        market.minute[42] = [(10, "10.30", "10.31"), (30, "10.18", "10.19")]   # trail stop $10.18
        bars = {40: ("10.01", "10.00", "10.01"), 41: ("10.31", "10.05", "10.30"), 42: ("10.31", "10.18", "10.18"),
                50: ("10.21", "10.20", "10.21"), 380: ("10.21", "10.20", "10.21")}
        again = dict(bars)
        again[45] = ("10.40", "10.20", "10.21")                                    # a new high after the sale
        self.assertEqual(len(run(day(bars, {40, 50}, reading), market, boost="30", new_high=False)), 2)
        self.assertEqual(len(run(day(bars, {40, 50}, reading), market, boost="30", new_high=True)), 1)
        self.assertEqual(len(run(day(again, {40, 50}, reading), market, boost="30", new_high=True)), 2)


if __name__ == "__main__":
    unittest.main()
