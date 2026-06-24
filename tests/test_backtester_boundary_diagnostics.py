from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.backtester import StrategyEvaluationContext
from alpaca_desktop.engine import TraderEngine, TraderManager
from alpaca_desktop.runtime_diagnostics import (
    OrderExecutionError,
    runtime_diagnostics,
    runtime_diagnostics_snapshot,
)


class BacktesterBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_diagnostics.clear()

    def tearDown(self) -> None:
        runtime_diagnostics.clear()

    def test_backtester_boundary_delegates_to_live_strategy_methods(self) -> None:
        engine = TraderEngine("boundary")
        boundary = engine.backtester_boundary()
        context = StrategyEvaluationContext(
            account={"equity": "1000", "buying_power": "1000"},
            position=None,
            open_position_count=0,
            open_orders=[],
            total_exposure=Decimal("0"),
            entries_allowed=True,
            entry_guard_detail="",
            opening_guard_detail="",
            allow_entries=True,
        )

        with patch.object(
            engine,
            "apply_strategy",
            return_value=([("info", "delegated")], False, {"side": "buy", "symbol": "SPY"}),
        ) as apply_strategy:
            result = boundary.strategy.apply_strategy("SPY", context)

        self.assertEqual(result[0], [("info", "delegated")])
        apply_strategy.assert_called_once_with(
            "SPY",
            context.account,
            context.position,
            context.open_position_count,
            context.open_orders,
            context.total_exposure,
            context.entries_allowed,
            context.entry_guard_detail,
            context.opening_guard_detail,
            context.allow_entries,
        )

    def test_backtester_boundary_account_snapshot_is_copy(self) -> None:
        engine = TraderEngine("snapshot")
        engine.account = {"equity": "1000"}
        engine.positions = [{"symbol": "SPY", "qty": "1"}]

        snapshot = engine.backtester_boundary().account_state.snapshot()
        snapshot["account"]["equity"] = "0"
        snapshot["positions"][0]["symbol"] = "QQQ"

        self.assertEqual(engine.account["equity"], "1000")
        self.assertEqual(engine.positions[0]["symbol"], "SPY")

    def test_order_boundary_wraps_broker_failure_and_records_diagnostic(self) -> None:
        class FailingClient:
            def submit_order(self, _order: object) -> object:
                raise RuntimeError("broker rejected")

        engine = TraderEngine("orders")
        engine.trading_client = FailingClient()  # type: ignore[assignment]

        with self.assertRaises(OrderExecutionError):
            engine.submit_order_request(object())

        diagnostics = runtime_diagnostics_snapshot()
        self.assertEqual(diagnostics["error_count"], 1)
        self.assertEqual(diagnostics["entries"][-1]["area"], "order_execution")
        self.assertIn("broker rejected", diagnostics["entries"][-1]["detail"])

    def test_manager_state_and_health_payloads_include_runtime_diagnostics(self) -> None:
        manager = TraderManager()
        state = manager.state()
        dashboard = manager.dashboard_state()

        self.assertIn("runtime_diagnostics", state)
        self.assertIn("runtime_diagnostics", dashboard)


class RuntimeDiagnosticsFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime_diagnostics.clear()

    def tearDown(self) -> None:
        runtime_diagnostics.clear()

    def test_dashboard_cache_load_failure_records_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            cache_path = Path(raw_dir) / "dashboard-cache.json"
            cache_path.write_text("{bad-json", encoding="utf-8")

            with patch.object(engine_module, "DASHBOARD_CACHE_PATH", cache_path):
                self.assertEqual(engine_module.load_dashboard_cache_rows(), {})

        diagnostics = runtime_diagnostics_snapshot()
        self.assertEqual(diagnostics["entries"][-1]["area"], "dashboard_cache")
        self.assertIn("using empty cache", diagnostics["entries"][-1]["message"])

    def test_replay_write_failure_returns_error_and_records_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            replay_dir_as_file = Path(raw_dir) / "replay"
            replay_dir_as_file.write_text("not a directory", encoding="utf-8")

            with patch.object(engine_module, "REPLAY_DIR", replay_dir_as_file):
                event = engine_module.append_replay_event("test", {"ok": True})

        self.assertIn("write_error", event)
        diagnostics = runtime_diagnostics_snapshot()
        self.assertEqual(diagnostics["entries"][-1]["area"], "replay")


if __name__ == "__main__":
    unittest.main()
