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
UI_SCRIPT = REPO_ROOT / "scripts" / "verify_ui_display.py"


def load_ui_module():
    spec = importlib.util.spec_from_file_location("verify_ui_display_under_test", UI_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {UI_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def state_payload() -> dict[str, object]:
    return {
        "_runtime_health": {"current": True, "status": "ok"},
        "accounts": [
            {"account_id": "acct-1", "name": "Private One"},
            {"account_id": "acct-2", "name": "Private Two"},
            {"account_id": "acct-3", "name": "Private Three"},
        ],
        "selected": {
            "account_id": "acct-1",
            "name": "Private One",
            "last_refresh": "09:32:45 AM",
            "account": {
                "equity_display": "$1,010.00",
                "daily_pl_display": "$10.00",
                "daily_pl_pct_display": "+1.00%",
                "daily_pl_session_date": "2026-06-25",
                "realized_pl_display": "$2.50",
                "realized_pl_session_date": "2026-06-25",
                "buying_power_display": "$500.00",
                "cash_display": "$250.00",
            },
        },
    }


def rendered_payload() -> dict[str, object]:
    return {
        "equity": "$1,010.00",
        "dailyPl": "$10.00 (+1.00%)",
        "dailyPlDetail": "Session 2026-06-25",
        "realizedPl": "$2.50",
        "realizedPlDetail": "Session 2026-06-25",
        "buyingPower": "$500.00",
        "cash": "$250.00",
        "lastRefresh": "09:32:45 AM",
        "accountCards": 3,
        "activeCardDailyPl": "$10.00 (+1.00%)",
        "runtimeWarningVisible": False,
        "runtimeWarningTitle": "Runtime warning",
    }


class UiDisplayVerifierTests(unittest.TestCase):
    def test_rendered_metrics_match_state_without_identifiers_in_report(self) -> None:
        module = load_ui_module()
        report = module.verify_rendered_payload(state_payload(), rendered_payload())

        self.assertTrue(report["ok"], report["checks"])
        rendered = json.dumps(report)
        self.assertNotIn("acct-1", rendered)
        self.assertNotIn("Private One", rendered)

    def test_rendered_daily_pl_mismatch_fails(self) -> None:
        module = load_ui_module()
        rendered = deepcopy(rendered_payload())
        rendered["dailyPl"] = "$0.00 (0.00%)"

        report = module.verify_rendered_payload(state_payload(), rendered)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("ui.dailyPl", failed)

    def test_current_backend_fails_if_stale_runtime_warning_is_visible(self) -> None:
        module = load_ui_module()
        rendered = deepcopy(rendered_payload())
        rendered["runtimeWarningVisible"] = True
        rendered["runtimeWarningTitle"] = "Stale runtime warning"

        report = module.verify_rendered_payload(state_payload(), rendered)
        failed = {item["name"] for item in report["checks"] if not item["ok"]}

        self.assertFalse(report["ok"])
        self.assertIn("ui.stale_runtime_warning_hidden", failed)

    def test_stale_backend_requires_stale_runtime_warning(self) -> None:
        module = load_ui_module()
        state = deepcopy(state_payload())
        state["_runtime_health"] = {"current": False, "status": "stale"}
        rendered = deepcopy(rendered_payload())
        rendered["runtimeWarningVisible"] = True
        rendered["runtimeWarningTitle"] = "Stale runtime warning"

        report = module.verify_rendered_payload(state, rendered)

        self.assertTrue(report["ok"], report["checks"])


if __name__ == "__main__":
    unittest.main()
