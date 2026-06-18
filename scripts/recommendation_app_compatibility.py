from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any


def load_patch(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    top = report.get("top") or []
    if not top:
        raise SystemExit(f"No top recommendation found in {path}")
    patch = top[0].get("app_config_patch")
    if not isinstance(patch, dict):
        raise SystemExit(f"No app_config_patch found in {path}")
    return patch


def app_config_fields(engine_path: Path) -> set[str]:
    tree = ast.parse(engine_path.read_text(encoding="utf-8"))
    fields: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "AppConfig":
            continue
        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                fields.add(child.target.id)
        break
    return fields


def js_array_values(text: str, name: str) -> set[str]:
    pattern = re.compile(rf"const\s+{re.escape(name)}\s*=\s*(?:new\s+Set\()?\[(.*?)\]\)?;", re.S)
    match = pattern.search(text)
    if not match:
        return set()
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def snake_to_field_id(key: str) -> str:
    parts = key.split("_")
    if not parts:
        return key
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def html_ids(text: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', text))


def compatibility_for(path: Path, patch: dict[str, Any], engine_fields: set[str], config_keys: set[str], profile_keys: set[str], ids: set[str]) -> dict[str, Any]:
    rows = []
    for key in patch:
        field_id = snake_to_field_id(key)
        row = {
            "key": key,
            "app_config": key in engine_fields,
            "js_config_key": key in config_keys,
            "js_profile_key": key in profile_keys,
            "html_input_id": field_id in ids,
            "html_id": field_id,
        }
        row["compatible"] = all(row[item] for item in ("app_config", "js_config_key", "js_profile_key", "html_input_id"))
        rows.append(row)
    return {
        "recommendation": str(path),
        "compatible": all(row["compatible"] for row in rows),
        "field_count": len(rows),
        "missing_count": sum(1 for row in rows if not row["compatible"]),
        "fields": rows,
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Recommendation App Compatibility",
        "",
        "Static check that recommendation patches target fields accepted by the supplied AppConfig and browser config form.",
        "",
        f"- Engine: `{report['engine']}`",
        f"- App JS: `{report['app_js']}`",
        f"- HTML: `{report['index_html']}`",
        "",
        "| Recommendation | Compatible | Fields | Missing |",
        "| --- | ---: | ---: | ---: |",
    ]
    for result in report["results"]:
        lines.append(
            f"| `{result['recommendation']}` | {result['compatible']} | {result['field_count']} | {result['missing_count']} |"
        )
    lines.extend(["", "## Field Detail", ""])
    for result in report["results"]:
        lines.extend(
            [
                f"### `{result['recommendation']}`",
                "",
                "| Field | AppConfig | JS config key | Profile key | HTML id |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in result["fields"]:
            lines.append(
                f"| `{row['key']}` | {row['app_config']} | {row['js_config_key']} | "
                f"{row['js_profile_key']} | `{row['html_id']}`={row['html_input_id']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check recommendation patch fields against app config/UI support.")
    parser.add_argument("--recommendation", action="append", type=Path, required=True)
    parser.add_argument("--engine", type=Path, default=Path("python_app/alpaca_desktop/engine.py"))
    parser.add_argument("--app-js", type=Path, default=Path("python_app/static/app.js"))
    parser.add_argument("--index-html", type=Path, default=Path("python_app/static/index.html"))
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    engine_fields = app_config_fields(args.engine)
    app_js_text = args.app_js.read_text(encoding="utf-8")
    config_keys = js_array_values(app_js_text, "configKeys")
    profile_keys = js_array_values(app_js_text, "strategyProfileKeys")
    ids = html_ids(args.index_html.read_text(encoding="utf-8"))
    report = {
        "engine": str(args.engine),
        "app_js": str(args.app_js),
        "index_html": str(args.index_html),
        "results": [
            compatibility_for(path, load_patch(path), engine_fields, config_keys, profile_keys, ids)
            for path in args.recommendation
        ],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
        print(f"Markdown report: {args.markdown_output}")
    for result in report["results"]:
        print(f"{result['recommendation']}: compatible={result['compatible']} missing={result['missing_count']}")
    return 0 if all(result["compatible"] for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
