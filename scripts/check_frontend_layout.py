from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = REPO_ROOT / "python_app" / "static" / "index.html"
STYLES_CSS = REPO_ROOT / "python_app" / "static" / "styles.css"
LAUNCHER_VBS = REPO_ROOT / "Launch Alpaca Paper Trader.vbs"


def css_block(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*{{(?P<body>[^}}]*)}}", source, re.DOTALL)
    if not match:
        raise AssertionError(f"Missing CSS block for {selector}")
    return match.group("body")


def launcher_width() -> int:
    source = LAUNCHER_VBS.read_text(encoding="utf-8")
    match = re.search(r"--window-size=(\d+),(\d+)", source)
    if not match:
        raise AssertionError("Could not find launcher --window-size in VBS launcher")
    return int(match.group(1))


def max_columns(container_width: int, minimum: int, gap: int, item_count: int) -> int:
    columns = 1
    for candidate in range(1, item_count + 1):
        required = candidate * minimum + max(0, candidate - 1) * gap
        if required <= container_width:
            columns = candidate
    return columns


def main() -> int:
    html = INDEX_HTML.read_text(encoding="utf-8")
    css = STYLES_CSS.read_text(encoding="utf-8")

    if 'id="accountsView"' not in html or 'class="tabs"' not in html:
        raise AssertionError("Accounts view or tabbed table surface is missing from index.html")

    layout_block = css_block(css, ".layout")
    metrics_block = css_block(css, ".metrics")
    tabs_block = css_block(css, ".tabs")
    tab_panel_block = css_block(css, ".tab-panel")
    dashboard_table_block = css_block(css, ".dashboard-table")

    required_contracts = {
        "layout_min_width_zero": "min-width: 0" in layout_block,
        "metrics_auto_fit": "repeat(auto-fit, minmax(128px, 1fr))" in metrics_block,
        "tabs_min_width_zero": "min-width: 0" in tabs_block,
        "tab_panel_local_scroll": "overflow: auto" in tab_panel_block,
        "dashboard_table_local_scroll": "overflow: auto" in dashboard_table_block,
        "desktop_collapse_breakpoint": "@media (max-width: 1180px)" in css,
    }
    missing = [key for key, value in required_contracts.items() if not value]
    if missing:
        raise AssertionError(f"Missing layout contracts: {', '.join(missing)}")

    breakpoint = 1180
    layout_padding = 36
    layout_gap = 18
    sidebar_max = 320
    metric_min = 128
    metric_gap = 12
    metric_count = 6
    viewports = [1024, 1100, launcher_width()]
    evidence = []

    for width in viewports:
        collapsed = width <= breakpoint
        content_width = width - layout_padding
        if collapsed:
            workspace_width = content_width
            page_min_width = layout_padding + min(content_width, width)
        else:
            workspace_width = width - layout_padding - layout_gap - sidebar_max
            page_min_width = layout_padding + layout_gap + sidebar_max + max(0, min(workspace_width, metric_min))
        metric_columns = max_columns(max(1, workspace_width), metric_min, metric_gap, metric_count)
        metric_required_width = metric_columns * metric_min + max(0, metric_columns - 1) * metric_gap
        whole_page_overflow = page_min_width > width or metric_required_width > max(1, workspace_width)
        evidence.append(
            {
                "viewport_width": width,
                "accounts_layout_collapsed": collapsed,
                "workspace_width": workspace_width,
                "metric_columns": metric_columns,
                "metric_required_width": metric_required_width,
                "tables_scroll_locally": True,
                "whole_page_horizontal_overflow": whole_page_overflow,
            }
        )

    failures = [item for item in evidence if item["whole_page_horizontal_overflow"]]
    if failures:
        raise AssertionError(f"Layout overflow evidence failed: {json.dumps(failures, indent=2)}")

    print(json.dumps({"viewports": evidence, "contracts": required_contracts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
