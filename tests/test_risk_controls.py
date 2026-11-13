from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from alpaca.common.exceptions import APIError
from alpaca.trading.enums import OrderSide

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AppConfig, TraderEngine


NOW = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)


class FakeTradingClient:
    """Minimal Alpaca TradingClient stand-in: one long AAA position, configurable orders/clock."""

    def __init__(
        self, *, is_open: bool, price: str = "100", orders: list[dict[str, Any]] | None = None, entry: str = "100"
    ) -> None:
        self.is_open = is_open
        self.price = price
        self.entry = entry
        self.open_orders = list(orders or [])
        self.submitted: list[Any] = []
        self.cancelled: list[str] = []
        self.equity = "1000"
        self.last_equity = "1000"
        self.closed_orders: list[dict[str, Any]] = []

    def get_account(self) -> dict[str, Any]:
        return {"equity": self.equity, "last_equity": self.last_equity, "buying_power": "1000", "cash": "1000"}

    def get_clock(self) -> Any:
        return SimpleNamespace(
            is_open=self.is_open,
            timestamp=NOW,
            next_open=NOW + timedelta(hours=14),
            next_close=NOW + timedelta(hours=2),
        )

    def get_all_positions(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "AAA",
                "qty": "0.25",
                "avg_entry_price": self.entry,
                "current_price": self.price,
                "market_value": str(Decimal(self.price) * Decimal("0.25")),
                "unrealized_pl": "0",
                "side": "long",
            }
        ]

    def get_open_position(self, symbol: str) -> dict[str, Any]:
        return next(position for position in self.get_all_positions() if position["symbol"] == symbol)

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        status = str(getattr(request, "status", "")).lower()
        return list(self.open_orders) if "open" in status else list(self.closed_orders)

    def submit_order(self, order: Any) -> Any:
        self.submitted.append(order)
        return SimpleNamespace(id=f"order-{len(self.submitted)}", client_order_id=getattr(order, "client_order_id", ""))

    def cancel_order_by_id(self, order_id: str) -> None:
        self.cancelled.append(order_id)
        self.open_orders = [order for order in self.open_orders if order.get("id") != order_id]


def connected_engine(client: FakeTradingClient, **config: Any) -> TraderEngine:
    engine = TraderEngine("risk")
    engine.config = AppConfig(
        symbols=["AAA"],
        use_top_volume_symbols=False,
        dry_run=config.pop("dry_run", False),
        stop_loss_percent="1.25",
        take_profit_percent="2.5",
        **config,
    )
    engine.connected = True
    engine.trading_client = client  # type: ignore[assignment]
    engine.data_client = object()  # type: ignore[assignment]
    engine.strategy_state.add_bar("AAA", client.price, NOW - timedelta(minutes=1))
    return engine


def run_refresh(engine: TraderEngine, run_strategy: bool = False) -> None:
    with (
        patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
        patch.object(engine, "record_day_tape_scan"),
        patch.object(engine, "record_day_tape_bars"),
    ):
        engine.refresh(run_strategy=run_strategy, shared_bars={"AAA": []})


def kinds(client: FakeTradingClient) -> list[tuple[str, str]]:
    return [(str(order.side.value), str(order.type.value)) for order in client.submitted]


