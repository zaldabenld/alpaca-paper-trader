from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from .helpers import configure_test_environment

configure_test_environment()

from alpaca_desktop import server


class FakeEngine:
    def __init__(self, name: str, *, fail_times: int = 0, auto_start: bool = True, keys: bool = True) -> None:
        self.name = name
        self.fail_times = fail_times
        self.auto_start_trading = auto_start
        self.keys = keys
        self.connected = False
        self.trading_enabled = False
        self.connect_calls = 0
        self.logs: list[tuple[str, str]] = []

    def settings(self, include_keys: bool = False) -> dict:
        return {
            "auto_connect": True,
            "remember": True,
            "api_key": "k" if self.keys else "",
            "secret_key": "s" if self.keys else "",
            "auto_start_trading": self.auto_start_trading,
        }

    def connect_saved(self) -> None:
        self.connect_calls += 1
        if self.connect_calls <= self.fail_times:
            raise ConnectionError("Temporary failure in name resolution")
        self.connected = True

    def start_trading(self) -> None:
        if not self.connected:
            raise RuntimeError("not connected")
        self.trading_enabled = True

    def log(self, level: str, message: str) -> None:
        self.logs.append((level, message))


class FakeManager:
    def __init__(self, engines: list[FakeEngine]) -> None:
        self.engines = engines
        self.shared_calls = 0

    def list_engines(self) -> list[FakeEngine]:
        return list(self.engines)

    def shared_market_source(self):
        return None

    def sync_top_volume_from(self, source) -> None:
        self.shared_calls += 1

    def ensure_market_data_stream(self) -> None:
        pass

    def backfill_dashboard_recent_trades(self, reason: str) -> None:
        pass

    def backfill_dashboard_latest_trades(self, reason: str) -> None:
        pass


def run(manager: FakeManager, *, clock_step: float = 0.0, auto_start_override: str = "0") -> list[float]:
    sleeps: list[float] = []
    now = [0.0]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds + clock_step

    # the shared test environment turns auto-start off; these tests set it explicitly
    with patch.object(server, "manager", manager), patch.dict(
        "os.environ", {"ALPACA_TRADER_DISABLE_AUTO_START": auto_start_override}
    ):
        asyncio.run(server.auto_connect_saved_accounts(sleep=fake_sleep, clock=lambda: now[0]))
    return sleeps


class AutoConnectRetryTests(unittest.TestCase):
    def test_network_down_at_boot_retries_then_connects_and_starts(self) -> None:
        flaky = FakeEngine("Account 1", fail_times=2)
        fine = FakeEngine("Account 2")
        manager = FakeManager([flaky, fine])
        sleeps = run(manager)
        self.assertEqual(sleeps, [5, 10])
        self.assertTrue(flaky.connected and flaky.trading_enabled)
        self.assertTrue(fine.connected and fine.trading_enabled)
        self.assertEqual(fine.connect_calls, 1)  # a connected account is not reconnected
        self.assertEqual(flaky.connect_calls, 3)
        self.assertEqual(sum(1 for level, _ in flaky.logs if level == "error"), 1)  # one error, not one per try
        self.assertIn(("success", "Auto-connect succeeded after retrying."), flaky.logs)
        self.assertEqual(manager.shared_calls, 2)  # stream/top-volume set up again when the late account joins

    def test_auto_start_off_connects_without_trading(self) -> None:
        engine = FakeEngine("Account 1", fail_times=1, auto_start=False)
        run(FakeManager([engine]))
        self.assertTrue(engine.connected)
        self.assertFalse(engine.trading_enabled)

    def test_account_connected_by_hand_during_retry_is_left_alone(self) -> None:
        engine = FakeEngine("Account 1", fail_times=99)
        manager = FakeManager([engine])
        sleeps: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            engine.connected = True  # the user pressed Connect

        with patch.object(server, "manager", manager), patch.dict(
            "os.environ", {"ALPACA_TRADER_DISABLE_AUTO_START": "0"}
        ):
            asyncio.run(server.auto_connect_saved_accounts(sleep=fake_sleep, clock=lambda: 0.0))
        self.assertEqual(sleeps, [5])
        self.assertEqual(engine.connect_calls, 1)
        self.assertFalse(engine.trading_enabled)

    def test_gives_up_after_the_limit(self) -> None:
        engine = FakeEngine("Account 1", fail_times=10_000)
        sleeps = run(FakeManager([engine]))
        self.assertGreaterEqual(sum(sleeps), server.AUTO_CONNECT_GIVE_UP_SECONDS - 30)
        self.assertEqual(sleeps[:5], [5, 10, 15, 30, 30])
        self.assertFalse(engine.connected)
        self.assertEqual(engine.logs[-1], ("error", "Auto-connect gave up; press Connect, then Start."))

    def test_accounts_without_saved_keys_are_skipped(self) -> None:
        engine = FakeEngine("Account 1", keys=False)
        self.assertEqual(run(FakeManager([engine])), [])
        self.assertEqual(engine.connect_calls, 0)

    def test_launch_override_skips_auto_start(self) -> None:
        engine = FakeEngine("Account 1")
        run(FakeManager([engine]), auto_start_override="1")
        self.assertTrue(engine.connected)
        self.assertFalse(engine.trading_enabled)


if __name__ == "__main__":
    unittest.main()
