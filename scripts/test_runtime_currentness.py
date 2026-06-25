from __future__ import annotations

import importlib.util
import os
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


def load_shortcut_verifier_module():
    spec = importlib.util.spec_from_file_location(
        "verify_desktop_shortcut_for_test", REPO_ROOT / "scripts" / "verify_desktop_shortcut.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/verify_desktop_shortcut.py")
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

    def test_default_launch_port_remains_fixed(self) -> None:
        run_module = load_run_module()
        original = os.environ.pop("ALPACA_TRADER_PORT", None)
        try:
            self.assertEqual(run_module.configured_port(), 8765)
        finally:
            if original is not None:
                os.environ["ALPACA_TRADER_PORT"] = original

    def test_current_backend_on_wrong_port_is_not_reused(self) -> None:
        run_module = load_run_module()
        valid_health = {
            "current": True,
            "source_stamp": currentness.source_stamp(),
            "source_path": str(currentness.ROOT),
            "status": "ok",
            "pid": 123,
        }
        stopped: list[str] = []

        run_module.load_instance = lambda: {"url": "http://127.0.0.1:50412", "pid": 123}
        run_module.url_is_alive = lambda url, timeout=1.0: True
        run_module.fetch_health = lambda url: valid_health
        run_module.safe_print = lambda message: None

        def fake_stop_instance(raw: dict[str, object], url: str) -> bool:
            stopped.append(url)
            return True

        run_module.stop_instance = fake_stop_instance

        self.assertEqual(run_module.active_instance_url("127.0.0.1", 8765), "")
        self.assertEqual(stopped, ["http://127.0.0.1:50412"])

    def test_stale_backend_stop_failure_blocks_launch(self) -> None:
        run_module = load_run_module()
        stale_health = {
            "current": False,
            "source_stamp": "old",
            "source_path": str(currentness.ROOT),
            "status": "stale",
            "pid": 123,
        }
        messages: list[str] = []

        run_module.load_instance = lambda: {"url": "http://127.0.0.1:8765", "pid": 123}
        run_module.url_is_alive = lambda url, timeout=1.0: True
        run_module.fetch_health = lambda url: stale_health
        run_module.stop_instance = lambda raw, url: False
        run_module.safe_print = lambda message: messages.append(message)

        with self.assertRaises(run_module.LaunchBlockedError):
            run_module.active_instance_url("127.0.0.1", 8765)
        self.assertTrue(any("Refusing to start another backend" in message for message in messages))

    def test_main_cmd_has_no_legacy_powershell_fallback(self) -> None:
        launcher = (REPO_ROOT / "Launch Alpaca Paper Trader.cmd").read_text(encoding="utf-8")
        self.assertNotIn("src\\App.ps1", launcher)
        self.assertIn("Python virtualenv is missing", launcher)
        self.assertIn("legacy PowerShell trader is not launched", launcher)

    def test_vbs_launcher_uses_health_contract(self) -> None:
        launcher = (REPO_ROOT / "Launch Alpaca Paper Trader.vbs").read_text(encoding="utf-8")
        self.assertIn("/api/health", launcher)
        self.assertIn("IsCurrentHealth", launcher)
        self.assertIn("DeleteInstanceIfUrl", launcher)
        self.assertNotIn("/api/state", launcher)
        self.assertIn("If Len(healthText) = 0 Then Exit Function", launcher)
        self.assertIn('If JsonValue(text, "url") = expectedUrl Then', launcher)
        self.assertIn("fso.DeleteFile instancePath, True", launcher)

    def test_desktop_shortcut_creator_points_to_vbs_through_wscript(self) -> None:
        creator = (REPO_ROOT / "Create-DesktopShortcut.ps1").read_text(encoding="utf-8")
        self.assertIn("System32\\wscript.exe", creator)
        self.assertIn("Launch Alpaca Paper Trader.vbs", creator)
        self.assertIn("Alpaca Paper Trader.lnk", creator)
        self.assertIn("$shortcut.TargetPath = $wscript", creator)
        self.assertIn('$shortcut.Arguments = "`"$launcher`""', creator)
        self.assertIn("$shortcut.WorkingDirectory = $root", creator)

    def test_vbs_launcher_starts_hidden_pythonw_and_opens_edge_app_mode(self) -> None:
        launcher = (REPO_ROOT / "Launch Alpaca Paper Trader.vbs").read_text(encoding="utf-8")
        self.assertIn('.venv\\Scripts\\pythonw.exe', launcher)
        self.assertIn('shell.Run Quote(launcherPython) & " " & Quote(pythonRun) & " --no-browser", 0, False', launcher)
        self.assertIn("--app=", launcher)
        self.assertIn("smokeExit = shell.Run", launcher)
        self.assertIn('" --smoke", 0, True)', launcher)

    def test_shortcut_verifier_accepts_expected_shortcut_metadata(self) -> None:
        verifier = load_shortcut_verifier_module()
        expected = verifier.expected_shortcut_contract(REPO_ROOT)
        metadata = {
            "exists": True,
            "target_path": expected["target_path"],
            "arguments": expected["arguments"],
            "working_directory": expected["working_directory"],
            "icon_location": expected["icon_path"] + ",0",
        }

        ok, issues, _expected = verifier.validate_shortcut_metadata(metadata, REPO_ROOT)

        self.assertTrue(ok, issues)


if __name__ == "__main__":
    unittest.main()
