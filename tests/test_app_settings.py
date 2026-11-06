from __future__ import annotations

import unittest

from .helpers import configure_test_environment

configure_test_environment()

from alpaca_desktop import universe as rvol
from alpaca_desktop.app_settings import AppWideSettings, DEFAULT_MARKET_STREAM_SYMBOL_LIMIT


class AppWideSettingsTests(unittest.TestCase):
    def test_defaults_match_universe_constants(self):
        settings = AppWideSettings()
        self.assertEqual(settings.daily_pick_minutes_after_open, rvol.PICK_AFTER_OPEN_MINUTES)
        self.assertEqual(settings.daily_recheck_minutes, rvol.RECHECK_SECONDS // 60)
        self.assertEqual(settings.rvol_lookback_sessions, rvol.LOOKBACK_SESSIONS)
        self.assertEqual(settings.rvol_min_sessions, rvol.MIN_SESSIONS)
        self.assertEqual(settings.market_stream_symbol_limit, 30)
        self.assertEqual(DEFAULT_MARKET_STREAM_SYMBOL_LIMIT, 30)

    def test_daily_pick_minutes_clamped(self):
        self.assertEqual(AppWideSettings(daily_pick_minutes_after_open=0).daily_pick_minutes_after_open, 1)
        self.assertEqual(AppWideSettings(daily_pick_minutes_after_open=500).daily_pick_minutes_after_open, 120)

    def test_daily_recheck_minutes_clamped(self):
        self.assertEqual(AppWideSettings(daily_recheck_minutes=1).daily_recheck_minutes, 5)
        self.assertEqual(AppWideSettings(daily_recheck_minutes=999).daily_recheck_minutes, 240)

    def test_rvol_lookback_sessions_clamped(self):
        self.assertEqual(AppWideSettings(rvol_lookback_sessions=1).rvol_lookback_sessions, 5)
        self.assertEqual(AppWideSettings(rvol_lookback_sessions=99).rvol_lookback_sessions, 60)

    def test_rvol_min_sessions_clamped_to_at_least_one(self):
        self.assertEqual(AppWideSettings(rvol_min_sessions=0).rvol_min_sessions, 1)

    def test_rvol_min_sessions_clamped_to_lookback(self):
        settings = AppWideSettings(rvol_min_sessions=30, rvol_lookback_sessions=10)
        self.assertEqual(settings.rvol_lookback_sessions, 10)
        self.assertEqual(settings.rvol_min_sessions, 10)

    def test_market_stream_symbol_limit_clamped(self):
        self.assertEqual(AppWideSettings(market_stream_symbol_limit=0).market_stream_symbol_limit, 1)
        self.assertEqual(AppWideSettings(market_stream_symbol_limit=9999).market_stream_symbol_limit, 500)

    def test_list_params_defaults(self):
        self.assertEqual(
            AppWideSettings().list_params(),
            {"pick_minutes_after_open": 15, "recheck_seconds": 1800, "lookback_sessions": 20, "min_sessions": 5},
        )


if __name__ == "__main__":
    unittest.main()
