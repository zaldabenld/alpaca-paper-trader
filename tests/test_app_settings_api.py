from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import server, storage
from alpaca_desktop.app_settings import AppWideSettings

from .test_api_lockdown import TOKEN, call
from .test_regression_baselines import patched_server_manager, patched_storage_paths


class AppSettingsApiTests(unittest.TestCase):
    def test_saved_settings_persist_and_come_back(self) -> None:
        with patched_storage_paths() as (_, settings_path), patched_server_manager({}) as manager:
            with patch.object(server, "load_settings", side_effect=storage.load_settings):
                status, _, content = call(
                    "POST", "/api/app-settings", headers=TOKEN,
                    body={"daily_pick_minutes_after_open": 30, "rvol_lookback_sessions": 10, "rvol_min_sessions": 40},
                )
                self.assertEqual(status, 200, content)
                saved = json.loads(settings_path.read_text(encoding="utf-8"))["app_settings"]
                self.assertEqual(saved["daily_pick_minutes_after_open"], 30)
                self.assertEqual(saved["rvol_min_sessions"], 10)  # clamped to the lookback
                self.assertEqual(manager.app_settings.daily_pick_minutes_after_open, 30)

                status, _, content = call("GET", "/api/settings")
                self.assertEqual(status, 200, content)
                self.assertEqual(json.loads(content)["app_settings"]["rvol_lookback_sessions"], 10)

    def test_endpoint_needs_the_token(self) -> None:
        status, _, _ = call("POST", "/api/app-settings", body={"daily_pick_minutes_after_open": 30})
        self.assertEqual(status, 403)

    def test_missing_settings_load_the_defaults(self) -> None:
        with patched_server_manager({"accounts": []}) as manager:
            server.load_saved_settings_to_manager()
            self.assertEqual(manager.app_settings, AppWideSettings())
            self.assertFalse(manager.app_settings_load_failed)

    def test_bad_saved_settings_run_on_defaults_and_are_not_overwritten(self) -> None:
        bad = {"daily_pick_minutes_after_open": "soon"}
        with patched_storage_paths() as (_, settings_path):
            storage.save_settings({"accounts": [], "app_settings": bad})
            with patched_server_manager(storage.load_settings()) as manager:
                server.load_saved_settings_to_manager()
                self.assertTrue(manager.app_settings_load_failed)
                self.assertEqual(manager.app_settings, AppWideSettings())
                self.assertTrue(any(item["source"] == "app_settings" for item in manager.settings_load_errors))
                with patch.object(server, "load_settings", side_effect=storage.load_settings):
                    server.save_manager_settings()
                self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["app_settings"], bad)


if __name__ == "__main__":
    unittest.main()
