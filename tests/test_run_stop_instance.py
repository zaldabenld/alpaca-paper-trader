from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .helpers import configure_test_environment, REPO_ROOT

configure_test_environment()

_spec = importlib.util.spec_from_file_location("apt_run", REPO_ROOT / "python_app" / "run.py")
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

FAKE_PID = 4242
FAKE_URL = "http://127.0.0.1:1"


def make_fake_proc(tmp: str, cmdline_args: list[str], cwd_target: Path) -> Path:
    proc_root = Path(tmp)
    pid_dir = proc_root / str(FAKE_PID)
    pid_dir.mkdir()
    payload = b"\0".join(arg.encode("utf-8") for arg in cmdline_args) + b"\0"
    (pid_dir / "cmdline").write_bytes(payload)
    os.symlink(str(cwd_target), str(pid_dir / "cwd"))
    return proc_root


class PidIsThisBackendTests(unittest.TestCase):
    def test_absolute_run_py_arg_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = make_fake_proc(
                tmp, [str(REPO_ROOT / "python_app" / "run.py")], Path(tmp)
            )
            with patch.object(module, "fetch_health", return_value={"pid": FAKE_PID}):
                self.assertTrue(
                    module.pid_is_this_backend(FAKE_PID, FAKE_URL, proc_root=proc_root)
                )

    def test_relative_run_py_arg_resolved_via_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = make_fake_proc(tmp, ["python_app/run.py"], REPO_ROOT)
            with patch.object(module, "fetch_health", return_value={"pid": FAKE_PID}):
                self.assertTrue(
                    module.pid_is_this_backend(FAKE_PID, FAKE_URL, proc_root=proc_root)
                )

    def test_unrelated_process_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = make_fake_proc(tmp, ["/usr/bin/sleep", "100"], Path(tmp))
            with patch.object(module, "fetch_health", return_value={"pid": FAKE_PID}):
                self.assertFalse(
                    module.pid_is_this_backend(FAKE_PID, FAKE_URL, proc_root=proc_root)
                )

    def test_health_pid_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc_root = make_fake_proc(
                tmp, [str(REPO_ROOT / "python_app" / "run.py")], Path(tmp)
            )
            with patch.object(module, "fetch_health", return_value={"pid": 9999}):
                self.assertFalse(
                    module.pid_is_this_backend(FAKE_PID, FAKE_URL, proc_root=proc_root)
                )


class StopInstanceTests(unittest.TestCase):
    def test_stop_instance_refuses_when_pid_is_not_this_backend(self) -> None:
        with patch.object(module, "pid_is_this_backend", return_value=False), \
                patch.object(module.os, "kill") as kill_mock, \
                patch.object(module, "safe_print"):
            result = module.stop_instance({"pid": FAKE_PID, "url": FAKE_URL}, FAKE_URL)
        self.assertFalse(result)
        kill_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
