from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop.strategy import StrategyState, _latest_session_points


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def build(points: list[tuple[datetime, str, str]]) -> StrategyState:
    state = StrategyState()
    for moment, close, volume in points:
        state.add_bar("AAA", close, moment, volume)
    return state


class SessionWindowTests(unittest.TestCase):
    def test_winter_day_ignores_prior_after_hours_and_premarket(self) -> None:
        # Nov 4 2026 is EST (UTC-5). 19:30 ET Nov 3 = 00:30 UTC Nov 4 (same UTC date as the session).
        state = build([
            (utc(2026, 11, 4, 0, 30), "50", "1000"),   # prior evening after-hours
            (utc(2026, 11, 4, 13, 0), "90", "1000"),   # 08:00 ET pre-market
            (utc(2026, 11, 4, 14, 30), "100", "10"),   # 09:30 ET open
            (utc(2026, 11, 4, 14, 31), "102", "10"),
        ])
        session = _latest_session_points(state.histories["AAA"])
        self.assertEqual([point.close for point in session], [Decimal("100"), Decimal("102")])
        snapshot = state.snapshot("AAA", 9, 21)
        self.assertEqual(snapshot.session_change_percent, Decimal("2"))
        self.assertEqual(snapshot.vwap, Decimal("101"))

    def test_summer_day_uses_daylight_time(self) -> None:
        # Jul 15 2026 is EDT (UTC-4): 09:30 ET = 13:30 UTC; 13:29 UTC is still pre-market.
        state = build([
            (utc(2026, 7, 15, 13, 29), "90", "1000"),
            (utc(2026, 7, 15, 13, 30), "100", "10"),
            (utc(2026, 7, 15, 13, 31), "101", "10"),
        ])
        self.assertEqual([p.close for p in _latest_session_points(state.histories["AAA"])], [Decimal("100"), Decimal("101")])

    def test_premarket_only_falls_back_to_that_days_extended_bars(self) -> None:
        state = build([
            (utc(2026, 11, 3, 20, 59), "80", "10"),    # yesterday 15:59 ET
            (utc(2026, 11, 4, 12, 0), "90", "10"),     # 07:00 ET today
            (utc(2026, 11, 4, 12, 1), "91", "10"),
        ])
        self.assertEqual([p.close for p in _latest_session_points(state.histories["AAA"])], [Decimal("90"), Decimal("91")])

    def test_after_hours_last_bar_keeps_the_regular_session(self) -> None:
        state = build([
            (utc(2026, 11, 4, 14, 30), "100", "10"),
            (utc(2026, 11, 4, 20, 59), "105", "10"),   # 15:59 ET
            (utc(2026, 11, 4, 22, 0), "110", "10"),    # 17:00 ET after-hours
        ])
        self.assertEqual([p.close for p in _latest_session_points(state.histories["AAA"])], [Decimal("100"), Decimal("105")])


if __name__ == "__main__":
    unittest.main()
