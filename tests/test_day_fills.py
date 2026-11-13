"""The day's fills are kept all day: buy counts, the trade table and realized P/L cover the whole
session, a stop filling in pieces is left to finish, and old sells do not log stale warnings."""

from __future__ import annotations

import time as clock_module
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import MARKET_TIMEZONE, AppConfig, TraderEngine  # noqa: E402

from .test_inplay_mode import Broker, day_engine, pick  # noqa: E402
from .test_movers_mode import ClosedOrdersBroker, filled, movers_engine, refresh  # noqa: E402

D = Decimal


class WindowBroker(ClosedOrdersBroker):
    """The regular read returns only the newest `window` closed orders; the whole-day read pages
    through all of them, newest first, the way Alpaca does."""

    def __init__(self, closed: list[dict[str, Any]], window: int) -> None:
        super().__init__(closed)
        self.window = window

    def get_clock(self) -> Any:
        # Open at noon ET on the fixtures' day, whatever the hour or time zone the test runs in.
        day = datetime.now(MARKET_TIMEZONE).date()
        noon = (datetime.combine(day, datetime.min.time(), tzinfo=MARKET_TIMEZONE) + timedelta(hours=12)).astimezone(timezone.utc)
        return SimpleNamespace(is_open=True, timestamp=noon, next_close=noon + timedelta(hours=4), next_open=noon + timedelta(days=1))

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        if "closed" not in str(getattr(request, "status", "")).lower():
            return []
        self.closed_requests.append(request)
        # Alpaca orders the list by when each order was submitted, not by when it filled.
        newest_first = sorted(self.closed, key=lambda order: order.get("submitted_at") or order["filled_at"], reverse=True)
        if getattr(request, "after", None) is None:
            return newest_first[: self.window]
        until = getattr(request, "until", None)
        if until is not None:
            newest_first = [order for order in newest_first if datetime.fromisoformat(order["submitted_at"].replace("Z", "+00:00")) <= until]
        return newest_first[: request.limit]


def round_trips(count: int, buy: str = "10.00", sell: str = "9.90", symbol: str = "HOT") -> list[dict[str, Any]]:
    orders: list[dict[str, Any]] = []
    for index in range(count):
        minutes_ago = 2 * (count - index) + 10
        for order in (filled(f"b{index}", "buy", buy, minutes_ago, symbol=symbol), filled(f"s{index}", "sell", sell, minutes_ago - 1, symbol=symbol)):
            order["submitted_at"] = order["filled_at"]
            orders.append(order)
    return orders


class PartFilledStopTests(unittest.TestCase):
    # MRLN 2026-11-13 13:32: a 19.6581-share stop at $1.23 had filled 5 shares. The app called the
    # stop the wrong size, cancelled it, had its replacement rejected as already crossed and sold
    # the other 14.6581 itself.
    held = {"symbol": "HOT", "qty": "14.6581", "qty_available": "0", "avg_entry_price": "1.25",
            "current_price": "1.23", "side": "long"}
    stop = {"id": "s1", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "19.6581", "filled_qty": "5",
            "status": "partially_filled", "stop_price": "1.23", "client_order_id": "apt-protect-sl-hot-1"}

    def open_orders(self, *orders: dict[str, Any]) -> Any:
        return lambda request: list(orders) if "open" in str(getattr(request, "status", "")).lower() else []

    def test_a_stop_that_is_filling_in_pieces_is_left_to_finish(self) -> None:
        broker = Broker(positions=[self.held])
        engine = movers_engine(broker, bars=150)
        with (
            patch.object(broker, "get_orders", side_effect=self.open_orders(self.stop)),
            patch.object(broker, "cancel_order_by_id") as cancel,
        ):
            refresh(engine)
        cancel.assert_not_called()
        self.assertEqual(broker.submitted, [])
        self.assertEqual([entry for entry in engine.logs if entry["level"] == "error"], [])

    def test_a_stop_that_has_not_triggered_and_is_the_wrong_size_is_still_replaced(self) -> None:
        untouched = dict(self.stop, filled_qty="0", status="new")
        broker = Broker(positions=[self.held])
        engine = movers_engine(broker, bars=150)
        with (
            patch.object(broker, "get_orders", side_effect=self.open_orders(untouched)),
            patch.object(broker, "cancel_order_by_id") as cancel,
        ):
            refresh(engine)
        cancel.assert_called_once_with("s1")

    def test_a_part_filled_profit_limit_is_sized_by_what_is_left(self) -> None:
        engine = movers_engine()
        limit = {"id": "t1", "symbol": "HOT", "side": "sell", "type": "limit", "qty": "10", "filled_qty": "4",
                 "limit_price": "1.30", "client_order_id": "apt-protect-tp-hot-1"}
        with patch.object(engine, "cancel_open_order", return_value=True) as cancel:
            self.assertFalse(engine.cancel_stale_protective_order(limit, D("6"), D("1.30"), D("0")))
            cancel.assert_not_called()
            self.assertTrue(engine.cancel_stale_protective_order(limit, D("5"), D("1.30"), D("0")))


