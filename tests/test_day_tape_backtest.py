from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKTEST_PATH = REPO_ROOT / "scripts" / "day_tape_backtest.py"


def load_backtest_module():
    spec = importlib.util.spec_from_file_location("day_tape_backtest_under_test", BACKTEST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BACKTEST_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_tape(raw_dir: str, events: list[dict[str, Any]]) -> Path:
    path = Path(raw_dir) / "tape-20260624.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    return path


class FakeSnapshot:
    price = backtest_price = None

    def __init__(self, symbol: str, price: str = "10") -> None:
        self.symbol = symbol
        self.price = Decimal(price)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_score_raw": 55.0,
            "rsi_raw": 50.0,
            "momentum_raw": 1.5,
            "recent_momentum_raw": 0.5,
            "long_momentum_raw": 2.0,
            "session_change_raw": 2.5,
            "vwap_distance_raw": 0.4,
            "smi_raw": 60.0,
            "atr_raw": 1.1,
            "volatility_raw": 1.2,
        }


class DayTapeBacktestTests(unittest.TestCase):
    def test_backtest_uses_recorded_top_volume_universe_not_fallback_symbols(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T14:30:00Z",
                "payload": {
                    "source": "alpaca_most_actives_volume",
                    "symbols": ["AAA", "BBB"],
                    "rows": [{"symbol": "AAA"}, {"symbol": "BBB"}],
                },
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T14:31:00Z",
                "payload": {
                    "config": {
                        "symbols": ["MANUAL"],
                        "use_top_volume_symbols": True,
                        "inverse_etf_mode": "exclude",
                    }
                },
            },
        ]
        seen: list[str] = []

        def fake_entry_candidate(self, symbol, *_args):
            seen.append(symbol)
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape])

        self.assertEqual(seen, ["AAA", "BBB"])
        self.assertEqual(summary["top_volume_sources"], ["alpaca_most_actives_volume"])
        self.assertEqual(summary["expected_top_volume_source"], "alpaca_most_actives_volume")
        self.assertEqual(summary["top_volume_snapshots_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["evaluations_by_top_volume_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["selection_engine"], "app_engine")

    def test_latest_event_window_reads_post_cutover_source_at_end_of_tape(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T14:30:00Z",
                "payload": {"source": "sp500_snapshot_volume", "symbols": ["OLD"], "rows": [{"symbol": "OLD"}]},
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T14:31:00Z",
                "payload": {"config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"}},
            },
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T20:30:00Z",
                "payload": {"source": "alpaca_most_actives_volume", "symbols": ["AAA"], "rows": [{"symbol": "AAA"}]},
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T20:31:00Z",
                "payload": {"config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"}},
            },
        ]
        seen: list[str] = []

        def fake_entry_candidate(self, symbol, *_args):
            seen.append(symbol)
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape], max_events=2, latest_events=True)

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["top_volume_sources"], ["alpaca_most_actives_volume"])
        self.assertEqual(summary["top_volume_snapshots_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["evaluations_by_top_volume_source"], {"alpaca_most_actives_volume": 1})

    def test_strategy_scan_embedded_top_volume_context_is_replayable(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T14:30:00Z",
                "payload": {"source": "sp500_snapshot_volume", "symbols": ["OLD"], "rows": [{"symbol": "OLD"}]},
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T20:31:00Z",
                "payload": {
                    "config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"},
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                    "top_volume_updated_at": "2026-06-24T20:30:00Z",
                },
            },
        ]
        seen: list[str] = []

        def fake_entry_candidate(self, symbol, *_args):
            seen.append(symbol)
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape], max_events=1, latest_events=True)

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["top_volume_snapshots_by_source"], {})
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["counts"]["strategy_scan_top_volume_contexts"], 1)
        self.assertEqual(summary["evaluations_by_top_volume_source"], {"alpaca_most_actives_volume": 1})

    def test_disabled_trading_strategy_scan_still_proves_replay_universe(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "strategy_scan",
                "time": "2026-06-25T14:31:00Z",
                "payload": {
                    "trading_enabled": False,
                    "should_trade": False,
                    "config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"},
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                    "top_volume_updated_at": "2026-06-25T14:30:00Z",
                },
            },
        ]
        seen: list[str] = []

        def fake_entry_candidate(self, symbol, *_args):
            seen.append(symbol)
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape], latest_events=True)

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["evaluations_by_top_volume_source"], {"alpaca_most_actives_volume": 1})

    def test_replay_harness_forces_top_volume_context_over_manual_scan_config(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T20:31:00Z",
                "payload": {
                    "config": {
                        "symbols": ["MANUAL"],
                        "use_top_volume_symbols": False,
                        "inverse_etf_mode": "exclude",
                    },
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                    "top_volume_updated_at": "2026-06-24T20:30:00Z",
                },
            },
        ]
        seen: list[str] = []

        def fake_entry_candidate(self, symbol, *_args):
            seen.append(symbol)
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape], latest_events=True)

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 1})
        self.assertEqual(summary["evaluations_by_top_volume_source"], {"alpaca_most_actives_volume": 1})

    def test_backtest_accepts_entries_with_app_engine_label_and_fixed_sizing(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T14:30:00Z",
                "payload": {
                    "source": "alpaca_most_actives_volume",
                    "symbols": ["AAA"],
                    "rows": [{"symbol": "AAA"}],
                },
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T14:31:00Z",
                "payload": {
                    "config": {
                        "symbols": ["MANUAL"],
                        "use_top_volume_symbols": True,
                        "inverse_etf_mode": "exclude",
                    }
                },
            },
        ]

        def fake_entry_candidate(_self, symbol, rank, *_args):
            return {"symbol": symbol, "rank": rank, "score": backtest.Decimal("55")}

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
            patch.object(backtest.TraderEngine, "snapshot", lambda _self, symbol: FakeSnapshot(symbol)),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest([tape])

        self.assertEqual(summary["counts"]["accepted_trades"], 1)
        self.assertEqual(summary["accepted_trades"][0]["symbol"], "AAA")
        self.assertEqual(summary["accepted_trades"][0]["selection_engine"], "app_engine")
        self.assertEqual(summary["accepted_trades"][0]["universe_source"], "top_volume")
        self.assertEqual(summary["accepted_trades"][0]["top_volume_source"], "alpaca_most_actives_volume")
        self.assertEqual(summary["sizing_harness"]["starting_equity"], "1000")
        self.assertEqual(summary["sizing_harness"]["trade_percent"], "5")
        self.assertEqual(summary["sizing_harness"]["max_positions"], 20)

    def test_strategy_overrides_apply_after_recorded_scan_config(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T14:31:00Z",
                "payload": {
                    "config": {
                        "use_top_volume_symbols": True,
                        "inverse_etf_mode": "exclude",
                        "min_entry_score": "44",
                        "score_weight_momentum": "20",
                    },
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                },
            }
        ]
        observed: list[tuple[str, str]] = []

        def fake_entry_candidate(self, symbol, *_args):
            observed.append((str(self.config.min_entry_score), str(self.config.score_weight_momentum)))
            self.strategy_state.last_action[symbol] = "Hold (synthetic)"
            return None

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest(
                [tape],
                strategy_overrides={"min_entry_score": 52, "score_weight_momentum": 30},
                latest_events=True,
            )

        self.assertEqual(observed, [("52", "30")])
        self.assertEqual(summary["strategy_overrides"]["min_entry_score"], 52)
        self.assertEqual(summary["strategy_overrides"]["score_weight_momentum"], 30)

    def test_sizing_overrides_change_replay_quantity_without_selecting_symbols(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T14:31:00Z",
                "payload": {
                    "config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"},
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                },
            }
        ]
        seen: list[str] = []

        def fake_entry_candidate(_self, symbol, rank, *_args):
            seen.append(symbol)
            return {"symbol": symbol, "rank": rank, "score": backtest.Decimal("55")}

        with (
            tempfile.TemporaryDirectory() as raw_dir,
            patch.object(backtest.TraderEngine, "entry_candidate", fake_entry_candidate),
            patch.object(backtest.TraderEngine, "snapshot", lambda _self, symbol: FakeSnapshot(symbol, price="10")),
        ):
            tape = write_tape(raw_dir, events)
            summary = backtest.run_backtest(
                [tape],
                sizing_overrides={
                    "starting_equity": 5000,
                    "starting_cash": 5000,
                    "trade_size_mode": "percent",
                    "trade_percent": 10,
                    "max_positions": 20,
                    "total_exposure_percent": 100,
                },
                latest_events=True,
            )

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["accepted_trades"][0]["notional"], "250.000000")
        self.assertEqual(summary["accepted_trades"][0]["qty"], "25.0000")
        self.assertEqual(summary["sizing_harness"]["starting_equity"], "5000")
        self.assertEqual(summary["sizing_harness"]["trade_percent"], "10")

    def test_replay_config_forces_most_active_universe_mode(self) -> None:
        backtest = load_backtest_module()
        with (
            patch.object(backtest, "AppConfig", side_effect=lambda **kw: kw),
            patch.object(backtest, "retune_strategy_config", side_effect=lambda c: c),
        ):
            config = backtest.replay_config({"universe_mode": "daily_rvol"})
            self.assertEqual(config["universe_mode"], "most_active")

            config = backtest.replay_config(None, {"universe_mode": "daily_rvol"})
            self.assertEqual(config["universe_mode"], "most_active")



