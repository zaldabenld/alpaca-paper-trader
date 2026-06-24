from __future__ import annotations

import os
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar


F = TypeVar("F", bound=Callable[..., object])
REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_APP = REPO_ROOT / "python_app"
TEST_APPDATA = REPO_ROOT / ".runtime" / "localappdata"


def configure_test_environment() -> None:
    os.environ["LOCALAPPDATA"] = str(TEST_APPDATA)
    os.environ["ALPACA_TRADER_DISABLE_AUTO_CONNECT"] = "1"
    os.environ["ALPACA_TRADER_DISABLE_AUTO_START"] = "1"
    os.environ.setdefault("ALPACA_TRADER_DISABLE_DAY_TAPE", "1")
    TEST_APPDATA.mkdir(parents=True, exist_ok=True)
    for path in (REPO_ROOT, PYTHON_APP):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def expected_failure(reason: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        marked = unittest.expectedFailure(func)
        setattr(marked, "_expected_failure_reason", reason)
        return marked  # type: ignore[return-value]

    return decorator
