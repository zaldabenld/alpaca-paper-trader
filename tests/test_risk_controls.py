from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AppConfig, TraderEngine


NOW = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)


class FakeTradingClient:
    """Minimal Alpaca TradingClient stand-in: one long AAA position, configurable orders/clock."""

    def __init__(self, *, is_open: bool, price: str = "100", orders: list[dict[str, Any]] | None = None) -> None:
        self.is_open = is_open
        self.price = price
        self.open_orders = list(orders or [])
        self.submitted: list[Any] = []
        self.cancelled: list[str] = []
        self.equity = "1000"
        self.last_equity = "1000"

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
                "avg_entry_price": "100",
                "current_price": self.price,
                "market_value": str(Decimal(self.price) * Decimal("0.25")),
                "unrealized_pl": "0",
                "side": "long",
            }
        ]

    def get_orders(self, request: Any) -> list[dict[str, Any]]:
        status = str(getattr(request, "status", "")).lower()
        return list(self.open_orders) if "open" in status else []

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

    def test_purge_orders_count_as_app_exits(self) -> None:
        engine = TraderEngine("roles")
        role = engine.order_role({"symbol": "AAA", "side": "sell", "client_order_id": "apt-purge-aaa-1"}, {"AAA"})
        self.assertEqual(role, "Strategy Exit")

    def test_zero_price_position_is_labelled_untradable(self) -> None:
        engine = TraderEngine("labels")
        engine.config = AppConfig(symbols=["AAA"], dry_run=False)
        rows = engine.protection_status_rows([{"symbol": "046CVR015", "qty": "2.8", "current_price": "0"}], [])
        self.assertEqual(rows[0]["status"], "No market price")


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


if __name__ == "__main__":
    unittest.main()
