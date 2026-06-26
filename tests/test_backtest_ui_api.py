from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import server


class FakeBacktestModule:
    def __init__(self, files: list[Path] | None = None) -> None:
        self.files = files if files is not None else [Path("tape-20260625.jsonl")]
        self.calls: list[dict[str, object]] = []

    def default_tape_dir(self) -> Path:
        return Path("C:/safe/day-tape")

    def selected_files(self, path: Path, days: int) -> list[Path]:
        self.calls.append({"path": str(path), "days": days})
        return list(self.files)

    def run_backtest(
        self,
        files: list[Path],
        max_events: int,
        *,
        latest_events: bool = False,
        warmup_events: int = 0,
        strategy_overrides: dict[str, object] | None = None,
        sizing_overrides: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "files": [item.name for item in files],
                "max_events": max_events,
                "latest_events": latest_events,
                "warmup_events": warmup_events,
                "strategy_overrides": dict(strategy_overrides or {}),
                "sizing_overrides": dict(sizing_overrides or {}),
            }
        )
        return {
            "selection_engine": "app_engine",
            "strategy_overrides": dict(strategy_overrides or {}),
            "sizing_harness": {
                "starting_equity": "1000",
                "starting_cash": "1000",
                "trade_size_mode": "percent",
                "max_positions": 20,
                "trade_percent": "5",
                "trade_notional": "0",
                "total_exposure_percent": "100",
                "diagnostic": bool(sizing_overrides),
            },
            "counts": {
                "evaluations": 2,
                "accepted_trades": 1,
                "closed_trades": 0,
                "open_positions": 1,
                "rejected_candidates": 4,
                "parse_errors": 0,
                "warmup_events": warmup_events,
            },
            "top_volume_sources": ["alpaca_most_actives_volume"],
            "expected_top_volume_source": "alpaca_most_actives_volume",
            "top_volume_contexts_by_source": {"alpaca_most_actives_volume": 2},
            "evaluations_by_top_volume_source": {"alpaca_most_actives_volume": 2},
            "accepted_trades": [{"symbol": "AAA", "score": "55", "entry_price": "10"}],
            "closed_trades": [],
            "rejected_candidates_sample": [{"symbol": "BBB", "reason": "Hold (synthetic)"}],
            "winner_indicator_averages": {},
            "loser_indicator_averages": {},
        }


class BacktestUiApiTests(unittest.TestCase):
    def test_day_tape_backtest_report_runs_engine_backtest_and_returns_checks(self) -> None:
        fake = FakeBacktestModule()
        payload = server.DayTapeBacktestPayload(
            days=1,
            max_events=50000,
            latest_events=True,
            warmup_events=25000,
            strategy_overrides={"min_entry_score": 50, "score_weight_momentum": 25},
            sizing_overrides={"starting_equity": 5000, "trade_size_mode": "percent", "trade_percent": 4},
        )

        with patch.object(server, "_day_tape_backtest_module", fake):
            report = server.day_tape_backtest_report(payload)

        self.assertTrue(report["ok"])
        self.assertEqual(report["files"], ["tape-20260625.jsonl"])
        self.assertEqual(report["parameters"]["max_events"], 50000)
        self.assertEqual(report["parameters"]["warmup_events"], 25000)
        self.assertEqual(report["parameters"]["strategy_overrides"]["min_entry_score"], 50)
        self.assertEqual(fake.calls[-1]["strategy_overrides"]["score_weight_momentum"], 25)
        self.assertEqual(fake.calls[-1]["sizing_overrides"]["starting_equity"], 5000)
        self.assertEqual(fake.calls[-1]["warmup_events"], 25000)
        self.assertEqual(report["summary"]["selection_engine"], "app_engine")
        checks = {item["name"]: item for item in report["checks"]}
        self.assertTrue(checks["selection_engine"]["ok"])
        self.assertTrue(checks["sizing_harness"]["ok"])
        self.assertTrue(checks["expected_source_evaluations"]["ok"])
        self.assertEqual(fake.calls[-1]["latest_events"], True)

    def test_day_tape_backtest_report_returns_pending_when_no_tape_files_exist(self) -> None:
        fake = FakeBacktestModule(files=[])
        payload = server.DayTapeBacktestPayload(days=1, max_events=50000, latest_events=True)

        with patch.object(server, "_day_tape_backtest_module", fake):
            report = server.day_tape_backtest_report(payload)

        self.assertFalse(report["ok"])
        self.assertEqual(report["pending"], "No day-tape files found.")
        self.assertEqual(report["files"], [])
        self.assertEqual(report["checks"][0]["name"], "day_tape_files")
        self.assertFalse(report["checks"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
