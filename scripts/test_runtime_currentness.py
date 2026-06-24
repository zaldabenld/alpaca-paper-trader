from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_APP = REPO_ROOT / "python_app"
if str(PYTHON_APP) not in sys.path:
    sys.path.insert(0, str(PYTHON_APP))

from alpaca_desktop import currentness


def load_run_module():
    spec = importlib.util.spec_from_file_location("alpaca_run_for_test", PYTHON_APP / "run.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load python_app/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeCurrentnessTests(unittest.TestCase):
    def test_source_stamp_changes_when_supported_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            app_file = root / "app.py"
            ignored_file = root / "notes.txt"
            app_file.write_text("print('one')\n", encoding="utf-8")
            ignored_file.write_text("ignored", encoding="utf-8")

            first = currentness.source_stamp(root)
            ignored_file.write_text("ignored but changed", encoding="utf-8")
            self.assertEqual(first, currentness.source_stamp(root))

            app_file.write_text("print('two')\n", encoding="utf-8")
            self.assertNotEqual(first, currentness.source_stamp(root))

    def test_currentness_payload_reports_stale_source_stamp(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            (root / "app.py").write_text("print('current')\n", encoding="utf-8")

            payload = currentness.currentness_payload(
                url="http://127.0.0.1:8765",
                expected_source_stamp="not-the-current-stamp",
                source_root=root,
                pid=123,
                started_at="2026-06-24T00:00:00+00:00",
            )

            self.assertFalse(payload["current"])
            self.assertEqual(payload["status"], "stale")
            self.assertEqual(payload["pid"], 123)
            self.assertIn("source_stamp", payload)
            self.assertIn("expected_source_stamp", payload)

    def test_run_py_reuses_only_same_source_current_health(self) -> None:
        run_module = load_run_module()
        valid_health = {
            "current": True,
            "source_stamp": currentness.source_stamp(),
            "source_path": str(currentness.ROOT),
        }
        self.assertTrue(run_module.health_matches_current_source(valid_health))

        stale_health = dict(valid_health)
        stale_health["source_stamp"] = "old"
        self.assertFalse(run_module.health_matches_current_source(stale_health))

        wrong_path_health = dict(valid_health)
        wrong_path_health["source_path"] = str(REPO_ROOT)
        self.assertFalse(run_module.health_matches_current_source(wrong_path_health))

    def test_main_cmd_has_no_legacy_powershell_fallback(self) -> None:
        launcher = (REPO_ROOT / "Launch Alpaca Paper Trader.cmd").read_text(encoding="utf-8")
        self.assertNotIn("src\\App.ps1", launcher)
        self.assertIn("Python virtualenv is missing", launcher)
        self.assertIn("legacy PowerShell trader is not launched", launcher)

    def test_vbs_launcher_uses_health_contract(self) -> None:
        launcher = (REPO_ROOT / "Launch Alpaca Paper Trader.vbs").read_text(encoding="utf-8")
        self.assertIn("/api/health", launcher)
        self.assertIn("IsCurrentHealth", launcher)
        self.assertNotIn("/api/state", launcher)


if __name__ == "__main__":
    unittest.main()