class BuyCountTests(unittest.TestCase):
    # SQQQ 2026-11-13: bought at 09:00, 11:21 and 11:46 with the trend-hold limit at 2. By 11:21
    # the 09:00 buy was no longer among the newest 100 closed orders, so the count stayed at 1.
    def sqqq(self) -> list[dict[str, Any]]:
        return [filled("b1", "buy", "42.40", 170, symbol="SQQQ"), filled("s1", "sell", "42.10", 160, symbol="SQQQ"),
                filled("b2", "buy", "43.15", 40, symbol="SQQQ"), filled("s2", "sell", "42.90", 25, symbol="SQQQ")]

    def fund_hold(self, engine: TraderEngine) -> str:
        return engine.inverse_trend_entry_hold_reason("SQQQ", SimpleNamespace(), engine.config)

    def test_a_buy_that_scrolled_out_of_the_order_list_is_still_counted(self) -> None:
        orders = self.sqqq()
        broker = ClosedOrdersBroker(orders[:2])
        engine = movers_engine(broker, inverse_trend_hold=True, inverse_trend_max_entries=2)
        engine.sync_entries_today_from_orders(engine.with_todays_fills(broker, orders[:2]))
        self.assertEqual(engine.entries_today_by_symbol, {"SQQQ": 1})
        engine.sync_entries_today_from_orders(engine.with_todays_fills(broker, orders[2:]))   # the morning pair has scrolled out
        self.assertEqual(engine.entries_today_by_symbol, {"SQQQ": 2})
        self.assertEqual(self.fund_hold(engine), "Hold (trend hold: bought 2x today)")

    def test_after_a_restart_the_whole_session_is_read_back(self) -> None:
        orders = self.sqqq()
        for order in orders:
            order["submitted_at"] = order["filled_at"]
        broker = WindowBroker(orders, window=2)
        engine = movers_engine(broker, bars=150, inverse_trend_hold=True, inverse_trend_max_entries=2)
        refresh(engine)
        self.assertEqual(engine.entries_today_by_symbol.get("SQQQ"), 2)

    def test_the_whole_day_is_read_a_page_at_a_time(self) -> None:
        orders = round_trips(5)
        broker = WindowBroker(orders, window=2)
        engine = movers_engine(broker)
        with patch("alpaca_desktop.engine.DAY_FILLS_PAGE_SIZE", 4):
            merged = engine.with_todays_fills(broker, broker.get_orders(SimpleNamespace(status="closed")))
        self.assertEqual(sorted(order["id"] for order in merged), sorted(order["id"] for order in orders))
        self.assertEqual(len(merged), 10)   # nothing twice
        self.assertGreaterEqual(sum(1 for request in broker.closed_requests if getattr(request, "after", None)), 3)

    def test_a_failed_whole_day_read_is_tried_again_and_warned_about_once(self) -> None:
        orders = self.sqqq()
        broker = ClosedOrdersBroker(orders)
        engine = movers_engine(broker)
        with patch.object(engine, "read_todays_closed_orders", side_effect=RuntimeError("timeout")) as read:
            engine.with_todays_fills(broker, orders[2:])
            engine.with_todays_fills(broker, orders[2:])      # inside the minute: not asked again
            self.assertEqual(read.call_count, 1)
            engine.day_fills_retry_at = clock_module.monotonic() - 1
            engine.with_todays_fills(broker, orders[2:])
            self.assertEqual(read.call_count, 2)
        self.assertEqual(sum("Could not read the session's earlier orders" in entry["message"] for entry in engine.logs), 1)
        engine.day_fills_retry_at = clock_module.monotonic() - 1
        merged = engine.with_todays_fills(broker, orders[2:])
        self.assertEqual(len(merged), 4)
        self.assertTrue(engine.day_fills_loaded)

    def test_a_stop_placed_long_ago_that_fills_out_of_sight_is_picked_up(self) -> None:
        # Closed orders are listed by submission time. A stop placed in the morning that fills in
        # the afternoon, after 100 newer orders, never appears in the regular read.
        buy, stop_fill = filled("hot-buy", "buy", "11.40", 240), filled("hot-stop", "sell", "11.20", 5)
        buy["submitted_at"] = stop_fill["submitted_at"] = buy["filled_at"]            # both sent in the morning
        newer = round_trips(3, symbol="OTHER")
        broker = WindowBroker([buy] + newer, window=4)
        engine = movers_engine(broker, reentry_score_boost="20")
        resting = {"id": "hot-stop", "symbol": "HOT", "side": "sell", "type": "stop", "qty": "10"}
        window = broker.get_orders(SimpleNamespace(status="closed"))
        engine.with_todays_fills(broker, window, "", [resting])
        reads = len(broker.closed_requests)
        engine.with_todays_fills(broker, window, "", [resting])
        self.assertEqual(len(broker.closed_requests), reads)                           # nothing changed: no extra read
        broker.closed.append(stop_fill)                                                # it fills
        merged = engine.with_todays_fills(broker, broker.get_orders(SimpleNamespace(status="closed")), "", [])
        self.assertIn("hot-stop", {order["id"] for order in merged})
        engine.sync_loss_reentry_floors_from_closed_orders(merged)
        self.assertEqual(engine.movers_reentry_bar("HOT", engine.config), (D("80"), 1))
        reads = len(broker.closed_requests)
        engine.with_todays_fills(broker, window, "", [])
        self.assertEqual(len(broker.closed_requests), reads)                           # read once, not every pass

    def test_a_cancelled_order_that_drops_out_of_sight_costs_one_read(self) -> None:
        broker = WindowBroker(round_trips(3), window=2)
        engine = movers_engine(broker)
        window = broker.get_orders(SimpleNamespace(status="closed"))
        engine.with_todays_fills(broker, window, "", [{"id": "gone", "symbol": "HOT", "side": "sell", "type": "stop"}])
        before = len(broker.closed_requests)
        engine.with_todays_fills(broker, window, "", [])
        engine.with_todays_fills(broker, window, "", [])
        self.assertEqual(len(broker.closed_requests), before + 1)

    def test_the_last_session_is_kept_while_the_market_is_closed(self) -> None:
        orders = self.sqqq()
        broker = ClosedOrdersBroker(orders)
        engine = movers_engine(broker)
        session = datetime.now(MARKET_TIMEZONE).date()
        engine.with_todays_fills(broker, orders[:2], session.isoformat())
        self.assertEqual(len(engine.with_todays_fills(broker, orders[2:], session.isoformat())), 4)
        engine.with_todays_fills(broker, [], (session + timedelta(days=3)).isoformat())   # the next session starts empty
        self.assertEqual(engine.day_fills, {})

    def test_yesterdays_fills_are_not_kept(self) -> None:
        day_ago = 24 * 60
        old = [filled("b0", "buy", "42.40", day_ago + 30, symbol="SQQQ"), filled("s0", "sell", "42.10", day_ago, symbol="SQQQ")]
        broker = ClosedOrdersBroker(old)
        engine = movers_engine(broker)
        self.assertEqual(len(engine.with_todays_fills(broker, old)), 2)   # the regular list, nothing added
        self.assertEqual(engine.day_fills, {})


