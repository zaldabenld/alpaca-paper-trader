from __future__ import annotations

import re
import unittest

from .helpers import REPO_ROOT

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
            r'\b(readNumber|readInt|backtestNumber|backtestString)\("([A-Za-z0-9_-]+)"',
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


if __name__ == "__main__":
    unittest.main()
