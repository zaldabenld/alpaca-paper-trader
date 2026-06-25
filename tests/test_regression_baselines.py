from __future__ import annotations

import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import server, storage
from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AccountPayload, AppConfig, TraderEngine, TraderManager


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


def entry_ready_snapshot(price: str = "10") -> SimpleNamespace:
    return SimpleNamespace(
        price=Decimal(price),
        rsi=Decimal("55"),
        bias="Bullish",
        momentum_percent=Decimal("2.0"),
        recent_momentum_percent=Decimal("1.0"),
        long_momentum_percent=Decimal("3.0"),
        session_change_percent=Decimal("3.0"),
        vwap_distance_percent=Decimal("1.0"),
        session_pullback_percent=Decimal("0.1"),
        recent_pullback_percent=Decimal("0.1"),
        smi=Decimal("60"),
        relative_volume=Decimal("3.0"),
        volume_ok=True,
        atr_percent=Decimal("2.0"),
        volatility_percent=Decimal("2.0"),
    )


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


class StrategySelectionContractTests(unittest.TestCase):
    def candidate_config(self, **overrides: Any) -> AppConfig:
        payload: dict[str, Any] = {
            "symbols": ["AAA"],
            "use_top_volume_symbols": True,
            "inverse_etf_mode": "exclude",
            "trade_size_mode": "percent",
            "max_trade_notional": "0",
            "max_trade_percent": "5",
            "max_open_positions": 1,
            "max_total_exposure_percent": "100",
            "buy_rsi_min": "40",
            "buy_rsi_max": "80",
            "min_entry_score": "1",
            "min_momentum_percent": "0.05",
            "min_recent_momentum_percent": "0",
            "min_long_momentum_percent": "0",
            "min_session_change_percent": "0.5",
            "min_vwap_distance_percent": "0",
            "max_vwap_distance_percent": "5",
            "max_session_pullback_percent": "2",
            "max_recent_pullback_percent": "2",
            "min_smi": "20",
            "volume_multiplier": "1",
            "dry_run": True,
        }
        payload.update(overrides)
        return AppConfig(**payload)

    def test_entry_candidate_ranking_ignores_sizing_capacity_and_price_inputs(self) -> None:
        engine = TraderEngine("selection-contract")
        snapshot = entry_ready_snapshot(price="5000")

        constrained_config = self.candidate_config(max_open_positions=1, max_total_exposure_percent="10")
        notional_config = self.candidate_config(
            trade_size_mode="notional",
            max_trade_notional="20",
            max_trade_percent="0",
            max_open_positions=20,
            max_total_exposure_percent="100",
        )

        with patch.object(engine, "snapshot", return_value=snapshot):
            engine.config = constrained_config
            constrained = engine.entry_candidate(
                "AAA",
                0,
                {"equity": "100", "buying_power": "0"},
                None,
                open_position_count=1,
                open_orders=[],
                entries_allowed=True,
            )
            engine.clear_entry_score("AAA")

            engine.config = notional_config
            unconstrained = engine.entry_candidate(
                "AAA",
                0,
                {"equity": "100000", "buying_power": "100000"},
                None,
                open_position_count=0,
                open_orders=[],
                entries_allowed=True,
            )

        self.assertIsNotNone(constrained)
        self.assertIsNotNone(unconstrained)
        self.assertEqual(constrained["score"], unconstrained["score"])
        self.assertEqual(constrained["symbol"], "AAA")
        self.assertEqual(unconstrained["symbol"], "AAA")

    def test_apply_strategy_keeps_capacity_gate_after_candidate_ranking(self) -> None:
        engine = TraderEngine("selection-capacity")
        engine.config = self.candidate_config(max_open_positions=1)
        snapshot = entry_ready_snapshot()

        with patch.object(engine, "snapshot", return_value=snapshot):
            candidate = engine.entry_candidate(
                "AAA",
                0,
                {"equity": "1000", "buying_power": "1000"},
                None,
                open_position_count=1,
                open_orders=[],
                entries_allowed=True,
            )
            events, stop_rule, reservation = engine.apply_strategy(
                "AAA",
                {"equity": "1000", "buying_power": "1000"},
                None,
                open_position_count=1,
                open_orders=[],
                total_exposure=Decimal("0"),
            )

        self.assertIsNotNone(candidate)
        self.assertEqual(events, [])
        self.assertFalse(stop_rule)
        self.assertIsNone(reservation)
        self.assertEqual(engine.strategy_state.last_action["AAA"], "Hold (max positions)")


