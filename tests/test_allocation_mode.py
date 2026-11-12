"""Hold mode (entry_mode "allocation"): signal, check days, the plan, and the engine pass."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import allocation as A  # noqa: E402
from alpaca_desktop import engine as engine_module  # noqa: E402
from alpaca_desktop.engine import AppConfig, TraderEngine  # noqa: E402

D = Decimal
# Thursday 2026-11-12, 15:50 ET (20:50 UTC): ten minutes before the close, inside a 20-minute window.
THURSDAY_LATE = datetime(2026, 11, 12, 20, 50, tzinfo=timezone.utc)
FRIDAY_LATE = datetime(2026, 11, 13, 20, 50, tzinfo=timezone.utc)
SESSIONS = [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18),
            date(2026, 11, 19), date(2026, 11, 20)]


def holding(symbol: str, value: str, qty: str = "1") -> A.Holding:
    return A.Holding(symbol=symbol, qty=D(qty), market_value=D(value), qty_available=D(qty))


class SignalTests(unittest.TestCase):
    def test_average_includes_the_live_price(self) -> None:
        signal = A.allocation_signal([D("100")] * 199, D("120"), 200)
        self.assertEqual(signal.regime, "on")
        self.assertEqual(signal.average, D("100.1"))
        self.assertAlmostEqual(float(signal.gap_percent), 19.88, places=2)

    def test_below_the_average_is_risk_off(self) -> None:
        self.assertEqual(A.allocation_signal([D("100")] * 250, D("99"), 200).regime, "off")

    def test_not_enough_history_or_no_price_gives_no_signal(self) -> None:
        self.assertIsNone(A.allocation_signal([D("100")] * 198, D("101"), 200))
        self.assertIsNone(A.allocation_signal([D("100")] * 250, None, 200))
        self.assertIsNone(A.allocation_signal([D("100")] * 250, D("0"), 200))


class CheckDayTests(unittest.TestCase):
    def test_last_session_of_the_week_is_the_check_day(self) -> None:
        self.assertFalse(A.is_check_day(date(2026, 11, 12), SESSIONS, "weekly"))
        self.assertTrue(A.is_check_day(date(2026, 11, 13), SESSIONS, "weekly"))
        self.assertEqual(A.next_check_day(date(2026, 11, 12), SESSIONS, "weekly"), date(2026, 11, 13))

    def test_a_friday_holiday_moves_the_check_to_thursday(self) -> None:
        # Good Friday 2027-03-26 is closed.
        sessions = [date(2027, 3, 24), date(2027, 3, 25), date(2027, 3, 29)]
        self.assertTrue(A.is_check_day(date(2027, 3, 25), sessions, "weekly"))
        self.assertFalse(A.is_check_day(date(2027, 3, 24), sessions, "weekly"))

    def test_year_end_week_and_closed_days(self) -> None:
        sessions = [date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 4)]
        self.assertTrue(A.is_check_day(date(2026, 12, 31), sessions, "weekly"))
        self.assertFalse(A.is_check_day(date(2027, 1, 1), sessions, "weekly"))  # holiday, not a session

    def test_daily_checks_every_session_and_unknown_next_session_waits(self) -> None:
        self.assertTrue(A.is_check_day(date(2026, 11, 12), SESSIONS, "daily"))
        self.assertFalse(A.is_check_day(date(2026, 11, 20), SESSIONS, "weekly"))  # no later session listed


class PlanTests(unittest.TestCase):
    def test_empty_account_buys_each_target_at_its_weight(self) -> None:
        plan = A.plan_allocation([], ["QQQ", "SPY"], D("1000"), D("1000"), D("4000"), D("98"), D("10"), rebalance=False)
        self.assertEqual(plan.sells, [])
        self.assertEqual([(symbol, notional) for symbol, notional, _ in plan.buys], [("QQQ", D("490.00")), ("SPY", D("490.00"))])

    def test_holdings_outside_the_target_are_sold_with_no_buy_in_the_same_pass(self) -> None:
        held = [holding("IEF", "490", "5"), holding("GLD", "490", "2")]
        plan = A.plan_allocation(held, ["QQQ", "SPY"], D("1000"), D("20"), D("20"), D("98"), D("10"), rebalance=True)
        self.assertEqual(sorted((symbol, qty) for symbol, qty, _ in plan.sells), [("GLD", D("2")), ("IEF", D("5"))])
        self.assertEqual(plan.buys, [])

    def test_buys_never_use_margin_and_scale_to_cash(self) -> None:
        plan = A.plan_allocation([], ["QQQ", "SPY"], D("1000"), D("500"), D("4000"), D("98"), D("10"), rebalance=False)
        self.assertEqual(sum(notional for _, notional, _ in plan.buys), D("480.00"))  # 500 cash less the 20 reserve

    def test_negative_cash_waits(self) -> None:
        plan = A.plan_allocation([], ["QQQ", "SPY"], D("1000"), D("-5"), D("100"), D("98"), D("10"), rebalance=False)
        self.assertEqual(plan.buys, [])
        self.assertEqual(plan.note, "waiting for cash")

    def test_trims_only_on_a_check_day_or_switch(self) -> None:
        held = [holding("QQQ", "700", "1"), holding("SPY", "280", "1")]
        quiet = A.plan_allocation(held, ["QQQ", "SPY"], D("1000"), D("20"), D("20"), D("98"), D("10"), rebalance=False)
        self.assertEqual(quiet.sells, [])
        check = A.plan_allocation(held, ["QQQ", "SPY"], D("1000"), D("20"), D("20"), D("98"), D("10"), rebalance=True)
        self.assertEqual([symbol for symbol, _, _ in check.sells], ["QQQ"])
        self.assertAlmostEqual(float(check.sells[0][1]), 0.3, places=3)

    def test_small_drift_is_left_alone_and_tiny_buys_are_skipped(self) -> None:
        held = [holding("QQQ", "450"), holding("SPY", "530")]
        plan = A.plan_allocation(held, ["QQQ", "SPY"], D("1000"), D("20"), D("20"), D("98"), D("10"), rebalance=True)
        self.assertEqual((plan.sells, plan.buys), ([], []))
        held = [holding("QQQ", "489.50"), holding("SPY", "490")]
        plan = A.plan_allocation(held, ["QQQ", "SPY"], D("1000"), D("20.50"), D("20.50"), D("98"), D("0.01"), rebalance=False)
        self.assertEqual(plan.buys, [])  # 0.50 to buy is under the $1 minimum

    def test_held_regime(self) -> None:
        self.assertEqual(A.held_regime([], ["QQQ"], ["GLD"]), "none")
        self.assertEqual(A.held_regime([holding("QQQ", "1")], ["QQQ"], ["GLD"]), "on")
        self.assertEqual(A.held_regime([holding("GLD", "1")], ["QQQ"], ["GLD"]), "off")
        self.assertEqual(A.held_regime([holding("QQQ", "1"), holding("GLD", "1")], ["QQQ"], ["GLD"]), "mixed")
        self.assertEqual(A.held_regime([holding("AAPL", "1")], ["QQQ"], ["GLD"]), "none")  # outside symbols do not count
        self.assertEqual(A.held_regime([holding("AAPL", "1"), holding("QQQ", "1")], ["QQQ"], ["GLD"]), "on")


class ConfigTests(unittest.TestCase):
    def test_defaults_and_validation(self) -> None:
        config = AppConfig(entry_mode="allocation")
        self.assertEqual((config.allocation_risk_on_symbols, config.allocation_risk_off_symbols), (["QQQ", "SPY"], ["IEF", "GLD"]))
        self.assertEqual(AppConfig(allocation_risk_on_symbols="qqq spy,QQQ").allocation_risk_on_symbols, ["QQQ", "SPY"])
        for bad in ({"allocation_risk_off_symbols": ["QQQ"]}, {"allocation_risk_on_symbols": []}, {"allocation_check": "monthly"},
                    {"allocation_signal_symbol": "QQQ SPY"}, {"entry_mode": "buy-everything"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                AppConfig(**bad)
        clamped = AppConfig(allocation_sma_days=5, allocation_invest_percent="150", allocation_trade_minutes_before_close=1)
        self.assertEqual((clamped.allocation_sma_days, clamped.allocation_invest_percent, clamped.allocation_trade_minutes_before_close), (20, D("100"), 5))


class FakeClient:
    def __init__(self, now: datetime, *, positions: list[dict[str, Any]] | None = None, cash: str = "1000",
                 open_orders: list[dict[str, Any]] | None = None, closed_orders: list[dict[str, Any]] | None = None) -> None:
        self.now = now
        self.positions = list(positions or [])
        self.cash = cash
        self.open_orders = list(open_orders or [])
        self.closed_orders = list(closed_orders or [])
        self.submitted: list[Any] = []
        self.cancelled: list[str] = []

    def get_account(self) -> dict[str, Any]:
        return {"equity": "1000", "last_equity": "1000", "cash": self.cash, "buying_power": "4000"}

    def get_clock(self) -> Any:
        close = self.now.replace(hour=21, minute=0)
        return SimpleNamespace(is_open=True, timestamp=self.now, next_close=close, next_open=close + timedelta(hours=17, minutes=30))

    def get_all_positions(self) -> list[dict[str, Any]]:
        return list(self.positions)

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        return list(self.open_orders) if "open" in str(getattr(request, "status", "")).lower() else list(self.closed_orders)

    def get_calendar(self, request: Any) -> list[Any]:
        return [SimpleNamespace(date=day) for day in SESSIONS]

    def submit_order(self, order: Any) -> Any:
        self.submitted.append(order)
        return SimpleNamespace(id=f"o{len(self.submitted)}", client_order_id=order.client_order_id)

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)


class FakeData:
    def __init__(self, close: str = "100") -> None:
        self.close = close
        self.requests: list[Any] = []

    def get_stock_bars(self, request: Any) -> Any:
        if not isinstance(request.symbol_or_symbols, str):
            return SimpleNamespace(data={})  # the minute-bar refresh for symbols the test did not pre-load
        self.requests.append(request)
        start = date(2026, 11, 11)
        bars = [SimpleNamespace(timestamp=datetime.combine(start - timedelta(days=i), datetime.min.time(), timezone.utc) + timedelta(hours=5),
                                close=float(self.close)) for i in range(260, -1, -1)]
        return SimpleNamespace(data={request.symbol_or_symbols: bars})


def position(symbol: str, qty: str, price: str) -> dict[str, Any]:
    return {"symbol": symbol, "qty": qty, "qty_available": qty, "avg_entry_price": price, "current_price": price,
            "market_value": str(D(qty) * D(price)), "side": "long"}


def hold_engine(client: FakeClient, prices: dict[str, str], **config: Any) -> TraderEngine:
    engine = TraderEngine("hold")
    engine.config = AppConfig(entry_mode="allocation", use_top_volume_symbols=False, symbols=["SPY"], dry_run=False,
                              flatten_before_close_minutes=10, flatten_on_daily_loss=True, **config)
    engine.connected = True
    engine.trading_enabled = True
    engine.trading_client = client  # type: ignore[assignment]
    engine.data_client = FakeData()  # type: ignore[assignment]
    for symbol, price in prices.items():
        engine.strategy_state.add_bar(symbol, price, client.now - timedelta(minutes=1))
    return engine


def refresh(engine: TraderEngine) -> None:
    with (
        patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
        patch.object(engine, "record_day_tape_scan"),
        patch.object(engine, "record_day_tape_bars"),
        patch.object(engine, "current_trade_price", side_effect=lambda symbol, fallback: fallback),
    ):
        engine.refresh(run_strategy=True, shared_bars={symbol: [] for symbol in ("QQQ", "SPY", "IEF", "GLD")})


PRICES_UP = {"QQQ": "110", "SPY": "500", "IEF": "95", "GLD": "250"}
PRICES_DOWN = {"QQQ": "90", "SPY": "500", "IEF": "95", "GLD": "250"}


class EnginePassTests(unittest.TestCase):
    def test_empty_account_funds_risk_on_in_the_window_even_off_a_check_day(self) -> None:
        client = FakeClient(THURSDAY_LATE)
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        bought = [(order.symbol, order.side.value, order.client_order_id.split("-")[:4]) for order in client.submitted]
        self.assertEqual(bought, [("QQQ", "buy", ["apt", "entry", "alloc", "on"]), ("SPY", "buy", ["apt", "entry", "alloc", "on"])])
        self.assertAlmostEqual(float(client.submitted[0].qty), 490 / 110, places=3)
        self.assertIn("Hold mode risk-on", engine.status)
        self.assertIn("Next check Fri Nov 13", engine.status)

    def test_open_orders_block_a_second_wave(self) -> None:
        client = FakeClient(THURSDAY_LATE)
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        client.open_orders = [{"id": "o1", "symbol": "QQQ", "side": "buy", "type": "market", "qty": "4.4",
                               "client_order_id": client.submitted[0].client_order_id}]
        engine.order_submit_holds.clear()  # the open order alone must block, not just the submit hold
        refresh(engine)
        self.assertEqual(len(client.submitted), 2)
        self.assertIn("waiting for 1 open order", engine.allocation_view["detail"])

    def test_check_day_switch_sells_first_and_buys_nothing_yet(self) -> None:
        client = FakeClient(FRIDAY_LATE, cash="20", positions=[position("IEF", "5.1579", "95"), position("GLD", "1.96", "250")])
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(sorted((order.symbol, order.side.value) for order in client.submitted), [("GLD", "sell"), ("IEF", "sell")])
        self.assertTrue(all(order.client_order_id.startswith("apt-exit-alloc-on-") for order in client.submitted))

    def test_off_a_check_day_a_valid_portfolio_is_left_alone_even_against_the_signal(self) -> None:
        client = FakeClient(THURSDAY_LATE, cash="20", positions=[position("IEF", "5.1579", "95"), position("GLD", "1.96", "250")])
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(client.submitted, [])
        self.assertIn("on target", engine.allocation_view.get("detail", ""))

    def test_outside_the_window_nothing_trades(self) -> None:
        client = FakeClient(THURSDAY_LATE - timedelta(hours=2))
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(client.submitted, [])

    def test_restart_keeps_the_decision_already_made_today(self) -> None:
        # Earlier today the account sold for a switch to risk-off; the price has since crossed back over.
        sold = {"id": "x1", "symbol": "QQQ", "side": "sell", "type": "market", "status": "filled",
                "client_order_id": "apt-exit-alloc-off-qqq-1", "submitted_at": "2026-11-13T20:42:00Z"}
        client = FakeClient(FRIDAY_LATE, closed_orders=[sold])
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(sorted(order.symbol for order in client.submitted), ["GLD", "IEF"])

    def test_leftover_momentum_stops_are_cancelled_before_trading(self) -> None:
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "1", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeClient(THURSDAY_LATE, open_orders=[stop], positions=[position("AAA", "1", "10")])
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(client.submitted, [])

    def test_hold_mode_skips_stops_flatten_and_the_entry_loop(self) -> None:
        client = FakeClient(FRIDAY_LATE, cash="20", positions=[position("QQQ", "4.4545", "110"), position("SPY", "0.98", "500")])
        engine = hold_engine(client, PRICES_UP)
        with (
            patch.object(engine, "entry_candidate") as candidate,
            patch.object(engine, "ensure_position_exit_orders") as stops,
            patch.object(engine, "flatten_all_positions") as flatten,
        ):
            refresh(engine)
        candidate.assert_not_called()
        stops.assert_not_called()
        flatten.assert_not_called()
        self.assertEqual(client.submitted, [])

    def test_closes_come_from_consolidated_data_ending_16_minutes_back(self) -> None:
        client = FakeClient(THURSDAY_LATE)
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        refresh(engine)
        requests = engine.data_client.requests  # type: ignore[attr-defined]
        self.assertEqual(len(requests), 1)  # cached for the day
        self.assertEqual(str(requests[0].feed.value).lower(), "sip")
        end = requests[0].end if requests[0].end.tzinfo else requests[0].end.replace(tzinfo=timezone.utc)
        self.assertLessEqual(end, datetime.now(timezone.utc) - timedelta(minutes=15))

    def test_a_failed_signal_on_the_check_day_does_not_lock_in_holding(self) -> None:
        client = FakeClient(FRIDAY_LATE, cash="20", positions=[position("QQQ", "4.4545", "110"), position("SPY", "0.98", "500")])
        engine = hold_engine(client, PRICES_DOWN)
        with patch.object(engine, "allocation_previous_closes", return_value=None):
            refresh(engine)  # closes request failed: no signal yet
        self.assertEqual(client.submitted, [])
        self.assertIsNone(engine.allocation_latch)
        refresh(engine)  # the signal is back: QQQ is below its average on a check day
        self.assertEqual(sorted((order.symbol, order.side.value) for order in client.submitted), [("QQQ", "sell"), ("SPY", "sell")])

    def test_a_stray_holding_cannot_switch_the_portfolio_mid_week(self) -> None:
        client = FakeClient(THURSDAY_LATE, cash="20",
                            positions=[position("QQQ", "4.4545", "110"), position("SPY", "0.98", "500"), position("AAPL", "0.01", "200")])
        engine = hold_engine(client, PRICES_DOWN)
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in client.submitted], [("AAPL", "sell")])

    def test_one_held_symbol_does_not_block_the_rest_of_the_wave(self) -> None:
        client = FakeClient(FRIDAY_LATE, cash="20", positions=[position("IEF", "5.1579", "95"), position("GLD", "1.96", "250")])
        engine = hold_engine(client, PRICES_UP)
        engine.hold_rejected_order("GLD", engine_module.OrderSide.SELL, 1800)
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in client.submitted], [("IEF", "sell")])

    def test_a_dead_placeholder_with_no_price_does_not_block_funding(self) -> None:
        # Nov 12: Account 2 held only a CVR placeholder that Alpaca reports with no price at all. It
        # was treated as a holding to sell, the sell was rejected, and QQQ/SPY were never bought.
        cvr = {"symbol": "046CVR015", "qty": "3.5107", "qty_available": "3.5107", "avg_entry_price": "0.37",
               "current_price": None, "market_value": None, "side": "long"}
        client = FakeClient(THURSDAY_LATE, positions=[cvr], cash="996.51")
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in client.submitted], [("QQQ", "buy"), ("SPY", "buy")])

    def test_a_holding_whose_sell_was_rejected_does_not_block_the_buys(self) -> None:
        client = FakeClient(THURSDAY_LATE, positions=[position("XYZ", "1", "5")], cash="995")
        engine = hold_engine(client, PRICES_UP)
        engine.hold_rejected_order("XYZ", engine_module.OrderSide.SELL, 1800)
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in client.submitted], [("QQQ", "buy"), ("SPY", "buy")])
        # Without a rejection the stray holding is still sold first, as before.
        client = FakeClient(THURSDAY_LATE, positions=[position("XYZ", "1", "5")], cash="995")
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual([(order.symbol, order.side.value) for order in client.submitted], [("XYZ", "sell")])

    def test_a_manual_order_on_another_symbol_does_not_block(self) -> None:
        manual = {"id": "m1", "symbol": "TSLA", "side": "buy", "type": "limit", "qty": "1", "client_order_id": "my-own-order"}
        client = FakeClient(THURSDAY_LATE, open_orders=[manual])
        engine = hold_engine(client, PRICES_UP)
        refresh(engine)
        self.assertEqual(sorted(order.symbol for order in client.submitted), ["QQQ", "SPY"])

    def test_momentum_mode_never_runs_the_hold_pass(self) -> None:
        client = FakeClient(THURSDAY_LATE)
        engine = hold_engine(client, PRICES_UP)
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["SPY"], dry_run=False)
        with patch.object(engine, "run_allocation_pass") as hold_pass:
            refresh(engine)
        hold_pass.assert_not_called()

    def test_scan_symbols_by_mode(self) -> None:
        engine = hold_engine(FakeClient(THURSDAY_LATE), PRICES_UP)
        self.assertEqual(engine.scan_symbols({"046CVR015"}), ["QQQ", "SPY", "IEF", "GLD", "046CVR015"])


if __name__ == "__main__":
    unittest.main()
