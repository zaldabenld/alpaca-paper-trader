from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

from .helpers import configure_test_environment


configure_test_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER_SCRIPT = REPO_ROOT / "scripts" / "verify_live_contract.py"


def load_verifier_module():
    spec = importlib.util.spec_from_file_location("verify_live_contract_under_test", VERIFIER_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {VERIFIER_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def top_volume_rows() -> list[dict[str, object]]:
    return [
        {
            "rank": index,
            "symbol": f"SYM{index}",
            "daily_volume_raw": 1000000 + index,
        }
        for index in range(1, 26)
    ]


def top_volume_symbols() -> list[str]:
    return [f"SYM{index}" for index in range(1, 26)]


def selected_account(account_id: str, daily: str = "10", pct: str = "1") -> dict[str, object]:
    return {
        "account_id": account_id,
        "name": "Private Account",
        "connected": True,
        "trading_enabled": False,
        "market_clock": {
            "is_open": True,
            "status": "Open",
            "session_date": "2026-06-25",
            "next_open": "Jun 26, 08:30 AM Central Daylight Time",
            "next_close": "Jun 25, 03:00 PM Central Daylight Time",
        },
        "account": {
            "equity": "1010",
            "last_equity": "1000",
            "daily_pl_raw": daily,
            "daily_pl_display": "$10.00",
            "daily_pl_pct_raw": pct,
            "daily_pl_pct_display": "+1.00%",
            "daily_pl_account_basis_raw": "1000",
            "daily_pl_session_date": "2026-06-25",
            "daily_pl_source": "alpaca_portfolio_history",
            "daily_pl_source_error": "",
            "realized_pl_raw": "0",
            "realized_pl_display": "$0.00",
            "realized_pl_session_date": "2026-06-25",
        },
        "config": {
            "use_top_volume_symbols": True,
            "trade_size_mode": "percent",
            "max_trade_notional": "0",
            "max_trade_percent": "5",
        },
        "positions": [],
        "orders": [],
        "protection": [],
        "trade_history": [],
        "order_intents": [],
        "strategy": [],
        "logs": [],
        "trading_symbols": top_volume_symbols(),
        "symbol_source": "top_volume",
        "trading_symbol_count": 25,
    }


def passing_payload() -> dict[str, object]:
    accounts = [
        {
            "account_id": f"acct-{index}",
            "name": "Private Account",
            "connected": True,
            "symbol_source": "top_volume",
            "trading_symbol_count": 25,
        }
        for index in range(1, 4)
    ]
    return {
        "shortcut_ok": True,
        "shortcut_issues": [],
        "launcher_contract": {
            "exists": True,
            "uses_health_currentness": True,
            "preserves_instance_while_starting": True,
            "hidden_backend_launch": True,
            "hidden_smoke_check": True,
            "edge_app_mode": True,
        },
        "health": {
            "current": True,
            "status": "ok",
            "url": "http://127.0.0.1:8765",
            "pid": 222,
            "paper_trading_only": True,
            "broker_mode": "paper",
        },
        "instance": {
            "url": "http://127.0.0.1:8765",
            "pid": 222,
        },
        "instance_path": "C:/Users/example/AppData/Local/AlpacaPaperTrader/instance.json",
        "process_pids": [222],
        "listener_pids": [222],
        "state": {
            "accounts": accounts,
            "settings_diagnostics": {"error_count": 0},
            "runtime_diagnostics": {"error_count": 0},
        },
        "settings": {
            "accounts": accounts,
            "settings_diagnostics": {"error_count": 0},
        },
        "dashboard": {
            "top_volume_source": "alpaca_most_actives_volume",
            "top_volume": top_volume_rows(),
            "top_volume_error": "",
            "top_volume_cache_seconds": 60,
            "market_stream": {
                "status": "Subscribed",
                "connected": True,
                "dashboard_symbols": 25,
                "bar_symbols": 25,
                "last_error": "",
            },
        },
        "account_states": [
            {"selected": selected_account("acct-1"), "replay": {"path": "C:/safe/replay.jsonl", "events": []}},
            {"selected": selected_account("acct-2"), "replay": {"path": "C:/safe/replay.jsonl", "events": []}},
            {"selected": selected_account("acct-3"), "replay": {"path": "C:/safe/replay.jsonl", "events": []}},
        ],
        "account_dashboards": [
            {
                "market_clock": {"is_open": True, "status": "Open"},
                "top_volume": top_volume_rows(),
                "halt_summary": {"items": []},
                "market_stream": {"status": "Connected"},
                "replay": {"path": "C:/safe/replay.jsonl", "events": []},
            },
            {
                "market_clock": {"is_open": True, "status": "Open"},
                "top_volume": top_volume_rows(),
                "halt_summary": {"items": []},
                "market_stream": {"status": "Connected"},
                "replay": {"path": "C:/safe/replay.jsonl", "events": []},
            },
            {
                "market_clock": {"is_open": True, "status": "Open"},
                "top_volume": top_volume_rows(),
                "halt_summary": {"items": []},
                "market_stream": {"status": "Connected"},
                "replay": {"path": "C:/safe/replay.jsonl", "events": []},
            },
        ],
    }


class LiveContractVerifierTests(unittest.TestCase):
    def test_process_parser_ignores_smoke_checks(self) -> None:
        module = load_verifier_module()
        rows = [
            {"pid": 111, "command_line": "pythonw.exe python_app\\run.py --no-browser"},
            {"pid": 222, "command_line": "python.exe python_app\\run.py --smoke"},
            {"pid": 333, "command_line": "python.exe python_app\\run.py --host 127.0.0.1"},
        ]

        self.assertEqual(module.parse_process_pids(rows), [111, 333])
        self.assertEqual(module.parse_pid_list([111, "333", 0, "bad"]), [111, 333])

    def test_single_listener_allows_venv_launcher_wrapper_process(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["process_pids"] = [111, 222]
        payload["listener_pids"] = [222]

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertTrue(report["ok"], report["checks"])
        self.assertNotIn("backend.single_process", failed)

    def test_multiple_listeners_fail_even_if_command_line_scan_is_ambiguous(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["process_pids"] = [111, 222]
        payload["listener_pids"] = [111, 222]

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("backend.single_process", failed)

    def test_passing_payload_verifies_without_account_identifiers_in_report(self) -> None:
        module = load_verifier_module()
        report = module.verify_payload(passing_payload())

        self.assertTrue(report["ok"], report["checks"])
        rendered = json.dumps(report)
        self.assertNotIn("acct-1", rendered)
        self.assertNotIn("Private Account", rendered)

    def test_stale_runtime_and_conflicting_sizing_fail(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["health"]["current"] = False
        payload["health"]["status"] = "stale"
        payload["dashboard"]["top_volume_source"] = ""
        payload["dashboard"]["top_volume_cache_seconds"] = 600
        selected = payload["account_states"][0]["selected"]
        selected["account"]["daily_pl_raw"] = "0"
        selected["config"]["max_trade_notional"] = "20"

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("backend.current", failed)
        self.assertIn("account_1.sizing_mode", failed)
        self.assertIn("account_1.daily_pl_percent_source", failed)
        self.assertIn("top_volume.source", failed)
        self.assertIn("top_volume.cache_seconds", failed)

    def test_daily_pl_session_dates_must_match_market_clock_session(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        selected = payload["account_states"][0]["selected"]
        selected["account"]["daily_pl_session_date"] = "2026-06-24"
        selected["account"]["realized_pl_session_date"] = "2026-06-24"

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("account_1.daily_pl_session_date", failed)
        self.assertIn("account_1.realized_pl_session_date", failed)

    def test_daily_pl_must_come_from_portfolio_history_source(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        selected = payload["account_states"][0]["selected"]
        selected["account"]["daily_pl_source"] = "equity_last_equity"

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("account_1.daily_pl_source", failed)
        self.assertIn("account_1.daily_pl_percent_source", failed)

    def test_missing_paper_only_health_contract_fails(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["health"]["paper_trading_only"] = False
        payload["health"]["broker_mode"] = "live"

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("backend.paper_only", failed)

    def test_missing_per_account_surfaces_fail(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        selected = payload["account_states"][0]["selected"]
        selected.pop("trading_enabled")
        selected.pop("positions")
        payload["account_states"][0].pop("replay")
        payload["account_dashboards"][0] = {"_error": "synthetic failure"}

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("account_1.trading_enabled", failed)
        self.assertIn("account_1.state_surfaces", failed)
        self.assertIn("account_1.replay_surface", failed)
        self.assertIn("account_1.dashboard_surface", failed)

    def test_market_clock_check_reports_open_status_and_session(self) -> None:
        module = load_verifier_module()
        report = module.verify_payload(passing_payload())
        market_clock = next(item for item in report["checks"] if item["name"] == "account_1.market_clock")

        self.assertTrue(market_clock["ok"])
        self.assertIn("is_open=True", market_clock["detail"])
        self.assertIn("status=Open", market_clock["detail"])
        self.assertIn("session=2026-06-25", market_clock["detail"])
        self.assertIn("next_open=Jun 26, 08:30 AM Central Daylight Time", market_clock["detail"])
        self.assertIn("next_close=Jun 25, 03:00 PM Central Daylight Time", market_clock["detail"])

    def test_missing_launcher_contract_checks_fail(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["launcher_contract"]["hidden_backend_launch"] = False
        payload["launcher_contract"]["edge_app_mode"] = False
        payload["launcher_contract"]["preserves_instance_while_starting"] = False

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("launcher.instance_startup_guard", failed)
        self.assertIn("launcher.hidden_backend", failed)
        self.assertIn("launcher.edge_app_mode", failed)

    def test_top_volume_accounts_must_not_append_hardcoded_symbols(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        selected = payload["account_states"][0]["selected"]
        selected["trading_symbols"] = top_volume_symbols() + ["SQQQ"]
        selected["trading_symbol_count"] = 26
        payload["state"]["accounts"][0]["trading_symbol_count"] = 26

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("account_1.top_volume_universe", failed)

    def test_market_stream_health_must_cover_dashboard_symbols_without_error(self) -> None:
        module = load_verifier_module()
        payload = deepcopy(passing_payload())
        payload["dashboard"]["market_stream"]["last_error"] = "connection limit exceeded"
        payload["dashboard"]["market_stream"]["dashboard_symbols"] = 24
        payload["dashboard"]["market_stream"]["bar_symbols"] = 20

        report = module.verify_payload(payload)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("market_stream.error", failed)
        self.assertIn("market_stream.dashboard_symbols", failed)
        self.assertIn("market_stream.bar_symbols", failed)


if __name__ == "__main__":
    unittest.main()