class EntryGuardReplayTests(unittest.TestCase):
    """Replay applies the live open/close entry guards (it used to buy from the 09:30 open)."""

    def scan(self, utc: str, display: str, next_close: str = "") -> dict[str, Any]:
        clock = {"is_open": True, "next_close": next_close} if next_close else {}
        return {"kind": "strategy_scan", "time": utc, "time_display": display, "payload": {"market_clock": clock}}

    def held(self, backtester: Any, event: dict[str, Any]) -> bool:
        before = backtester.entry_guard_holds
        with patch.object(backtester.boundary.strategy, "entry_candidate", return_value=None):
            backtester.handle_event(event)
        return backtester.entry_guard_holds > before

    def test_open_and_close_guards_hold_entries_like_live(self) -> None:
        backtest = load_backtest_module()
        replay = backtest.DayTapeBacktester(
            strategy_overrides={"entry_open_guard_minutes": 60, "entry_close_guard_minutes": 30}
        )
        # 2026-11-06 is a regular day (EST): open 14:30Z, close 21:00Z; no recorded clock -> 16:00 ET
        self.assertTrue(self.held(replay, self.scan("2026-11-06T14:45:00+00:00", "08:45:00")))
        self.assertTrue(self.held(replay, self.scan("2026-11-06T15:29:00+00:00", "09:29:00")))
        self.assertFalse(self.held(replay, self.scan("2026-11-06T15:31:00+00:00", "09:31:00")))
        self.assertFalse(self.held(replay, self.scan("2026-11-06T20:29:00+00:00", "14:29:00")))
        self.assertTrue(self.held(replay, self.scan("2026-11-06T20:31:00+00:00", "14:31:00")))
        self.assertEqual(replay.summary()["counts"]["entry_guard_holds"], 3)
        self.assertEqual(replay.summary()["counts"]["evaluations"], 2)

    def test_zero_guards_allow_entries_all_session(self) -> None:
        backtest = load_backtest_module()
        replay = backtest.DayTapeBacktester(
            strategy_overrides={"entry_open_guard_minutes": 0, "entry_close_guard_minutes": 0}
        )
        self.assertFalse(self.held(replay, self.scan("2026-11-06T14:31:00+00:00", "08:31:00")))
        self.assertFalse(self.held(replay, self.scan("2026-11-06T20:59:00+00:00", "14:59:00")))

    def test_half_day_close_comes_from_the_recorded_clock(self) -> None:
        backtest = load_backtest_module()
        replay = backtest.DayTapeBacktester(
            strategy_overrides={"entry_open_guard_minutes": 15, "entry_close_guard_minutes": 30}
        )
        # 2026-11-27 closes 13:00 ET (18:00Z), recorded on a CST machine as 12:00 PM
        half_day = "Nov 27, 12:00 PM CST"
        self.assertFalse(self.held(replay, self.scan("2026-11-27T17:25:00+00:00", "11:25:00", half_day)))
        self.assertTrue(self.held(replay, self.scan("2026-11-27T17:35:00+00:00", "11:35:00", half_day)))
        close = backtest.recorded_session_close(
            self.scan("2026-11-27T17:35:00+00:00", "11:35:00", half_day),
            {"market_clock": {"is_open": True, "next_close": half_day}},
        )
        self.assertEqual(close.astimezone(backtest.MARKET_TIMEZONE).strftime("%H:%M"), "13:00")

if __name__ == "__main__":
    unittest.main()
