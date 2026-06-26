from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "python_app" / "static" / "app.js"
INDEX_HTML = REPO_ROOT / "python_app" / "static" / "index.html"
STYLES_CSS = REPO_ROOT / "python_app" / "static" / "styles.css"


def read_static(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class FrontendStateCoordinationTests(unittest.TestCase):
    def test_state_loader_uses_account_scoped_request_guard(self) -> None:
        source = read_static(APP_JS)

        self.assertIn('const requestChannels = {', source)
        self.assertIn('const request = beginRequest("state"', source)
        self.assertIn('signal: request.signal', source)
        self.assertIn('if (!isCurrentAccountRequest(request)) return false;', source)
        self.assertIn('return renderState(state, request);', source)
        self.assertIn('function renderState(state, context)', source)
        self.assertIn('if (!stateMatchesRenderContext(state, context)) return false;', source)

    def test_dashboard_loader_and_recovery_use_account_scoped_request_guard(self) -> None:
        source = read_static(APP_JS)

        self.assertIn('const request = beginRequest("dashboard"', source)
        self.assertIn('if (!renderDashboard(dashboard, request)) return false;', source)
        self.assertIn('await maybeRecoverDashboardStream(dashboard, request);', source)
        self.assertIn('function renderDashboard(dashboard, context)', source)
        self.assertIn('if (!isCurrentAccountContext(context)) return false;', source)
        self.assertIn('renderDashboard(recovered, context);', source)

    def test_account_switching_invalidates_polling_and_guards_auto_save(self) -> None:
        source = read_static(APP_JS)

        self.assertIn('function invalidateAccountContext()', source)
        self.assertIn('abortRequestChannel("state");', source)
        self.assertIn('abortRequestChannel("dashboard");', source)
        self.assertIn('async function withAccountTransition(callback)', source)
        self.assertIn('await switchToAccount(fields.accountSelect.value);', source)
        self.assertIn('await switchToAccount(account.account_id);', source)
        self.assertIn('guard: () => isTransitionCurrent(transitionVersion)', source)

    def test_health_polling_only_renders_latest_response(self) -> None:
        source = read_static(APP_JS)

        self.assertIn('const request = beginRequest("health", { abortPrevious: false });', source)
        self.assertGreaterEqual(source.count('if (isLatestRequest(request))'), 2)
        self.assertIn('if (isAbortError(error)) throw error;', source)


class FrontendLayoutTests(unittest.TestCase):
    def test_accounts_layout_collapses_before_narrow_desktop_widths(self) -> None:
        source = read_static(STYLES_CSS)

        self.assertIn('@media (max-width: 1180px)', source)
        self.assertRegex(
            source,
            r"@media \(max-width: 1180px\)\s*{\s*\.layout\s*{\s*grid-template-columns: 1fr;",
        )

    def test_metrics_and_table_panels_do_not_force_page_width(self) -> None:
        source = read_static(STYLES_CSS)

        self.assertIn('grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));', source)
        self.assertRegex(source, r"\.layout\s*{[^}]*min-width: 0;", re.DOTALL)
        self.assertRegex(source, r"\.workspace\s*{[^}]*min-width: 0;", re.DOTALL)
        self.assertRegex(source, r"\.tabs\s*{[^}]*min-width: 0;", re.DOTALL)
        self.assertRegex(source, r"\.tab-panel\s*{[^}]*overflow: auto;", re.DOTALL)
        self.assertRegex(source, r"\.dashboard-table\s*{[^}]*overflow: auto;", re.DOTALL)

    def test_top_level_backtest_view_exposes_day_tape_backtest_runner(self) -> None:
        html = read_static(INDEX_HTML)
        script = read_static(APP_JS)
        styles = read_static(STYLES_CSS)

        self.assertIn('data-view="backtestView"', html)
        self.assertIn('id="backtestView"', html)
        self.assertIn('id="backtestDays"', html)
        self.assertIn('id="backtestMaxEvents"', html)
        self.assertIn('id="backtestWarmupEvents"', html)
        self.assertIn('id="backtestLatestEvents"', html)
        self.assertIn('id="runBacktestButton"', html)
        self.assertIn('id="backtestMinEntryScore"', html)
        self.assertIn('id="backtestWeightMomentum"', html)
        self.assertIn('id="backtestStartingEquity"', html)
        self.assertIn('id="backtestTradeSizeMode"', html)
        self.assertIn('id="backtestCheckRows"', html)
        self.assertIn('id="backtestAcceptedRows"', html)
        self.assertIn('id="backtestRejectedRows"', html)
        self.assertNotIn('id="realizedPercentToggle"', html)
        self.assertIn("strategy_overrides:", script)
        self.assertIn("sizing_overrides:", script)
        self.assertIn("warmup_events:", script)
        self.assertIn('backtestNumber("backtestMinEntryScore"', script)
        self.assertIn('backtestString("backtestTradeSizeMode"', script)
        self.assertIn('postJson("/api/backtest/day-tape"', script)
        self.assertIn("function renderBacktestReport", script)
        self.assertIn("backtestCheckRows:", script)
        self.assertIn(".backtest-controls", styles)
        self.assertIn(".backtest-parameter-grid", styles)
        self.assertIn(".backtest-detail", styles)


if __name__ == "__main__":
    unittest.main()