class StopProtectionTests(unittest.TestCase):
    def test_stopped_trading_still_places_stop_during_market_hours(self) -> None:
        client = FakeTradingClient(is_open=True)
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(kinds(client), [("sell", "stop")])

    def test_market_closed_queues_stop_and_never_sells(self) -> None:
        client = FakeTradingClient(is_open=False)
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(client.submitted[0].time_in_force.value, "day")

        below_stop = FakeTradingClient(is_open=False, price="95")
        engine = connected_engine(below_stop)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(below_stop.submitted, [])
        self.assertIn("exits at the open", engine.strategy_state.last_action["AAA"])

    def test_existing_stop_is_not_duplicated_off_hours(self) -> None:
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25",
                "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeTradingClient(is_open=False, orders=[stop])
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(client.submitted, [])
        self.assertEqual(client.cancelled, [])

    def test_partly_filled_entry_waits_to_place_the_stop_for_the_full_quantity(self) -> None:
        # Alpaca rejects a sell stop beside the still-open buy as a potential wash trade (STLA, SQQQ 2026-11-06).
        entry = {"id": "b1", "symbol": "AAA", "side": "buy", "type": "market", "qty": "0.5",
                 "status": "partially_filled", "client_order_id": "apt-entry-aaa-1"}
        for is_open, price in ((True, "100"), (True, "95"), (False, "100")):
            with self.subTest(is_open=is_open, price=price):
                client = FakeTradingClient(is_open=is_open, price=price, orders=[entry])
                engine = connected_engine(client)
                run_refresh(engine, run_strategy=is_open)
                self.assertEqual(client.submitted, [])
                self.assertEqual(client.cancelled, [])
                self.assertEqual(engine.strategy_state.last_action["AAA"], "Hold (entry still filling)")

        client = FakeTradingClient(is_open=True, orders=[entry])
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=True)
        client.open_orders = []  # the buy finished filling
        run_refresh(engine, run_strategy=True)
        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(client.submitted[0].qty, 0.25)

    def test_backup_sell_uses_only_the_shares_alpaca_has_available(self) -> None:
        # U on 2026-11-06: the broker stop was filling in pieces, the app saw "stop missing" and sold the
        # full position; Alpaca rejected it (requested 32.7446, available 12.7446).
        engine = connected_engine(FakeTradingClient(is_open=True, price="95"))
        position = {"symbol": "AAA", "qty": "32.7446", "qty_available": "12.7446", "avg_entry_price": "100",
                    "current_price": "95"}
        snapshot = engine.snapshot("AAA")
        with patch.object(engine, "submit_exit_order", return_value=[]) as sell:
            events, exit_submitted, protection_active, placed = engine.ensure_position_exit_orders("AAA", position, snapshot, [])
        self.assertTrue(exit_submitted)
        self.assertEqual(sell.call_args.args[1], Decimal("12.7446"))

        position["qty_available"] = "0"
        with patch.object(engine, "submit_exit_order", return_value=[]) as sell:
            events, exit_submitted, protection_active, placed = engine.ensure_position_exit_orders("AAA", position, snapshot, [])
        self.assertFalse(exit_submitted)
        self.assertEqual(sell.call_count, 0)
        self.assertEqual(engine.strategy_state.last_action["AAA"], "Hold (shares held by a working order)")

        del position["qty_available"]  # replay positions: sell the whole quantity
        self.assertEqual(engine.sellable_qty(position), Decimal("32.7446"))

    def test_mrln_crossed_stop_exits_in_the_same_pass_at_broker_available_quantity(self) -> None:
        for remaining in ("0.14", "0"):
            with self.subTest(remaining=remaining):
                client = FakeTradingClient(is_open=True, entry="1.36", price="1.3583")
                engine = connected_engine(client)
                original_submit = client.submit_order
                attempts = []

                def submit(order: Any) -> Any:
                    attempts.append(order)
                    if order.type.value == "stop":
                        raise APIError(
                            '{"code":42210000,"market_price":"1.34",'
                            '"message":"stop price must be less than current price","stop_price":"1.34"}'
                        )
                    return original_submit(order)

                client.submit_order = submit
                client.get_open_position = lambda symbol: client.get_all_positions()[0] | {"qty_available": remaining}
                run_refresh(engine)

                self.assertEqual(attempts[0].stop_price, 1.34)
                self.assertEqual(kinds(client), [("sell", "market")] if remaining != "0" else [])
                if remaining != "0":
                    self.assertEqual(client.submitted[0].qty, 0.14)
                    self.assertIn("broker confirmed stop crossed", engine.order_intents[-1]["reason"])
                self.assertFalse(engine.protective_order_blocked("AAA", "stop_loss"))

    def test_crossed_stop_rechecks_for_an_order_that_appeared_after_the_scan(self) -> None:
        client = FakeTradingClient(is_open=True, entry="1.36", price="1.3583")
        engine = connected_engine(client)
        attempts = []

        def reject(order: Any) -> Any:
            attempts.append(order.type.value)
            client.open_orders.append({"symbol": "AAA", "type": "market", "side": "sell"})
            raise APIError(
                '{"code":42210000,"market_price":"1.34",'
                '"message":"stop price must be less than current price","stop_price":"1.34"}'
            )

        client.submit_order = reject
        run_refresh(engine)
        self.assertEqual(attempts, ["stop"])

    def test_offhours_or_other_stop_rejections_keep_their_retry_hold(self) -> None:
        for is_open, error in (
            (False, '{"code":42210000,"market_price":"1.34",'
                    '"message":"stop price must be less than current price","stop_price":"1.34"}'),
            (True, '{"code":42210000,"message":"insufficient qty available"}'),
        ):
            with self.subTest(is_open=is_open):
                client = FakeTradingClient(is_open=is_open, entry="1.36", price="1.3583")
                engine = connected_engine(client)
                clock = client.get_clock()
                clock.next_open = datetime.now(timezone.utc) + timedelta(hours=1)
                client.get_clock = lambda: clock
                attempts = []

                def reject(order: Any) -> Any:
                    attempts.append(order.type.value)
                    raise APIError(error)

                client.submit_order = reject
                run_refresh(engine)
                run_refresh(engine)
                self.assertEqual(attempts, ["stop"])
                self.assertTrue(engine.protective_order_blocked("AAA", "stop_loss"))

    def test_mrln_trail_uses_the_new_positions_peak_without_the_prior_positions_hold(self) -> None:
        client = FakeTradingClient(is_open=True, entry="1.35", price="1.3799")
        engine = connected_engine(client, profit_trail_start_percent="2", profit_trail_drop_percent="1")
        engine.hold_rejected_protective_order("AAA", "stop_loss")
        engine.hold_submitted_order("AAA", OrderSide.SELL)
        engine.hold_rejected_order("AAA", OrderSide.SELL, 60)
        engine.hold_rejected_order("AAA", OrderSide.BUY, 60)
        engine.prune_position_trackers(set())  # the broker reported the previous position flat
        self.assertFalse(engine.order_hold_reason("AAA", OrderSide.SELL))
        self.assertTrue(engine.order_hold_reason("AAA", OrderSide.BUY))

        run_refresh(engine)

        self.assertEqual(kinds(client), [("sell", "stop")])
        self.assertEqual(client.submitted[0].stop_price, 1.36)  # 1% under $1.3799, rounded down
        self.assertEqual(engine.position_stop_price("AAA", Decimal("1.35"), Decimal("1.36"), engine.config), Decimal("1.36"))

    def test_dry_run_account_that_is_stopped_sends_nothing(self) -> None:
        client = FakeTradingClient(is_open=True)
        engine = connected_engine(client, dry_run=True)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(client.submitted, [])

    def test_unfilled_take_profit_falls_back_to_stop_loss_sell(self) -> None:
        take_profit = {"id": "tp1", "symbol": "AAA", "side": "sell", "type": "limit", "qty": "0.25",
                       "limit_price": "102.5", "client_order_id": "apt-exit-limit-aaa-1"}
        client = FakeTradingClient(is_open=True, price="98", orders=[take_profit])
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(client.cancelled, ["tp1"])
        self.assertEqual(kinds(client), [("sell", "market")])

    def test_take_profit_fallback_does_not_sell_if_cancel_fails(self) -> None:
        take_profit = {"id": "tp1", "symbol": "AAA", "side": "sell", "type": "limit", "qty": "0.25",
                       "limit_price": "102.5", "client_order_id": "apt-exit-limit-aaa-1"}
        client = FakeTradingClient(is_open=True, price="98", orders=[take_profit])

        def refuse(order_id: str) -> None:
            raise RuntimeError("order is not cancelable")

        client.cancel_order_by_id = refuse  # type: ignore[method-assign]
        engine = connected_engine(client)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(client.submitted, [])

    def test_rejected_stop_loss_sell_waits_before_retrying(self) -> None:
        client = FakeTradingClient(is_open=True, price="95")
        attempts: list[Any] = []

        def reject(order: Any) -> Any:
            attempts.append(order)
            raise RuntimeError("insufficient qty available")

        client.submit_order = reject  # type: ignore[method-assign]
        engine = connected_engine(client)
        with patch.object(engine, "entry_open_guard_message", return_value=""):
            for _ in range(3):
                run_refresh(engine, run_strategy=False)
        self.assertEqual(len(attempts), 1)
        self.assertIn("blocked", engine.strategy_state.last_action["AAA"])

    def test_flatten_cancels_a_resting_take_profit_and_sells(self) -> None:
        take_profit = {"id": "tp1", "symbol": "AAA", "side": "sell", "type": "limit", "qty": "0.25",
                       "limit_price": "102.5", "client_order_id": "apt-exit-limit-aaa-1"}
        client = FakeTradingClient(is_open=True, orders=[take_profit])
        client.equity = "970"
        engine = connected_engine(client, daily_loss_limit="20", flatten_on_daily_loss=True)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(client.cancelled, ["tp1"])
        self.assertEqual(kinds(client), [("sell", "market")])

    def test_rejected_flatten_sell_restores_the_stop_next_pass(self) -> None:
        client = FakeTradingClient(is_open=True)
        client.equity = "970"
        original_submit = client.submit_order

        def reject_market(order: Any) -> Any:
            if order.type.value == "market":
                raise RuntimeError("market sell rejected")
            return original_submit(order)

        client.submit_order = reject_market  # type: ignore[method-assign]
        engine = connected_engine(client, daily_loss_limit="20", flatten_on_daily_loss=True)
        run_refresh(engine, run_strategy=False)  # flatten attempt rejected -> 60 s sell hold
        run_refresh(engine, run_strategy=False)  # held: normal pass puts the stop back
        self.assertEqual(kinds(client), [("sell", "stop")])

    def test_new_stop_and_local_take_profit_never_collide_in_one_pass(self) -> None:
        # Gain is past 2.5% but the price is below the rounded-up take-profit price (102.52), so the
        # first pass places the stop and must stop there instead of also sending a sell.
        client = FakeTradingClient(is_open=True, price="102.515", entry="100.01")
        engine = connected_engine(client)
        with patch.object(engine, "entry_open_guard_message", return_value=""):
            run_refresh(engine, run_strategy=False)
        self.assertEqual(kinds(client), [("sell", "stop")])

    def test_sell_before_close_sells_inside_the_window_only(self) -> None:
        client = FakeTradingClient(is_open=True)  # fake clock: close is 2 hours away
        engine = connected_engine(client, flatten_before_close_minutes=180)
        engine.trading_enabled = True
        run_refresh(engine, run_strategy=True)
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertIn("Selling before the close", engine.status)

        outside = FakeTradingClient(is_open=True)
        engine = connected_engine(outside, flatten_before_close_minutes=30)
        run_refresh(engine, run_strategy=False)
        self.assertEqual(kinds(outside), [("sell", "stop")])

    def test_sell_before_close_in_dry_run_sends_nothing(self) -> None:
        client = FakeTradingClient(is_open=True)
        engine = connected_engine(client, flatten_before_close_minutes=180, dry_run=True)
        engine.trading_enabled = True
        run_refresh(engine, run_strategy=True)
        self.assertEqual(client.submitted, [])

    def test_flatten_sells_the_shares_its_own_stop_was_holding(self) -> None:
        # 2026-11-09 close: every Account A position had a live app stop holding all its shares, so
        # Alpaca reported qty_available 0 and the sell-before-close pass skipped all of them.
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25", "filled_qty": "0",
                "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeTradingClient(is_open=True, orders=[stop])
        engine = connected_engine(client)
        position = {"symbol": "AAA", "qty": "0.25", "qty_available": "0", "side": "long",
                    "current_price": "100", "avg_entry_price": "100"}
        events, handled = engine.flatten_all_positions({"AAA": position}, [stop], "flatten before close")
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "0.25")
        self.assertEqual(handled, {"AAA"})

    def test_flatten_leaves_shares_held_by_a_manual_order(self) -> None:
        manual = {"id": "m1", "symbol": "AAA", "side": "sell", "type": "limit", "qty": "0.25",
                  "limit_price": "150", "client_order_id": "my-own-order"}
        client = FakeTradingClient(is_open=True, orders=[manual])
        engine = connected_engine(client)
        position = {"symbol": "AAA", "qty": "0.25", "qty_available": "0", "side": "long",
                    "current_price": "100", "avg_entry_price": "100"}
        events, handled = engine.flatten_all_positions({"AAA": position}, [manual], "flatten before close")
        self.assertEqual(client.cancelled, [])
        self.assertEqual(client.submitted, [])
        self.assertEqual(handled, {"AAA"})

    def test_flatten_sells_only_the_part_a_filling_stop_released(self) -> None:
        # Like U on 2026-11-06: the stop is filling in pieces (20 shares still working), the position
        # already reflects the fills and Alpaca reports only the unheld 12.7446 as available.
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "110.7446", "filled_qty": "90.7446",
                "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeTradingClient(is_open=True, orders=[stop])
        engine = connected_engine(client)
        client.get_open_position = lambda symbol: {"symbol": symbol, "qty": "32.7446", "qty_available": "32.7446"}
        position = {"symbol": "AAA", "qty": "32.7446", "qty_available": "12.7446", "side": "long",
                    "current_price": "100", "avg_entry_price": "100"}
        engine.flatten_all_positions({"AAA": position}, [stop], "flatten before close")
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "32.7446")

    def test_close_sells_only_broker_quantity_after_stop_partially_fills_during_cancel(self) -> None:
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25",
                "filled_qty": "0", "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeTradingClient(is_open=True, orders=[stop])
        engine = connected_engine(client, flatten_before_close_minutes=180)

        def remaining_position(symbol: str) -> dict[str, Any]:
            self.assertEqual(client.open_orders, [])
            return {"symbol": symbol, "qty": "0.15", "qty_available": "0.15"}

        client.get_open_position = remaining_position
        run_refresh(engine)
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(kinds(client), [("sell", "market")])
        self.assertEqual(str(client.submitted[0].qty), "0.15")

    def test_close_waits_for_broker_quantity_when_position_lookup_fails_after_cancel(self) -> None:
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25",
                "filled_qty": "0", "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        client = FakeTradingClient(is_open=True, orders=[stop])
        engine = connected_engine(client, flatten_before_close_minutes=180)
        with patch.object(client, "get_open_position", side_effect=OSError("broker unavailable")):
            run_refresh(engine)
        self.assertEqual(client.cancelled, ["s1"])
        self.assertEqual(client.submitted, [])
        run_refresh(engine)
        self.assertEqual(kinds(client), [("sell", "market")])

    def test_halted_refresh_leaves_working_stop_untouched(self) -> None:
        stop = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25",
                "filled_qty": "0", "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}
        for flatten_minutes in (0, 180):
            with self.subTest(flatten_minutes=flatten_minutes):
                client = FakeTradingClient(is_open=True, price="103", orders=[stop])
                engine = connected_engine(client, flatten_before_close_minutes=flatten_minutes)
                with patch.object(engine_module, "trading_halted", return_value=True):
                    run_refresh(engine, run_strategy=True)
                self.assertEqual(client.cancelled, [])
                self.assertEqual(client.submitted, [])
                self.assertEqual(client.open_orders, [stop])
                self.assertIn("paused by n8n", engine.state()["status"])

    def test_flatten_never_sells_a_short_position(self) -> None:
        client = FakeTradingClient(is_open=True)
        engine = connected_engine(client)
        short = {"symbol": "AAA", "qty": "-1", "side": "short", "current_price": "100", "avg_entry_price": "100"}
        events, handled = engine.flatten_all_positions({"AAA": short}, [], "flatten before close")
        self.assertEqual(client.submitted, [])
        self.assertEqual(handled, set())

    def test_flatten_window_setting_is_clamped(self) -> None:
        self.assertEqual(AppConfig(symbols=["SPY"], flatten_before_close_minutes=1).flatten_before_close_minutes, 2)
        self.assertEqual(AppConfig(symbols=["SPY"], flatten_before_close_minutes=999).flatten_before_close_minutes, 390)
        self.assertEqual(AppConfig(symbols=["SPY"]).flatten_before_close_minutes, 0)

    def test_purge_orders_count_as_app_exits(self) -> None:
        engine = TraderEngine("roles")
        role = engine.order_role({"symbol": "AAA", "side": "sell", "client_order_id": "apt-purge-aaa-1"}, {"AAA"})
        self.assertEqual(role, "Strategy Exit")

    def test_zero_price_position_is_labelled_untradable(self) -> None:
        engine = TraderEngine("labels")
        engine.config = AppConfig(symbols=["AAA"], dry_run=False)
        rows = engine.protection_status_rows([{"symbol": "046CVR015", "qty": "2.8", "current_price": "0"}], [])
        self.assertEqual(rows[0]["status"], "No market price")

    def test_placeholder_position_does_not_use_a_position_slot(self) -> None:
        client = FakeTradingClient(is_open=True)
        cvr = {"symbol": "046CVR015", "qty": "3.05", "avg_entry_price": "0.37", "current_price": "0", "market_value": "0", "side": "long"}
        client.get_all_positions = lambda: [*FakeTradingClient.get_all_positions(client), cvr]  # type: ignore[method-assign]
        engine = connected_engine(client, max_open_positions=2)
        engine.config = engine.config.model_copy(update={"symbols": ["AAA", "BBB"]})
        engine.strategy_state.add_bar("BBB", "50", NOW - timedelta(minutes=1))
        engine.trading_enabled = True
        with (
            patch.object(engine, "entry_open_guard_message", return_value=""),
            patch.object(engine, "entry_close_guard_message", return_value=""),
            patch.object(engine, "entry_candidate", return_value=None) as candidate,
            patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
            patch.object(engine, "record_day_tape_scan"),
            patch.object(engine, "record_day_tape_bars"),
        ):
            engine.refresh(run_strategy=True, shared_bars={"AAA": [], "BBB": [], "046CVR015": []})
        bbb_calls = [call for call in candidate.call_args_list if call.args[0] == "BBB"]
        self.assertEqual(bbb_calls[0].args[4], 1)  # only AAA counts toward max_open_positions
        self.assertTrue(engine_module.is_placeholder_position(cvr))
        self.assertFalse(engine_module.is_placeholder_position({"symbol": "AAA", "qty": "1"}))  # no price reported yet
        # Alpaca reports some placeholders with no price at all (Account 2, Nov 12).
        self.assertTrue(engine_module.is_placeholder_position({"symbol": "046CVR015", "qty": "3.5", "current_price": None}))
        self.assertFalse(engine_module.is_placeholder_position({"symbol": "AAA", "qty": "1", "current_price": None}))


