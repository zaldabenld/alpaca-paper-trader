from __future__ import annotations

import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "pre_live_backup.py"


def load_backup_module():
    spec = importlib.util.spec_from_file_location("pre_live_backup_under_test", BACKUP_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BACKUP_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PreLiveBackupTests(unittest.TestCase):
    def test_dry_run_does_not_copy_app_data(self) -> None:
        module = load_backup_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "AlpacaPaperTrader"
            backup_root = root / "backups"
            source.mkdir()
            (source / "python-settings.json").write_text('{"encrypted":"blob"}', encoding="utf-8")
            (source / "instance.json").write_text('{"url":"http://127.0.0.1:8765"}', encoding="utf-8")
            (source / "day-tape").mkdir()
            (source / "day-tape" / "tape-20260624.jsonl").write_text("{}\n", encoding="utf-8")

            output = io.StringIO()
            with patch.object(module, "app_data_dir", return_value=source), redirect_stdout(output):
                exit_code = module.build_backup(execute=False, backup_root=backup_root)

            self.assertEqual(exit_code, 0)
            self.assertFalse(backup_root.exists())
            self.assertIn("Dry run only", output.getvalue())

    def test_execute_copies_core_files_and_dirs(self) -> None:
        module = load_backup_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "AlpacaPaperTrader"
            backup_root = root / "backups"
            source.mkdir()
            (source / "python-settings.json").write_text("settings", encoding="utf-8")
            (source / "instance.json").write_text("instance", encoding="utf-8")
            (source / "dashboard-cache.json").write_text("cache", encoding="utf-8")
            (source / "replay").mkdir()
            (source / "replay" / "events.jsonl").write_text("{}\n", encoding="utf-8")
            (source / "day-tape").mkdir()
            (source / "day-tape" / "tape-20260624.jsonl").write_text("{}\n", encoding="utf-8")

            output = io.StringIO()
            with patch.object(module, "app_data_dir", return_value=source), redirect_stdout(output):
                exit_code = module.build_backup(execute=True, backup_root=backup_root)

            self.assertEqual(exit_code, 0)
            backups = list(backup_root.iterdir())
            self.assertEqual(len(backups), 1)
            backup = backups[0]
            self.assertEqual((backup / "python-settings.json").read_text(encoding="utf-8"), "settings")
            self.assertTrue((backup / "replay" / "events.jsonl").exists())
            self.assertTrue((backup / "day-tape" / "tape-20260624.jsonl").exists())
            self.assertIn("Backup complete", output.getvalue())

    def test_execute_aborts_before_copy_when_destination_space_is_too_small(self) -> None:
        module = load_backup_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "AlpacaPaperTrader"
            backup_root = root / "backups"
            source.mkdir()
            (source / "python-settings.json").write_text("settings", encoding="utf-8")
            (source / "day-tape").mkdir()
            (source / "day-tape" / "tape-20260624.jsonl").write_text("0123456789", encoding="utf-8")

            output = io.StringIO()
            with (
                patch.object(module, "app_data_dir", return_value=source),
                patch.object(module, "available_bytes", return_value=1),
                redirect_stdout(output),
            ):
                exit_code = module.build_backup(execute=True, backup_root=backup_root)

            self.assertEqual(exit_code, 1)
            self.assertFalse(backup_root.exists())
            self.assertIn("Backup aborted", output.getvalue())

    def test_execute_reuses_latest_backup_for_unchanged_files_when_space_is_tight(self) -> None:
        module = load_backup_module()
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            source = root / "AlpacaPaperTrader"
            backup_root = root / "backups"
            previous = backup_root / "20260625T000000Z"
            source.mkdir()
            previous.mkdir(parents=True)
            source_file = source / "python-settings.json"
            previous_file = previous / "python-settings.json"
            source_file.write_text("settings", encoding="utf-8")
            shutil.copy2(source_file, previous_file)

            output = io.StringIO()
            with (
                patch.object(module, "app_data_dir", return_value=source),
                patch.object(module, "available_bytes", return_value=1),
                redirect_stdout(output),
            ):
                exit_code = module.build_backup(execute=True, backup_root=backup_root)

            self.assertEqual(exit_code, 0)
            backups = sorted(item for item in backup_root.iterdir() if item.is_dir())
            self.assertEqual(len(backups), 2)
            latest = backups[-1]
            self.assertTrue((latest / "python-settings.json").samefile(previous_file))
            self.assertIn("Reusable unchanged bytes", output.getvalue())


if __name__ == "__main__":
    unittest.main()