class ProfitLossContractBaselineTests(unittest.TestCase):
    def test_daily_pl_payload_uses_standard_raw_display_and_percent_fields(self) -> None:
        engine = TraderEngine("pl-baseline")
        engine.account = {
            "equity_display": "$101.23",
            "last_equity": "100",
            "daily_pl": "1.230000",
            "daily_pl_raw": "1.230000",
            "daily_pl_display": "$1.23",
            "daily_pl_pct_raw": "1.230000",
            "daily_pl_pct_display": "+1.23%",
            "daily_pl_account_basis_raw": "100.000000",
            "daily_pl_source": "alpaca_portfolio_history",
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

        self.assertEqual(selected_account["daily_pl_raw"], "")
        self.assertEqual(selected_account["daily_pl_display"], "Unavailable")
        self.assertEqual(selected_account["daily_pl_pct_raw"], "")
        self.assertEqual(selected_account["daily_pl_pct_display"], "Unavailable")
        self.assertEqual(summary["daily_pl_raw"], "")
        self.assertEqual(summary["daily_pl_display"], "Unavailable")
        self.assertEqual(summary["daily_pl_pct_raw"], "")
        self.assertEqual(summary["daily_pl_pct_display"], "Unavailable")

    def test_daily_pl_contract_rejects_account_field_subtraction_without_portfolio_source(self) -> None:
        engine = TraderEngine("pl-no-source")
        engine.account = {"equity": "1010", "last_equity": "1000"}

        selected_account = engine.state()["account"]

        self.assertEqual(selected_account["daily_pl_raw"], "")
        self.assertEqual(selected_account["daily_pl_display"], "Unavailable")
        self.assertEqual(selected_account["daily_pl_source"], "unavailable")

    def test_daily_pl_payload_uses_alpaca_portfolio_history_source(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.request = None

            def get_portfolio_history(self, request):
                self.request = request
                return SimpleNamespace(
                    profit_loss=[None, "0.20"],
                    profit_loss_pct=[None, "0.0004"],
                    base_value="465.42",
                    equity=["465.62"],
                    timestamp=[123],
                    timeframe="1Min",
                )

        engine = TraderEngine("pl-history")
        client = FakeClient()

        payload = engine.portfolio_history_daily_pl_payload(client, "2026-06-24")

        self.assertEqual(payload["daily_pl_source"], "alpaca_portfolio_history")
        self.assertEqual(payload["daily_pl_raw"], "0.200000")
        self.assertEqual(payload["daily_pl_display"], "$0.20")
        self.assertEqual(payload["daily_pl_pct_raw"], "0.040000")
        self.assertEqual(payload["daily_pl_pct_display"], "+0.04%")
        self.assertEqual(payload["daily_pl_account_basis_raw"], "465.420000")
        self.assertEqual(client.request.date_end, date(2026, 6, 24))

    def test_daily_pl_percent_does_not_round_nonzero_source_pl_to_zero(self) -> None:
        class FakeClient:
            def get_portfolio_history(self, request):
                return SimpleNamespace(
                    profit_loss=["-0.18"],
                    profit_loss_pct=["0.0"],
                    base_value="116141.33",
                    equity=["116141.15"],
                    timestamp=[123],
                    timeframe="1Min",
                )

        engine = TraderEngine("pl-tiny-percent")

        payload = engine.portfolio_history_daily_pl_payload(FakeClient(), "2026-06-24")

        self.assertEqual(payload["daily_pl_raw"], "-0.180000")
        self.assertNotEqual(payload["daily_pl_pct_raw"], "0.000000")
        self.assertEqual(payload["daily_pl_pct_display"], "-0.0002%")

    def test_market_clock_payload_exposes_clock_session_date(self) -> None:
        engine = TraderEngine("clock-session")
        clock = SimpleNamespace(
            is_open=True,
            timestamp=datetime(2026, 6, 24, 15, 0, tzinfo=timezone.utc),
            next_open=datetime(2026, 6, 24, 13, 30, tzinfo=timezone.utc),
            next_close=datetime(2026, 6, 24, 20, 0, tzinfo=timezone.utc),
        )

        payload = engine.format_market_clock(clock)

        self.assertEqual(payload["session_date"], "2026-06-24")

    def test_closed_pre_open_market_clock_uses_latest_closed_session_date(self) -> None:
        engine = TraderEngine("clock-pre-open-session")
        local_tz = datetime.now().astimezone().tzinfo
        clock = SimpleNamespace(
            is_open=False,
            timestamp=datetime(2026, 6, 25, 0, 5, tzinfo=local_tz),
            next_open=datetime(2026, 6, 25, 8, 30, tzinfo=local_tz),
            next_close=datetime(2026, 6, 25, 15, 0, tzinfo=local_tz),
        )

        payload = engine.format_market_clock(clock)

        self.assertEqual(payload["session_date"], "2026-06-24")

    def test_standardized_daily_pl_uses_market_clock_session_date(self) -> None:
        engine = TraderEngine("pl-session")
        engine.market_clock = {
            "status": "Closed",
            "is_open": False,
            "detail": "",
            "next_open": "",
            "next_close": "",
            "session_date": "2026-06-24",
        }
        engine.account = {"equity": "1010", "last_equity": "1000", "daily_pl_raw": "10"}

        account = engine.standardized_account_metrics()

        self.assertEqual(account["daily_pl_session_date"], "2026-06-24")
        self.assertEqual(account["realized_pl_session_date"], "2026-06-24")

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

    def test_daily_realized_summary_uses_supplied_market_clock_session_date(self) -> None:
        engine = TraderEngine("realized-session")
        rows = [
            {
                "side": "sell",
                "sort_time": "2026-06-24T17:00:00+00:00",
                "cost_basis_raw": "100",
                "realized_pl_raw": "5",
            },
            {
                "side": "sell",
                "sort_time": "2026-06-25T17:00:00+00:00",
                "cost_basis_raw": "80",
                "realized_pl_raw": "8",
            },
        ]

        summary = engine.daily_realized_pl_summary(rows, Decimal("1000"), "2026-06-24")

        self.assertEqual(summary["value"], Decimal("5.000000"))
        self.assertEqual(summary["trade_cost_basis"], Decimal("100.000000"))
        self.assertEqual(summary["session_date"], "2026-06-24")


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
    def test_top_volume_refresh_uses_alpaca_most_actives_screener(self) -> None:
        class FakeScreenerClient:
            def __init__(self) -> None:
                self.requests: list[Any] = []

            def get_most_actives(self, request: Any) -> dict[str, Any]:
                self.requests.append(request)
                return {
                    "most_actives": [
                        {"symbol": "ZZZ", "volume": 2000, "trade_count": 20},
                        {"symbol": "AAA", "volume": 1500, "trade_count": 15},
                    ]
                }

        fake_screener = FakeScreenerClient()
        engine = TraderEngine("top-volume")
        engine.connected = True
        engine.screener_client = fake_screener  # type: ignore[assignment]
        engine.data_client = object()  # type: ignore[assignment]

        snapshots = {
            "ZZZ": SimpleNamespace(
                latest_trade=SimpleNamespace(price="12.34"),
                daily_bar=SimpleNamespace(close="12.30"),
            ),
            "AAA": SimpleNamespace(
                latest_trade=SimpleNamespace(price="23.45"),
                daily_bar=SimpleNamespace(close="23.40"),
            ),
        }

        with patch.object(engine_module, "fetch_stock_snapshots_chunked", return_value=snapshots) as fetch_snapshots:
            engine.refresh_top_volume(force=True, restart_stream=False)

        self.assertEqual(len(fake_screener.requests), 1)
        self.assertEqual(fake_screener.requests[0].top, engine_module.DASHBOARD_TOP_LIMIT)
        self.assertEqual(getattr(fake_screener.requests[0].by, "value", fake_screener.requests[0].by), "volume")
        fetch_snapshots.assert_called_once()
        self.assertEqual(fetch_snapshots.call_args.args[1], ["ZZZ", "AAA"])
        self.assertEqual(engine.top_volume_symbols, ["ZZZ", "AAA"])
        self.assertEqual(engine.top_volume_rows[0]["total_volume_raw"], 2000)
        self.assertEqual(engine.dashboard_state()["top_volume_source"], engine_module.TOP_VOLUME_SOURCE)

    def test_strategy_scan_day_tape_includes_top_volume_context(self) -> None:
        engine = TraderEngine("scan-context")
        engine.config = AppConfig(symbols=["MANUAL"], use_top_volume_symbols=True)
        engine.apply_shared_top_volume(
            rows=[{"rank": 1, "rank_raw": 1, "symbol": "AAA", "total_volume_raw": 12345}],
            symbols=["AAA"],
            updated="2026-06-24T20:30:00Z",
        )
        captured: list[tuple[str, dict[str, Any]]] = []

        def fake_append(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            captured.append((kind, payload))
            return {"kind": kind, "payload": payload}

        with patch.object(engine_module, "append_day_tape_event", fake_append):
            engine.record_day_tape_scan(
                should_trade=True,
                entries_allowed=True,
                entry_guard_detail="",
                market_clock={"is_open": True, "status": "Open", "session_date": "2026-06-24"},
                account={"equity": "1000", "cash": "1000", "buying_power": "1000"},
                positions=[],
                open_orders=[],
                closed_orders=[],
                strategy_rows=[],
            )

        self.assertEqual(len(captured), 1)
        kind, payload = captured[0]
        self.assertEqual(kind, "strategy_scan")
        self.assertEqual(payload["symbol_source"], "top_volume")
        self.assertEqual(payload["top_volume_source"], engine_module.TOP_VOLUME_SOURCE)
        self.assertEqual(payload["top_volume_symbols"], ["AAA"])
        self.assertEqual(payload["top_volume_rows"][0]["symbol"], "AAA")
        self.assertEqual(payload["top_volume_updated_at"], "2026-06-24T20:30:00Z")

    def test_market_open_strategy_scan_records_context_when_trading_disabled(self) -> None:
        engine = TraderEngine("scan-context-disabled")
        engine.trading_enabled = False
        engine.config = AppConfig(symbols=["MANUAL"], use_top_volume_symbols=True)
        engine.apply_shared_top_volume(
            rows=[{"rank": 1, "rank_raw": 1, "symbol": "AAA", "total_volume_raw": 12345}],
            symbols=["AAA"],
            updated="2026-06-25T14:30:00Z",
        )
        captured: list[tuple[str, dict[str, Any]]] = []

        def fake_append(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            captured.append((kind, payload))
            return {"kind": kind, "payload": payload}

        with patch.object(engine_module, "append_day_tape_event", fake_append):
            engine.record_day_tape_scan(
                should_trade=False,
                entries_allowed=True,
                entry_guard_detail="",
                market_clock={"is_open": True, "status": "Open", "session_date": "2026-06-25"},
                account={"equity": "1000", "cash": "1000", "buying_power": "1000"},
                positions=[],
                open_orders=[],
                closed_orders=[],
                strategy_rows=[],
            )

        self.assertEqual(len(captured), 1)
        kind, payload = captured[0]
        self.assertEqual(kind, "strategy_scan")
        self.assertFalse(payload["trading_enabled"])
        self.assertFalse(payload["should_trade"])
        self.assertEqual(payload["top_volume_source"], engine_module.TOP_VOLUME_SOURCE)
        self.assertEqual(payload["top_volume_symbols"], ["AAA"])

    def test_account_refresh_updates_top_volume_before_strategy_symbols(self) -> None:
        manager = fresh_manager()
        source = manager.create_account(
            "Source",
            AppConfig(symbols=["OLD"], use_top_volume_symbols=True, use_market_stream=True),
        )
        target = manager.create_account(
            "Target",
            AppConfig(symbols=["MANUAL"], use_top_volume_symbols=True, use_market_stream=True),
        )
        source.connected = True
        target.connected = True
        manager.selected_account_id = source.account_id
        calls: list[str] = []

        def fake_refresh_top_volume(force: bool = False, restart_stream: bool = True) -> None:
            calls.append(f"top_volume:{force}:{restart_stream}")
            source.apply_shared_top_volume(
                rows=[{"symbol": "AAA", "rank": 1, "rank_raw": 1}],
                symbols=["AAA"],
                updated="synthetic",
                error="",
            )

        def fake_target_refresh(*_args: Any, **_kwargs: Any) -> None:
            calls.append("strategy_refresh")
            self.assertEqual(target.trading_symbols()[:1], ["AAA"])

        source.refresh_top_volume = fake_refresh_top_volume  # type: ignore[method-assign]
        target.refresh = fake_target_refresh  # type: ignore[method-assign]

        manager.refresh_account(target.account_id)

        self.assertEqual(calls, ["top_volume:False:False", "strategy_refresh"])
        self.assertEqual(target.top_volume_symbols, ["AAA"])

    def test_top_volume_cache_is_short_enough_for_live_trading_refresh(self) -> None:
        self.assertLessEqual(engine_module.TOP_VOLUME_CACHE_SECONDS, 60)

    def test_market_stream_bar_symbols_union_connected_eligible_accounts(self) -> None:
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
        self.assertEqual(bar_symbols, ["SPY", "QQQ"])

    def test_market_stream_bar_symbols_follow_source_then_other_accounts(self) -> None:
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

        self.assertEqual(bar_symbols, ["SPY", "QQQ"])

    def test_held_position_symbols_are_in_shared_market_stream_bars(self) -> None:
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
        self.assertEqual(bar_symbols, ["SPY", "AAPL"])

    def test_market_bars_update_held_positions_outside_top_volume(self) -> None:
        engine = TraderEngine("held-bars")
        engine.config = AppConfig(symbols=["OLD"], use_top_volume_symbols=True, inverse_etf_mode="allow")
        engine.top_volume_symbols = ["MSFT", "NVDA"]
        engine.positions = [{"symbol": "AAPL", "qty_raw": "0.25"}]

        engine.ingest_market_bar(
            SimpleNamespace(
                symbol="AAPL",
                close="188.25",
                timestamp=datetime(2026, 6, 25, 14, 30),
                volume="1500",
                high="189",
                low="187",
            )
        )

        snapshot = engine.snapshot("AAPL")
        self.assertEqual(snapshot.price, Decimal("188.25"))
        self.assertEqual(snapshot.bars, 1)

    def test_market_bars_update_proxy_symbols_in_top_volume_mode(self) -> None:
        engine = TraderEngine("proxy-bars")
        engine.config = AppConfig(symbols=["OLD"], use_top_volume_symbols=True, inverse_etf_mode="allow")
        engine.top_volume_symbols = ["MSFT", "NVDA"]

        engine.ingest_market_bar(
            SimpleNamespace(
                symbol="SPY",
                close="520.10",
                timestamp=datetime(2026, 6, 25, 14, 31),
                volume="2000",
                high="521",
                low="519",
            )
        )

        snapshot = engine.snapshot("SPY")
        self.assertEqual(snapshot.price, Decimal("520.10"))
        self.assertEqual(snapshot.bars, 1)

    def test_inverse_etf_eligibility_has_no_downturn_gate(self) -> None:
        engine = TraderEngine("acct", "Inverse")
        config = AppConfig(symbols=["MSFT"], use_top_volume_symbols=True, inverse_etf_mode="allow")
        engine.config = config
        engine.top_volume_symbols = ["MSFT", "NVDA"]

        self.assertNotIn("SQQQ", engine.trading_symbols())
        self.assertEqual(engine.inverse_etf_hold_reason("SQQQ", config), "")
        self.assertFalse(hasattr(engine, "market_downturn_active"))
        self.assertFalse(hasattr(engine, "downturn_inverse_allowed"))

        engine.top_volume_symbols = ["MSFT", "SQQQ"]
        self.assertIn("SQQQ", engine.trading_symbols())

        exclude_config = AppConfig(symbols=["MSFT"], use_top_volume_symbols=True, inverse_etf_mode="exclude")
        self.assertEqual(exclude_config.inverse_etf_mode, "exclude")
        engine.config = exclude_config
        self.assertEqual(engine.inverse_etf_hold_reason("SQQQ", exclude_config), "Hold (inverse ETF excluded)")

        inverse_only_config = AppConfig(symbols=["MSFT"], use_top_volume_symbols=True, inverse_etf_mode="inverse_only")
        engine.config = inverse_only_config
        self.assertEqual(engine.trading_symbol_source(), "inverse_only")
        self.assertIn("SQQQ", engine.trading_symbols())
        self.assertNotIn("MSFT", engine.trading_symbols())


class ServerContractTests(unittest.TestCase):
    def test_health_payload_exposes_paper_only_contract(self) -> None:
        request = SimpleNamespace(base_url="http://127.0.0.1:8765/")
        payload = asyncio.run(server.get_health(request))

        self.assertIs(payload["paper_trading_only"], True)
        self.assertEqual(payload["broker_mode"], "paper")

    def test_account_connect_constructs_paper_trading_client(self) -> None:
        constructed: list[dict[str, Any]] = []

        class FakeTradingClient:
            def __init__(self, api_key: str, secret_key: str, paper: bool = False) -> None:
                constructed.append({"api_key": api_key, "secret_key": secret_key, "paper": paper})

            def get_account(self) -> Any:
                return SimpleNamespace(equity="1000", last_equity="1000")

        class FakeDataClient:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

        class FakeScreenerClient:
            def __init__(self, *_args: Any, **_kwargs: Any) -> None:
                pass

        payload = AccountPayload(
            name="Paper Test",
            api_key="PK123456789012345678901234",
            secret_key="S" * 32,
            remember=False,
            auto_connect=False,
            auto_start_trading=False,
            config=AppConfig(symbols=["SPY"], use_top_volume_symbols=False),
        )
        engine = TraderEngine("paper-contract")

        with (
            patch.object(engine_module, "TradingClient", FakeTradingClient),
            patch.object(engine_module, "StockHistoricalDataClient", FakeDataClient),
            patch.object(engine_module, "ScreenerClient", FakeScreenerClient),
            patch.object(TraderEngine, "refresh_top_volume", lambda *_args, **_kwargs: None),
            patch.object(TraderEngine, "refresh", lambda *_args, **_kwargs: None),
        ):
            engine.connect(payload)

        self.assertEqual(len(constructed), 1)
        self.assertIs(constructed[0]["paper"], True)
        self.assertEqual(engine.status, "Connected to Alpaca paper API")


if __name__ == "__main__":
    unittest.main()
