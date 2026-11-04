from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import storage


@unittest.skipIf(os.name == "nt", "POSIX permission contract; Windows uses DPAPI")
class SettingsPermissionTests(unittest.TestCase):
    def test_settings_folder_and_files_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            app_dir = Path(raw_dir) / "AlpacaPaperTrader"
            settings_path = app_dir / "python-settings.json"
            with patch.object(storage, "APP_DIR", app_dir), patch.object(storage, "SETTINGS_PATH", settings_path):
                storage.save_settings({"accounts": []})
                storage.save_settings({"accounts": [1]})

                self.assertEqual(stat.S_IMODE(app_dir.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(settings_path.stat().st_mode) & 0o077, 0)
                backups = list(app_dir.glob("python-settings.json.*.bak"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode) & 0o077, 0)

    def test_settings_backups_are_capped(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            app_dir = Path(raw_dir) / "AlpacaPaperTrader"
            settings_path = app_dir / "python-settings.json"
            with (
                patch.object(storage, "APP_DIR", app_dir),
                patch.object(storage, "SETTINGS_PATH", settings_path),
                patch.object(storage, "SETTINGS_BACKUP_KEEP", 3),
            ):
                for index in range(6):
                    storage.save_settings({"saves": index})

                self.assertEqual(len(list(app_dir.glob("python-settings.json.*.bak"))), 3)
                self.assertEqual(storage.load_settings(), {"saves": 5})


if __name__ == "__main__":
    unittest.main()
