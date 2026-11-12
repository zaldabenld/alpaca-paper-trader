from __future__ import annotations

import re
import unittest

from .helpers import REPO_ROOT, configure_test_environment

configure_test_environment()

from alpaca_desktop import engine as engine_module

APP_JS = REPO_ROOT / "python_app" / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "python_app" / "static" / "index.html"


class FrontendDomContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app_js = APP_JS.read_text(encoding="utf-8")
        self.index_html = INDEX_HTML.read_text(encoding="utf-8")

    def test_every_js_id_exists_exactly_once_in_html(self) -> None:
        ids_from_js = set()
        for match in re.finditer(r'querySelector\("#([A-Za-z0-9_-]+)"\)', self.app_js):
            ids_from_js.add(match.group(1))
        for match in re.finditer(
            r'\b(readNumber|readInt|backtestNumber|backtestString|readAppInt)\("([A-Za-z0-9_-]+)"',
            self.app_js,
        ):
            ids_from_js.add(match.group(2))

        problems = {}
        for element_id in sorted(ids_from_js):
            count = len(re.findall(rf'(?<![\w-])id="{re.escape(element_id)}"', self.index_html))
            if count != 1:
                problems[element_id] = count
        self.assertEqual({}, problems)

    def test_every_config_key_has_a_form_field(self) -> None:
        config_start = self.app_js.index("const configKeys = [") + len(
            "const configKeys = ["
        )
        config_text = self.app_js[config_start : self.app_js.index("];", config_start)]
        keys = re.findall(r'"([a-z0-9_]+)"', config_text)

        fields_start = self.app_js.index("const fields = {") + len("const fields = {")
        fields_text = self.app_js[
            fields_start : self.app_js.index("\n};", fields_start)
        ]
        field_names = set(re.findall(r"^\s*([A-Za-z0-9]+):", fields_text, re.MULTILINE))

        def camel(key: str) -> str:
            parts = key.split("_")
            return parts[0] + "".join(part.capitalize() for part in parts[1:])

        missing = sorted(k for k in keys if camel(k) not in field_names)
        self.assertEqual([], missing)
        self.assertGreater(len(keys), 40)

    def test_universe_mode_control_and_status_are_wired(self) -> None:
        self.assertEqual(1, len(re.findall(r'(?<![\w-])id="universeMode"', self.index_html)))
        self.assertEqual(1, len(re.findall(r'(?<![\w-])id="dailyUniverseStatus"', self.index_html)))
        for value in ("most_active", "daily_rvol"):
            self.assertIn(f'<option value="{value}"', self.index_html)

        config_start = self.app_js.index("const configKeys = [")
        config_text = self.app_js[config_start : self.app_js.index("];", config_start)]
        self.assertIn('"universe_mode"', config_text)
        profile_start = self.app_js.index("const strategyProfileKeys = new Set([")
        profile_text = self.app_js[profile_start : self.app_js.index("]);", profile_start)]
        self.assertIn('"universe_mode"', profile_text)
        self.assertIn("universe_mode: fields.universeMode.value", self.app_js)
        self.assertIn('universe_mode: "most_active"', self.app_js)

    def test_orb_entry_controls_are_wired(self) -> None:
        for element_id in ("entryMode", "orbMinutes", "orbMaxBreakoutPercent"):
            self.assertEqual(1, len(re.findall(rf'(?<![\w-])id="{element_id}"', self.index_html)))
        for value in ("momentum", "orb"):
            self.assertIn(f'<option value="{value}"', self.index_html)
        config_start = self.app_js.index("const configKeys = [")
        config_text = self.app_js[config_start : self.app_js.index("];", config_start)]
        profile_start = self.app_js.index("const strategyProfileKeys = new Set([")
        profile_text = self.app_js[profile_start : self.app_js.index("]);", profile_start)]
        for key in ("entry_mode", "orb_minutes", "orb_max_breakout_percent"):
            self.assertIn(f'"{key}"', config_text)
            self.assertIn(f'"{key}"', profile_text)
        self.assertIn("entry_mode: fields.entryMode.value", self.app_js)
        self.assertIn('entry_mode: "momentum"', self.app_js)

    def test_movers_controls_are_wired(self) -> None:
        ids = (
            "moverWeightVolume",
            "moverWeightHalfHourMove",
            "moverWeightVwap",
            "moverWeightFiveMinMove",
            "moverWeightRange",
            "moverWeightSession",
            "moverWeightRsi",
            "moverVolumeFullAt",
        )
        keys = (
            "mover_weight_volume",
            "mover_weight_half_hour_move",
            "mover_weight_vwap",
            "mover_weight_five_min_move",
            "mover_weight_range",
            "mover_weight_session",
            "mover_weight_rsi",
            "mover_volume_full_at",
        )
        for element_id in ids:
            self.assertEqual(1, len(re.findall(rf'(?<![\w-])id="{element_id}"', self.index_html)))
        self.assertIn('<option value="movers"', self.index_html)
        self.assertNotIn("moverStop", self.index_html)  # movers exits are the Basic Settings stop fields
        for key in keys:
            self.assertIn(f'"{key}"', self.app_js)

    def test_settings_form_shows_only_the_selected_modes_fields(self) -> None:
        # Buy Rules is the buy decision: the selected mode's score weights and Min Score sit in it,
        # with no separate weights section. app.js hides whatever the selected mode does not use.
        buy = re.search(r'<h3>Buy Rules</h3>(.*?)<h3>Buy Limits</h3>', self.index_html, re.S)
        self.assertIsNotNone(buy)
        rules = buy.group(1)
        for element_id in ("entryMode", "minEntryScore", "moverWeightVolume", "moverWeightRsi", "moverVolumeFullAt",
                           "scoreWeightRsi", "scoreWeightVwap"):
            self.assertIn(f'id="{element_id}"', rules)
        self.assertNotIn("Movers Score Weights", self.index_html)
        self.assertNotIn("Score Weights (momentum)", self.index_html)
        self.assertEqual(self.index_html.count("<h3>Score Weights</h3>"), 1)  # the backtest panel's own
        for element_id in ("moverWeightVolume", "moverVolumeFullAt"):
            self.assertRegex(rules, rf'(?s)<label data-modes="movers"[^>]*>(?:(?!</label>).)*id="{element_id}"')
        for element_id in ("scoreWeightRsi", "buyRsiMax", "maxEntryRsi", "maxVwapDistancePercent", "requireRisingPrice",
                           "momentumPeriod", "smiPeriod", "atrPeriod", "volumePeriod"):
            self.assertRegex(rules, rf'(?s)<label data-modes="momentum"[^>]*>(?:(?!</label>).)*id="{element_id}"')
        self.assertRegex(rules, r'(?s)<label data-modes="momentum orb"[^>]*>(?:(?!</label>).)*id="minBuyVolumeRatio"')  # ORB's order-flow check
        self.assertRegex(rules, r'(?s)<label data-modes="momentum orb movers"[^>]*>(?:(?!</label>).)*id="minEntryScore"')
        # Limits and inverse funds are their own sections, out of the buy decision.
        for heading, ids in (("Buy Limits", ("maxEntriesPerSymbolPerDay", "maxEntriesPerScan", "entrySpacingSeconds")),
                             ("Inverse ETFs", ("inverseEtfMode", "inverseTrendHold", "inverseTrendMaxEntries"))):
            section = re.search(rf'<h3>{heading}</h3>(.*?)</div>\s*</div>', self.index_html, re.S)
            self.assertIsNotNone(section)
            for element_id in ids:
                self.assertIn(f'id="{element_id}"', section.group(1))
        self.assertIn("function syncEntryModeFields()", self.app_js)
        self.assertIn('fields.entryMode.addEventListener("change", syncEntryModeFields)', self.app_js)

    def test_hold_and_day_trade_controls_are_wired(self) -> None:
        hold_ids = (
            "allocationRiskOnSymbols",
            "allocationRiskOffSymbols",
            "allocationSignalSymbol",
            "allocationSmaDays",
            "allocationCheck",
            "allocationTradeMinutesBeforeClose",
            "allocationInvestPercent",
            "allocationRebalanceDriftPercent",
        )
        day_trade_ids = (
            "inplayRangeMinutes",
            "inplayMinRelativeVolume",
            "inplayMinAtrPercent",
            "inplayMinDollarVolumeMillions",
            "inplayMaxPicks",
            "inplayMaxChasePercent",
            "inplayStop",
        )
        for element_id in hold_ids + day_trade_ids:
            self.assertEqual(1, len(re.findall(rf'(?<![\w-])id="{element_id}"', self.index_html)))
        for value in ("allocation", "inplay"):
            self.assertIn(f'<option value="{value}"', self.index_html)
        config_start = self.app_js.index("const configKeys = [")
        config_text = self.app_js[config_start : self.app_js.index("];", config_start)]
        profile_start = self.app_js.index("const strategyProfileKeys = new Set([")
        profile_text = self.app_js[profile_start : self.app_js.index("]);", profile_start)]
        scalar_keys = (
            "allocation_signal_symbol",
            "allocation_sma_days",
            "allocation_check",
            "allocation_trade_minutes_before_close",
            "allocation_invest_percent",
            "allocation_rebalance_drift_percent",
            "inplay_range_minutes",
            "inplay_min_relative_volume",
            "inplay_min_atr_percent",
            "inplay_min_dollar_volume_millions",
            "inplay_max_picks",
            "inplay_max_chase_percent",
            "inplay_stop",
        )
        list_keys = ("allocation_risk_on_symbols", "allocation_risk_off_symbols")
        for key in scalar_keys:
            self.assertIn(f'"{key}"', config_text)
            self.assertIn(f'"{key}"', profile_text)
            self.assertIn(f'"{key}"', self.app_js)
        for key in list_keys:
            self.assertIn(f'"{key}"', profile_text)
            self.assertIn(f'"{key}"', self.app_js)

    def test_market_overview_is_wired(self) -> None:
        for element_id in ("tickerTape", "tickerTrack", "marketOverview", "indexCharts", "newsList", "newsFlash"):
            self.assertEqual(1, len(re.findall(rf'(?<![\w-])id="{element_id}"', self.index_html)))
        # The tape sits outside the views so it shows on every page; the index box is on the dashboard.
        self.assertLess(self.index_html.index('id="tickerTape"'), self.index_html.index('id="dashboardView"'))
        self.assertLess(self.index_html.index('id="dashboardView"'), self.index_html.index('id="marketOverview"'))
        self.assertIn('fetchWithRecovery("/api/market-overview"', self.app_js)
        self.assertIn("setInterval(loadMarketOverview, MARKET_OVERVIEW_POLL_MS)", self.app_js)

    def test_tab_buttons_match_tab_panels(self) -> None:
        buttons = len(
            re.findall(r'<button[^>]*class="tab(?: active)?"', self.index_html)
        )
        panels = len(
            re.findall(r'<section[^>]*class="tab-panel(?: active)?"', self.index_html)
        )
        self.assertEqual(buttons, panels)
        self.assertGreaterEqual(buttons, 3)

    def test_every_positions_header_is_sortable(self) -> None:
        panel_start = self.index_html.index('<section id="positionsPanel"')
        panel = self.index_html[panel_start:self.index_html.index("</thead>", panel_start)]
        headers = re.findall(r'data-sort="([a-z_]+)"', panel)
        block_start = self.app_js.index("  positionRows: {")
        columns_start = self.app_js.index("columns: [", block_start)
        columns = re.findall(r'"([a-z_]+)"', self.app_js[columns_start:self.app_js.index("],", columns_start)])
        self.assertEqual(len(headers), len(columns))
        self.assertIn("protection", columns)

    def test_js_strategy_profile_keys_match_python(self) -> None:
        profile_start = self.app_js.index("const strategyProfileKeys = new Set([")
        profile_text = self.app_js[profile_start : self.app_js.index("]);", profile_start)]
        js_keys = set(re.findall(r'"([a-z0-9_]+)"', profile_text))
        python_keys = set(engine_module.PROFILE_STRATEGY_KEYS)
        only_js = sorted(js_keys - python_keys)
        only_python = sorted(python_keys - js_keys)
        self.assertEqual(
            python_keys,
            js_keys,
            f"only in js strategyProfileKeys: {only_js}; only in python PROFILE_STRATEGY_KEYS: {only_python}",
        )

    def test_read_config_covers_every_appconfig_field(self) -> None:
        start = self.app_js.index("function readConfig() {")
        body = self.app_js[start : self.app_js.index("\n  };", start)]
        js_keys = set(re.findall(r"^\s{4}([a-z_0-9]+):", body, re.MULTILINE))
        required = set(engine_module.AppConfig.model_fields) - {"trade_size_migration", "config_version"}
        missing = sorted(required - js_keys)
        self.assertEqual([], missing, f"readConfig() is missing AppConfig fields: {missing}")

    def test_app_settings_are_wired(self) -> None:
        self.assertIn('postJson("/api/app-settings", readAppSettings())', self.app_js)
        self.assertIn('els.saveAppSettingsButton.addEventListener("click", saveAppSettings);', self.app_js)
        for element_id in ("saveAppSettingsButton", "appSettingsStatus"):
            self.assertEqual(1, len(re.findall(rf'(?<![\w-])id="{element_id}"', self.index_html)))


if __name__ == "__main__":
    unittest.main()
