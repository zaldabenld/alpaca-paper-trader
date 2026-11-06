from __future__ import annotations

import unittest

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop import universe as rvol
from alpaca_desktop.engine import AppConfig, TraderEngine


NEW_PRESET_KEYS = (
    "most_active_count",
    "daily_pick_count",
    "daily_max_symbols",
    "inverse_etf_symbols",
    "extension_atr_reference_percent",
)


class ConfigSelectionSettingsTests(unittest.TestCase):
    def test_defaults(self):
        config = AppConfig()
        self.assertEqual(config.most_active_count, engine_module.MOST_ACTIVES_MAX)
        self.assertEqual(config.daily_pick_count, rvol.PICK_COUNT)
        self.assertEqual(config.daily_max_symbols, rvol.MAX_SYMBOLS)
        self.assertEqual(config.inverse_etf_symbols, list(engine_module.TOP_VOLUME_INVERSE_ETF_SYMBOLS))

    def test_counts_are_clamped(self):
        self.assertEqual(AppConfig(most_active_count=0).most_active_count, 1)
        self.assertEqual(AppConfig(most_active_count=500).most_active_count, 100)
        self.assertEqual(AppConfig(daily_pick_count=0).daily_pick_count, 1)
        self.assertEqual(AppConfig(daily_pick_count=200).daily_pick_count, engine_module.DAILY_LIST_MAX)
        self.assertEqual(AppConfig(daily_pick_count=30, daily_max_symbols=10).daily_max_symbols, 30)
        self.assertEqual(AppConfig(daily_max_symbols=300).daily_max_symbols, engine_module.DAILY_LIST_MAX)

    def test_inverse_etf_symbols_parsing(self):
        self.assertEqual(
            AppConfig(inverse_etf_symbols=" sqqq, sh ,SQQQ").inverse_etf_symbols,
            ["SQQQ", "SH"],
        )
        self.assertEqual(AppConfig(inverse_etf_symbols="sqqq sh").inverse_etf_symbols, ["SQQQ", "SH"])
        with self.assertRaises(ValueError):
            AppConfig(inverse_etf_symbols="AAPL")
        with self.assertRaises(ValueError):
            AppConfig(inverse_etf_symbols=[])

    def test_presets_cover_every_strategy_key_with_defaults(self):
        defaults = AppConfig().model_dump(mode="json")
        for name, preset in engine_module.PROFILE_PRESETS.items():
            for key in engine_module.PROFILE_STRATEGY_KEYS:
                self.assertIn(key, preset, f"preset {name!r} is missing strategy key {key!r}")
        for key in NEW_PRESET_KEYS:
            for name, preset in engine_module.PROFILE_PRESETS.items():
                self.assertEqual(preset[key], defaults[key], f"preset {name!r} tunes {key!r} away from the default")

    def test_trading_symbols_honors_most_active_count(self):
        engine = TraderEngine("sel")
        engine.top_volume_symbols = [f"S{i:03d}" for i in range(100)]
        engine.config = AppConfig(most_active_count=10, inverse_etf_mode="allow", use_top_volume_symbols=True)
        expected = (
            engine.top_volume_symbols[:10]
            + list(engine_module.TOP_VOLUME_INVERSE_ETF_SYMBOLS)
        )
        self.assertEqual(engine.trading_symbols(), expected)

    def test_active_inverse_symbols_uses_configured_set(self):
        engine = TraderEngine("sel")
        engine.config = AppConfig(
            inverse_etf_symbols=["SH"], inverse_etf_mode="allow", use_top_volume_symbols=True
        )
        self.assertEqual(engine.active_inverse_symbols(), ["SH"])
        engine.config = AppConfig(
            inverse_etf_symbols=["SH"], inverse_etf_mode="exclude", use_top_volume_symbols=True
        )
        self.assertEqual(engine.active_inverse_symbols(), [])



class StreamSymbolLimitErrorTests(unittest.TestCase):
    def test_symbol_limit_error_says_which_setting_to_lower(self) -> None:
        status, detail = engine_module.market_stream_error_status("405", "symbol limit exceeded", 60)
        self.assertEqual(status, "Symbol limit")
        self.assertIn("60 streamed symbols", detail)
        self.assertIn("Settings > App-wide", detail)
        self.assertEqual(engine_module.market_stream_error_status("", "Symbol limit exceeded", 30)[0], "Symbol limit")

    def test_other_errors_keep_the_plain_detail(self) -> None:
        self.assertEqual(
            engine_module.market_stream_error_status("409", "insufficient subscription", 30),
            ("Stream error", "insufficient subscription (409)"),
        )


if __name__ == "__main__":
    unittest.main()