class DailyLossLimitTests(unittest.TestCase):
    def test_limit_settings_are_no_longer_forced_off(self) -> None:
        config = AppConfig(symbols=["SPY"], daily_loss_limit="10", daily_loss_limit_percent="250")
        self.assertEqual(config.daily_loss_limit, Decimal("10"))
        self.assertEqual(config.daily_loss_limit_percent, Decimal("100"))
        self.assertFalse(config.flatten_on_daily_loss)

    def test_effective_limit_is_the_stricter_setting(self) -> None:
        engine = TraderEngine("limit")
        config = AppConfig(symbols=["SPY"], daily_loss_limit="30", daily_loss_limit_percent="2")
        self.assertEqual(engine.effective_daily_loss_limit(config, Decimal("1000")), Decimal("20"))
        self.assertEqual(engine.effective_daily_loss_limit(AppConfig(symbols=["SPY"]), Decimal("1000")), Decimal("0"))

    def test_breach_latches_for_the_session_and_resets_next_day(self) -> None:
        engine = TraderEngine("latch")
        config = AppConfig(symbols=["SPY"], daily_loss_limit="20")
        self.assertFalse(engine.evaluate_daily_loss_limit(config, {"equity": "990", "last_equity": "1000"}, "2026-11-04"))
        self.assertTrue(engine.evaluate_daily_loss_limit(config, {"equity": "975", "last_equity": "1000"}, "2026-11-04"))
        # equity recovers: still latched today
        self.assertTrue(engine.evaluate_daily_loss_limit(config, {"equity": "1005", "last_equity": "1000"}, "2026-11-04"))
        # new session clears it
        self.assertFalse(engine.evaluate_daily_loss_limit(config, {"equity": "1005", "last_equity": "1000"}, "2026-11-05"))

    def test_breach_blocks_new_entries_but_keeps_trading_enabled(self) -> None:
        client = FakeTradingClient(is_open=True)
        client.equity = "970"
        engine = connected_engine(client, daily_loss_limit="20")
        engine.config = engine.config.model_copy(update={"symbols": ["AAA", "BBB"]})
        engine.strategy_state.add_bar("BBB", "50", NOW - timedelta(minutes=1))
        engine.trading_enabled = True
        with (
            patch.object(engine, "entry_open_guard_message", return_value=""),
            patch.object(engine, "entry_close_guard_message", return_value=""),
            patch.object(engine, "entry_candidate", return_value=None) as candidate,
        ):
            with (
                patch.object(engine, "portfolio_history_daily_pl_payload", return_value={}),
                patch.object(engine, "record_day_tape_scan"),
                patch.object(engine, "record_day_tape_bars"),
            ):
                engine.refresh(run_strategy=True, shared_bars={"AAA": [], "BBB": []})
        self.assertTrue(engine.trading_enabled)
        self.assertIn("Daily loss limit hit", engine.status)
        bbb_calls = [call for call in candidate.call_args_list if call.args[0] == "BBB"]
        self.assertEqual(len(bbb_calls), 1)
        self.assertIs(bbb_calls[0].args[6], False)  # entries_allowed
        self.assertEqual(kinds(client), [("sell", "stop")])  # protection still placed, no flatten by default

    def test_flatten_option_sells_positions_when_breached(self) -> None:
        client = FakeTradingClient(is_open=True)
        client.equity = "970"
        engine = connected_engine(client, daily_loss_limit="20", flatten_on_daily_loss=True)
        run_refresh(engine, run_strategy=False)
        # exactly one closing order: no fresh stop placed behind the flatten sell
        self.assertEqual(kinds(client), [("sell", "market")])


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, body: str, **_: Any) -> bool:
        self.sent.append((title, body))
        return True


class AlertHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.notifier = RecordingNotifier()
        self.patcher = patch.object(engine_module, "NOTIFIER", self.notifier)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()

    def test_existing_fills_are_seeded_and_new_stop_out_alerts_once(self) -> None:
        client = FakeTradingClient(is_open=True)
        client.closed_orders = [{"id": "old", "symbol": "AAA", "side": "buy", "status": "filled",
                                 "filled_qty": "0.25", "filled_avg_price": "100", "client_order_id": "apt-entry-aaa-1"}]
        engine = connected_engine(client)
        run_refresh(engine)
        self.assertEqual(self.notifier.sent, [])
        client.closed_orders.append({"id": "new", "symbol": "AAA", "side": "sell", "status": "filled", "type": "stop",
                                     "filled_qty": "0.25", "filled_avg_price": "98.75",
                                     "client_order_id": "apt-protect-sl-aaa-2"})
        run_refresh(engine)
        run_refresh(engine)
        self.assertEqual(len(self.notifier.sent), 1)
        self.assertIn("Stopped out of AAA", self.notifier.sent[0][0])

    def test_rejected_order_alerts_and_alerts_can_be_turned_off(self) -> None:
        engine = TraderEngine("alerts")
        engine.config = AppConfig(symbols=["AAA"])
        engine.record_order_intent("AAA", engine_module.OrderSide.SELL, Decimal("1"), "Protective Exit", "error", "rejected")
        self.assertEqual(len(self.notifier.sent), 1)
        self.assertIn("Order rejected", self.notifier.sent[0][0])
        engine.config = AppConfig(symbols=["AAA"], alert_problems=False)
        engine.record_order_intent("AAA", engine_module.OrderSide.SELL, Decimal("1"), "Protective Exit", "error", "rejected")
        self.assertEqual(len(self.notifier.sent), 1)



