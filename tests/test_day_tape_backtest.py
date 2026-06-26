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

    def test_latest_event_window_uses_warmup_without_counting_entry_evaluations(self) -> None:
        backtest = load_backtest_module()
        events = [
            {
                "kind": "top_volume_snapshot",
                "time": "2026-06-24T20:29:00Z",
                "payload": {"source": "alpaca_most_actives_volume", "symbols": ["AAA"], "rows": [{"symbol": "AAA"}]},
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T20:30:00Z",
                "payload": {
                    "config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"},
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
                },
            },
            {
                "kind": "strategy_scan",
                "time": "2026-06-24T20:31:00Z",
                "payload": {
                    "config": {"use_top_volume_symbols": True, "inverse_etf_mode": "exclude"},
                    "top_volume_source": "alpaca_most_actives_volume",
                    "top_volume_symbols": ["AAA"],
                    "top_volume_rows": [{"symbol": "AAA"}],
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
            summary = backtest.run_backtest([tape], max_events=1, latest_events=True, warmup_events=2)

        self.assertEqual(seen, ["AAA"])
        self.assertEqual(summary["counts"]["warmup_events"], 2)
        self.assertEqual(summary["counts"]["evaluations"], 1)
        self.assertEqual(summary["top_volume_contexts_by_source"], {"alpaca_most_actives_volume": 3})
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


if __name__ == "__main__":
    unittest.main()
