from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_APP = REPO_ROOT / "python_app"
TEST_APPDATA = REPO_ROOT / ".runtime" / "localappdata"


def configure_environment() -> None:
    os.environ["LOCALAPPDATA"] = str(TEST_APPDATA)
    os.environ["ALPACA_TRADER_DISABLE_AUTO_CONNECT"] = "1"
    os.environ["ALPACA_TRADER_DISABLE_AUTO_START"] = "1"
    os.environ.setdefault("ALPACA_TRADER_DISABLE_DAY_TAPE", "1")
    TEST_APPDATA.mkdir(parents=True, exist_ok=True)
    for path in (REPO_ROOT, PYTHON_APP):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_failure_reason(test: unittest.TestCase) -> str:
    method = getattr(test, getattr(test, "_testMethodName", ""), None)
    return str(getattr(method, "_expected_failure_reason", "") or "")


def build_suite() -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    suite.addTests(loader.discover(str(REPO_ROOT / "tests"), pattern="test_*.py", top_level_dir=str(REPO_ROOT)))
    runtime_module = load_module_from_path(
        "test_runtime_currentness",
        REPO_ROOT / "scripts" / "test_runtime_currentness.py",
    )
    suite.addTests(loader.loadTestsFromModule(runtime_module))
    return suite


def main() -> int:
    configure_environment()
    suite = build_suite()
    runner = unittest.TextTestRunner(stream=sys.stdout, verbosity=2)
    result = runner.run(suite)
    if result.expectedFailures:
        print("\nExpected-failing future contracts:")
        for test, _traceback in result.expectedFailures:
            reason = expected_failure_reason(test)
            suffix = f" - {reason}" if reason else ""
            print(f"- {test.id()}{suffix}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
