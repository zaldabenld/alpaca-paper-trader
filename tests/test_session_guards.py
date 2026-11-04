from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import AppConfig, TraderEngine


def clock_at(now_utc: datetime, close_utc: datetime) -> SimpleNamespace:
    return SimpleNamespace(is_open=True, timestamp=now_utc, next_close=close_utc, next_open=None)


class SessionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = TraderEngine("guards")
        self.config = AppConfig(symbols=["SPY"], entry_open_guard_minutes=15, entry_close_guard_minutes=180)

    def test_open_guard_on_a_half_day(self) -> None:
        # Fri 2026-11-27 closes 13:00 ET (18:00 UTC); 09:40 ET is inside the 15-minute open guard.
        close = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
        self.assertIn("opened 10 min ago",
                      self.engine.entry_open_guard_message(clock_at(datetime(2026, 11, 27, 14, 40, tzinfo=timezone.utc), close), self.config))
        self.assertEqual(
            self.engine.entry_open_guard_message(clock_at(datetime(2026, 11, 27, 14, 50, tzinfo=timezone.utc), close), self.config), "")

    def test_open_guard_on_a_normal_day_is_unchanged(self) -> None:
        close = datetime(2026, 11, 4, 21, 0, tzinfo=timezone.utc)  # 16:00 ET
        self.assertIn("opened 5 min ago",
                      self.engine.entry_open_guard_message(clock_at(datetime(2026, 11, 4, 14, 35, tzinfo=timezone.utc), close), self.config))
        self.assertEqual(
            self.engine.entry_open_guard_message(clock_at(datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc), close), self.config), "")

    def test_close_guard_counts_back_from_the_half_day_close(self) -> None:
        close = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)
        # 10:01 ET is 179 minutes before a 13:00 close: inside a 180-minute guard.
        self.assertIn("closes in 179 min",
                      self.engine.entry_close_guard_message(clock_at(datetime(2026, 11, 27, 15, 1, tzinfo=timezone.utc), close), self.config))
        self.assertEqual(
            self.engine.entry_close_guard_message(clock_at(datetime(2026, 11, 27, 14, 55, tzinfo=timezone.utc), close), self.config), "")


if __name__ == "__main__":
    unittest.main()