class TradeTableTests(unittest.TestCase):
    # 2026-11-13: the table's Realized P/L read -$5.71 against the broker's -$9.19 for the day,
    # because it was summed over the last 79 fills, and close-out sales read "Unknown".
    def test_realized_pl_is_summed_over_the_whole_day(self) -> None:
        orders = round_trips(60)                                   # 120 fills, $1.00 lost on each round trip
        engine = movers_engine()
        today = datetime.now(MARKET_TIMEZONE).date().isoformat()
        shown = engine.trade_history_rows(orders)
        self.assertEqual(len(shown), 100)
        every = engine.trade_history_rows(orders, limit=None)
        self.assertEqual(len(every), 120)
        self.assertEqual(engine.daily_realized_pl_summary(every, D("1000"), today)["value"], D("-60"))

    def test_refresh_reports_the_whole_day_when_the_broker_lists_only_the_newest_orders(self) -> None:
        broker = WindowBroker(round_trips(60), window=79)          # the oldest shown sale's buy is not in the window
        engine = movers_engine(broker, bars=150, reentry_score_boost="0")
        refresh(engine)
        self.assertEqual(D(engine.account["realized_pl_raw"]), D("-60"))
        self.assertEqual(len(engine.trade_history), 100)
        sells = [row for row in engine.trade_history if row["side"] == "sell"]
        self.assertTrue(sells)
        self.assertTrue(all(row["cost_basis_raw"] > 0 for row in sells))


class StaleWarningTests(unittest.TestCase):
    # After the 2026-11-13 restart the hold account and the day-trade account each logged about 24
    # "requiring stronger score before re-entry" warnings for sells from earlier days.
    losing = [filled("b1", "buy", "11.40", 30), filled("s1", "sell", "11.20", 25)]

    def test_day_trade_and_hold_accounts_do_not_use_the_score_floor(self) -> None:
        day = day_engine(Broker(), [pick("HOT")], {"HOT": "10.64"})
        hold_account = TraderEngine("hold")
        hold_account.config = AppConfig(entry_mode="allocation")
        for engine in (day, hold_account):
            with self.subTest(mode=engine.config.entry_mode):
                engine.sync_loss_reentry_floors_from_closed_orders(self.losing)
                self.assertEqual(engine.reentry_score_floors, {})
                self.assertEqual([entry for entry in engine.logs if "requiring stronger score" in entry["message"]], [])

    def test_the_momentum_score_floor_is_unchanged(self) -> None:
        engine = TraderEngine("momentum")
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"], reentry_score_boost="10")
        engine.sync_loss_reentry_floors_from_closed_orders(self.losing)
        self.assertIn("HOT", engine.reentry_score_floors)
        self.assertEqual(sum("HOT exit filled; requiring stronger score" in entry["message"] for entry in engine.logs), 1)


if __name__ == "__main__":
    unittest.main()