class TakeProfitCancelRaceTests(unittest.TestCase):
    """Price above take-profit with a resting stop: the stop must be gone before the limit sell."""

    STOP = {"id": "s1", "symbol": "AAA", "side": "sell", "type": "stop", "qty": "0.25",
            "stop_price": "98.75", "client_order_id": "apt-protect-sl-aaa-1"}

    def above_take_profit(self, stop: dict[str, Any] | None = None) -> FakeTradingClient:
        return FakeTradingClient(is_open=True, price="103", orders=[dict(stop or self.STOP)])

    def test_pending_cancel_waits_for_the_stop_to_clear_then_sells(self) -> None:
        client = self.above_take_profit()
        polls: list[int] = []
        open_orders = client.get_orders

        def pending_cancel(order_id: str) -> None:
            raise RuntimeError('{"code":42210000,"message":"order pending cancel"}')

        def clears_after_first_poll(request: Any) -> list[dict[str, Any]]:
            orders = open_orders(request)
            polls.append(len(orders))
            client.open_orders = []
            return orders

        client.cancel_order_by_id = pending_cancel  # type: ignore[method-assign]
        client.get_orders = clears_after_first_poll  # type: ignore[method-assign]
        engine = connected_engine(client)
        engine_module.clear_runtime_diagnostics()
        with patch.object(engine_module.time, "sleep"):
            run_refresh(engine, run_strategy=False)
        self.assertEqual(kinds(client), [("sell", "limit")])
        self.assertNotIn(
            "Live order cancellation failed",
            [entry["message"] for entry in engine_module.runtime_diagnostics_snapshot()["entries"]],
        )

    def test_stop_still_pending_cancel_holds_the_sell(self) -> None:
        client = self.above_take_profit()
        client.cancel_order_by_id = lambda order_id: (_ for _ in ()).throw(  # type: ignore[method-assign]
            RuntimeError("order pending cancel")
        )
        engine = connected_engine(client)
        with patch.object(engine, "wait_for_symbol_app_orders_cleared", return_value=False) as wait:
            run_refresh(engine, run_strategy=False)
        wait.assert_called()
        self.assertEqual(client.submitted, [])
        self.assertIn("waiting for exit order cancellation", engine.strategy_state.last_action["AAA"])

    def test_order_already_pending_cancel_is_not_cancelled_again(self) -> None:
        client = self.above_take_profit(dict(self.STOP, status="pending_cancel"))
        engine = connected_engine(client)
        with patch.object(engine, "wait_for_symbol_app_orders_cleared", return_value=False):
            run_refresh(engine, run_strategy=False)
        self.assertEqual(client.cancelled, [])
        self.assertEqual(client.submitted, [])

    def test_refused_stop_cancel_never_sells(self) -> None:
        client = self.above_take_profit()

        def refuse(order_id: str) -> None:
            raise RuntimeError("order is not cancelable")

        client.cancel_order_by_id = refuse  # type: ignore[method-assign]
        engine = connected_engine(client)
        with patch.object(engine, "wait_for_symbol_app_orders_cleared", return_value=True) as wait:
            run_refresh(engine, run_strategy=False)
        wait.assert_not_called()
        self.assertEqual(client.submitted, [])


if __name__ == "__main__":
    unittest.main()
