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
    def test_config_uses_explicit_trade_size_mode_and_migrates_legacy_single_cap(self) -> None:
        default_percent = AppConfig(profile="neutral", symbols=["SPY"])
        self.assertEqual(default_percent.trade_size_mode, "percent")
        self.assertEqual(default_percent.max_trade_notional, Decimal("0"))
        self.assertEqual(default_percent.max_trade_percent, Decimal("7.0"))

        default_percent = AppConfig(profile="neutral", symbols=["SPY"], max_trade_notional="20")
        self.assertEqual(default_percent.max_trade_notional, Decimal("20"))
        self.assertEqual(default_percent.max_trade_percent, Decimal("0"))
        self.assertEqual(default_percent.trade_size_mode, "notional")
        self.assertEqual(default_percent.trade_size_migration, "inferred_notional_from_legacy_dollar_cap")

        dollar_only_by_caller_convention = AppConfig(
            profile="neutral",
            symbols=["SPY"],
            max_trade_notional="20",
            max_trade_percent="0",
        )
        self.assertEqual(dollar_only_by_caller_convention.max_trade_notional, Decimal("20"))
        self.assertEqual(dollar_only_by_caller_convention.max_trade_percent, Decimal("0"))
        self.assertEqual(dollar_only_by_caller_convention.trade_size_mode, "notional")

    def test_trade_size_mode_rejects_conflicting_caps(self) -> None:
        explicit_notional = AppConfig(
            profile="neutral",
            symbols=["SPY"],
            trade_size_mode="notional",
            max_trade_notional="20",
        )
        self.assertEqual(explicit_notional.max_trade_notional, Decimal("20"))
        self.assertEqual(explicit_notional.max_trade_percent, Decimal("0"))

        with self.assertRaises(ValueError):
            AppConfig(
                profile="neutral",
                symbols=["SPY"],
                trade_size_mode="percent",
                max_trade_notional="20",
                max_trade_percent="7.0",
            )
        with self.assertRaises(ValueError):
            AppConfig(
                profile="neutral",
                symbols=["SPY"],
                max_trade_notional="20",
                max_trade_percent="7.0",
            )

    def test_trade_notional_downsizes_to_remaining_exposure_room(self) -> None:
        engine = TraderEngine("sizing-baseline")
        config = AppConfig(
            symbols=["SPY"],
            use_top_volume_symbols=False,
            trade_size_mode="notional",
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
            Decimal("75"),
        )

    def test_trade_notional_blocks_when_remaining_exposure_room_is_not_tradeable(self) -> None:
        engine = TraderEngine("sizing-desired")
        config = AppConfig(
            symbols=["SPY"],
            use_top_volume_symbols=False,
            trade_size_mode="notional",
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
                total_exposure=Decimal("499.50"),
                price=Decimal("10"),
            ),
            Decimal("0"),
        )


class ProfitLossContractBaselineTests(unittest.TestCase):
    def test_daily_pl_payload_uses_standard_raw_display_and_percent_fields(self) -> None:
        engine = TraderEngine("pl-baseline")
        engine.account = {
            "equity_display": "$101.23",
            "last_equity": "100",
            "daily_pl": "1.230000",
            "daily_pl_display": "$1.23",
            "realized_pl": "0.450000",
            "realized_pl_display": "$0.45",
            "realized_pl_pct": "0.123456",
            "realized_pl_pct_display": "+0.12%",
        }

        selected_account = engine.state()["account"]
        summary = engine.summary()

        self.assertEqual(selected_account["daily_pl"], "$1.23")
        self.assertEqual(selected_account["daily_pl_raw"], "1.230000")
        self.assertEqual(selected_account["daily_pl_display"], "$1.23")
        self.assertEqual(selected_account["daily_pl_pct_raw"], "1.230000")
        self.assertEqual(selected_account["daily_pl_pct_display"], "+1.23%")
        self.assertIn("daily_pl_session_date", selected_account)

        self.assertEqual(summary["daily_pl"], "$1.23")
        self.assertEqual(summary["daily_pl_raw"], "1.230000")
        self.assertEqual(summary["daily_pl_display"], "$1.23")
        self.assertEqual(summary["daily_pl_pct_raw"], "1.230000")
        self.assertEqual(summary["daily_pl_pct_display"], "+1.23%")

    def test_daily_pl_contract_handles_empty_account_state(self) -> None:
        engine = TraderEngine("pl-desired")
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
        self.assertIn("session_date", summary)


class SettingsBaselineTests(unittest.TestCase):
    def test_corrupt_settings_file_surfaces_load_error(self) -> None:
        with patched_storage_paths() as (_app_dir, settings_path):
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text("{not-json", encoding="utf-8")

            loaded = storage.load_settings()
            self.assertIn("settings_load_error", loaded)
            self.assertEqual(loaded["settings_load_error_path"], str(settings_path))

    def test_corrupt_settings_file_recovers_from_latest_backup(self) -> None:
        with patched_storage_paths() as (_app_dir, settings_path):
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            backup = settings_path.with_name(f"{settings_path.name}.20260624T000000Z.test.bak")
            backup.write_text('{"selected_account_id":"backup","accounts":[]}', encoding="utf-8")
            settings_path.write_text("{not-json", encoding="utf-8")

            loaded = storage.load_settings()
            self.assertIn("settings_load_error", loaded)
            self.assertEqual(loaded["selected_account_id"], "backup")
            self.assertEqual(loaded["settings_recovered_from_backup"], str(backup))

    def test_save_settings_writes_backup_before_atomic_replace(self) -> None:
        with patched_storage_paths() as (_app_dir, settings_path):
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text('{"selected_account_id":"old","accounts":[]}', encoding="utf-8")

            storage.save_settings({"selected_account_id": "new", "accounts": []})

            self.assertEqual(storage.load_settings()["selected_account_id"], "new")
            backups = list(settings_path.parent.glob(f"{settings_path.name}.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertIn('"old"', backups[0].read_text(encoding="utf-8"))

    def test_save_settings_write_error_still_propagates(self) -> None:
        with patched_storage_paths() as (app_dir, settings_path):
            app_dir.mkdir(parents=True, exist_ok=True)
            settings_path.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(OSError):
                storage.save_settings({"accounts": []})

    def test_saved_account_parse_failure_preserves_visible_shell(self) -> None:
        raw_settings = {
            "selected_account_id": "broken",
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
            self.assertIn("broken", manager.accounts)
            self.assertIn("settings_load_error", manager.accounts["broken"].state())
            self.assertEqual(manager.selected_account_id, "broken")
            self.assertEqual(manager.settings_diagnostics()["error_count"], 1)


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
