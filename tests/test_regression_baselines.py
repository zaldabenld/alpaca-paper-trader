from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment, expected_failure


configure_test_environment()

from alpaca_desktop import server, storage
from alpaca_desktop.engine import AppConfig, TraderEngine, TraderManager


@contextmanager
def patched_storage_paths():
    with tempfile.TemporaryDirectory() as raw_dir:
        app_dir = Path(raw_dir) / "AlpacaPaperTrader"
        settings_path = app_dir / "python-settings.json"
        with patch.object(storage, "APP_DIR", app_dir), patch.object(storage, "SETTINGS_PATH", settings_path):
            yield app_dir, settings_path


@contextmanager
def patched_server_manager(raw_settings: dict[str, Any]):
    original_manager = server.manager
    original_loaded = server._settings_loaded
    replacement = TraderManager()
    server.manager = replacement
    server._settings_loaded = False
    try:
        with patch.object(server, "load_settings", return_value=raw_settings):
            yield replacement
    finally:
        server.manager = original_manager
        server._settings_loaded = original_loaded


def fresh_manager() -> TraderManager:
    manager = TraderManager()
    with manager.lock:
        manager.accounts = {}
        manager.selected_account_id = ""
    return manager


class ConfigAndSizingBaselineTests(unittest.TestCase):
    def test_config_preserves_current_implicit_trade_cap_conflict(self) -> None:
        default_percent = AppConfig(profile="neutral", symbols=["SPY"], max_trade_notional="20")
        self.assertEqual(default_percent.max_trade_notional, Decimal("20"))
        self.assertEqual(default_percent.max_trade_percent, Decimal("7.0"))
        self.assertFalse(hasattr(default_percent, "trade_size_mode"))

        dollar_only_by_caller_convention = AppConfig(
            profile="neutral",
            symbols=["SPY"],
            max_trade_notional="20",
            max_trade_percent="0",
        )
        self.assertEqual(dollar_only_by_caller_convention.max_trade_notional, Decimal("20"))
        self.assertEqual(dollar_only_by_caller_convention.max_trade_percent, Decimal("0"))

    @expected_failure("AUDIT-010: explicit trade_size_mode should reject conflicting percent and notional caps")
    def test_desired_trade_size_mode_rejects_conflicting_caps(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(
                profile="neutral",
                symbols=["SPY"],
                max_trade_notional="20",
                max_trade_percent="7.0",
            )

    def test_trade_notional_currently_blocks_when_exposure_room_is_below_planned_slot(self) -> None:
        engine = TraderEngine("sizing-baseline")
        config = AppConfig(
            symbols=["SPY"],
            use_top_volume_symbols=False,
            max_trade_notional="100",
            max_trade_percent="0",
            max_total_exposure_percent="50",
            max_open_positions=5,
        )

        self.assertEqual(engine.planned_entry_notional_cap(config, Decimal("1000"), Decimal("10")), Decimal("100"))
        self.assertEqual(
            engine.trade_notional(
                config=config,
                equity=Decimal("1000"),
                buying_power=Decimal("1000"),
                total_exposure=Decimal("425"),
                price=Decimal("10"),
            ),
            Decimal("0"),
        )

    @expected_failure("AUDIT-011: remaining exposure room above the minimum should downsize the entry")
    def test_desired_trade_notional_downsizes_to_remaining_exposure_room(self) -> None:
        engine = TraderEngine("sizing-desired")
        config = AppConfig(
            symbols=["SPY"],
            use_top_volume_symbols=False,
            max_trade_notional="100",
            max_trade_percent="0",
            max_total_exposure_percent="50",
            max_open_positions=5,
        )
        self.assertEqual(
            engine.trade_notional(
                config=config,
                equity=Decimal("1000"),
                buying_power=Decimal("1000"),
                total_exposure=Decimal("425"),
                price=Decimal("10"),
            ),
            Decimal("75"),
        )


class ProfitLossContractBaselineTests(unittest.TestCase):
    def test_daily_pl_payload_currently_uses_different_selected_and_summary_shapes(self) -> None:
        engine = TraderEngine("pl-baseline")
        engine.account = {
            "equity_display": "$101.23",
            "daily_pl": "1.230000",
            "daily_pl_display": "$1.23",
            "realized_pl": "0.450000",
            "realized_pl_display": "$0.45",
            "realized_pl_pct": "0.123456",
            "realized_pl_pct_display": "+0.12%",
        }

        selected_account = engine.state()["account"]
        summary = engine.summary()

        self.assertEqual(selected_account["daily_pl"], "1.230000")
        self.assertEqual(selected_account["daily_pl_display"], "$1.23")
        self.assertNotIn("daily_pl_pct", selected_account)
        self.assertNotIn("daily_pl_pct_display", selected_account)

        self.assertEqual(summary["daily_pl"], "$1.23")
        self.assertEqual(summary["daily_pl_raw"], "1.230000")
        self.assertNotIn("daily_pl_display", summary)
        self.assertNotIn("daily_pl_pct_raw", summary)

    @expected_failure("AUDIT-002/AUDIT-016: daily P/L raw, display, and percent keys should be standardized")
    def test_desired_daily_pl_contract_has_standard_raw_display_and_percent_fields(self) -> None:
        engine = TraderEngine("pl-desired")
        engine.account = {
            "equity_display": "$101.23",
            "daily_pl": "1.230000",
            "daily_pl_display": "$1.23",
        }

        selected_account = engine.state()["account"]
        summary = engine.summary()

        for key in ("daily_pl_raw", "daily_pl_display", "daily_pl_pct_raw", "daily_pl_pct_display"):
            self.assertIn(key, selected_account)
        for key in ("daily_pl_raw", "daily_pl_display", "daily_pl_pct_raw", "daily_pl_pct_display"):
            self.assertIn(key, summary)

    def test_daily_realized_summary_includes_today_sells_and_excludes_prior_days(self) -> None:
        engine = TraderEngine("realized-baseline")
        now = datetime.now().astimezone()
        rows = [
            {
                "side": "sell",
                "sort_time": now.isoformat(),
                "cost_basis_raw": "100",
                "realized_pl_raw": "5",
            },
            {
                "side": "sell",
                "sort_time": (now - timedelta(days=1)).isoformat(),
                "cost_basis_raw": "80",
                "realized_pl_raw": "8",
            },
            {
                "side": "buy",
                "sort_time": now.isoformat(),
                "cost_basis_raw": "50",
                "realized_pl_raw": "4",
            },
        ]

        summary = engine.daily_realized_pl_summary(rows, Decimal("1000"))

        self.assertEqual(summary["value"], Decimal("5.000000"))
        self.assertEqual(summary["trade_cost_basis"], Decimal("100.000000"))
        self.assertEqual(summary["account_basis"], Decimal("1000.000000"))
        self.assertEqual(summary["percent"], Decimal("0.500000"))
        self.assertNotIn("session_date", summary)

    @expected_failure("AUDIT-003: realized P/L summary should expose the session/date boundary it used")
    def test_desired_daily_realized_summary_exposes_session_date(self) -> None:
        engine = TraderEngine("realized-desired")
        summary = engine.daily_realized_pl_summary([], Decimal("1000"))
        self.assertIn("session_date", summary)


class SettingsBaselineTests(unittest.TestCase):
    def test_corrupt_settings_file_currently_loads_as_empty_settings(self) -> None:
        with patched_storage_paths() as (_app_dir, settings_path):
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text("{not-json", encoding="utf-8")

            self.assertEqual(storage.load_settings(), {})

    @expected_failure("AUDIT-013: corrupt settings should surface a typed or visible load error")
    def test_desired_corrupt_settings_load_surfaces_error(self) -> None:
        with patched_storage_paths() as (_app_dir, settings_path):
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text("{not-json", encoding="utf-8")

            loaded = storage.load_settings()
            self.assertIn("settings_load_error", loaded)

    def test_save_settings_write_error_still_propagates(self) -> None:
        with patched_storage_paths() as (app_dir, settings_path):
            app_dir.mkdir(parents=True, exist_ok=True)
            settings_path.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(OSError):
                storage.save_settings({"accounts": []})

    def test_saved_account_parse_failure_currently_drops_invalid_account(self) -> None:
        raw_settings = {
            "selected_account_id": "valid",
            "accounts": [
                {
                    "account_id": "valid",
                    "name": "Valid",
                    "remember": False,
                    "config": {"symbols": ["SPY"], "use_top_volume_symbols": False},
                },
                {
                    "account_id": "broken",
                    "name": "Broken",
                    "remember": False,
                    "config": {"symbols": []},
                },
            ],
        }

        with patched_server_manager(raw_settings) as manager:
            server.load_saved_settings_to_manager()
            self.assertIn("valid", manager.accounts)
            self.assertNotIn("broken", manager.accounts)

    @expected_failure("AUDIT-012: invalid saved accounts should remain visible with a settings-load error")
    def test_desired_saved_account_parse_failure_preserves_visible_shell(self) -> None:
        raw_settings = {
            "selected_account_id": "broken",
            "accounts": [
                {
                    "account_id": "broken",
                    "name": "Broken",
                    "remember": False,
                    "config": {"symbols": []},
                },
            ],
        }

        with patched_server_manager(raw_settings) as manager:
            server.load_saved_settings_to_manager()
            self.assertIn("broken", manager.accounts)
            self.assertIn("settings_load_error", manager.accounts["broken"].state())


class MarketStreamBaselineTests(unittest.TestCase):
    def test_market_stream_symbols_currently_use_first_eligible_account_only(self) -> None:
        manager = fresh_manager()
        first = manager.create_account(
            "First",
            AppConfig(symbols=["SPY"], use_top_volume_symbols=False, use_market_stream=True),
        )
        second = manager.create_account(
            "Second",
            AppConfig(symbols=["QQQ"], use_top_volume_symbols=False, use_market_stream=True),
        )
        first.connected = True
        second.connected = True
        manager.selected_account_id = first.account_id

        dashboard_symbols, bar_symbols = manager.market_data_symbols()

        self.assertEqual(dashboard_symbols, ["SPY"])
        self.assertEqual(bar_symbols, ["SPY"])
        self.assertNotIn("QQQ", bar_symbols)

    @expected_failure("AUDIT-018: market stream bar symbols should union connected eligible account symbols")
    def test_desired_market_stream_symbols_union_connected_accounts(self) -> None:
        manager = fresh_manager()
        first = manager.create_account(
            "First",
            AppConfig(symbols=["SPY"], use_top_volume_symbols=False, use_market_stream=True),
        )
        second = manager.create_account(
            "Second",
            AppConfig(symbols=["QQQ"], use_top_volume_symbols=False, use_market_stream=True),
        )
        first.connected = True
        second.connected = True
        manager.selected_account_id = first.account_id

        _dashboard_symbols, bar_symbols = manager.market_data_symbols()

        self.assertIn("SPY", bar_symbols)
        self.assertIn("QQQ", bar_symbols)

    def test_held_positions_are_in_scan_symbols_but_not_current_stream_bars(self) -> None:
        manager = fresh_manager()
        engine = manager.create_account(
            "Held",
            AppConfig(symbols=["SPY"], use_top_volume_symbols=False, use_market_stream=True),
        )
        engine.connected = True
        engine.positions = [{"symbol": "AAPL", "qty_raw": "0.25"}]
        manager.selected_account_id = engine.account_id

        self.assertIn("AAPL", engine.scan_symbols())
        _dashboard_symbols, bar_symbols = manager.market_data_symbols()
        self.assertEqual(bar_symbols, ["SPY"])
        self.assertNotIn("AAPL", bar_symbols)

    @expected_failure("AUDIT-019: held-position symbols should be included in shared market stream bars")
    def test_desired_market_stream_bars_include_held_position_symbols(self) -> None:
        manager = fresh_manager()
        engine = manager.create_account(
            "Held",
            AppConfig(symbols=["SPY"], use_top_volume_symbols=False, use_market_stream=True),
        )
        engine.connected = True
        engine.positions = [{"symbol": "AAPL", "qty_raw": "0.25"}]
        manager.selected_account_id = engine.account_id

        _dashboard_symbols, bar_symbols = manager.market_data_symbols()

        self.assertIn("SPY", bar_symbols)
        self.assertIn("AAPL", bar_symbols)


if __name__ == "__main__":
    unittest.main()
