from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any


def dec(value: Any) -> Decimal:
    if value in (None, "", "inf"):
        return Decimal("99") if value == "inf" else Decimal("0")
    return Decimal(str(value))


def candidate_summary(item: dict[str, Any]) -> dict[str, Any]:
    candidate = item.get("candidate") or {}
    entry = candidate.get("entry") or {}
    return {
        "name": candidate.get("name", ""),
        "entry": {
            "rsi": [entry.get("rsi_min"), entry.get("rsi_max")],
            "min_entry_score": entry.get("min_entry_score"),
            "min_momentum": entry.get("min_momentum"),
            "min_recent_momentum": entry.get("min_recent_momentum"),
            "min_long_momentum": entry.get("min_long_momentum"),
            "min_session_change": entry.get("min_session_change"),
            "vwap_distance": [entry.get("min_vwap_distance"), entry.get("max_vwap_distance")],
            "pullback_max": [entry.get("max_session_pullback"), entry.get("max_recent_pullback")],
            "min_smi": entry.get("min_smi"),
            "min_relative_volume": entry.get("min_relative_volume"),
        },
        "exit": {
            "style": candidate.get("exit_style"),
            "take_profit_percent": candidate.get("take_profit_percent"),
            "stop_loss_percent": candidate.get("stop_loss_percent"),
            "trail_activation_percent": candidate.get("trail_activation_percent"),
            "trail_distance_percent": candidate.get("trail_distance_percent"),
            "profit_lock_percent": candidate.get("profit_lock_percent"),
        },
    }


def rank_key(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item["max_stable_slippage_bps"],
        item["stable_slippage_count"],
        item["min_active_fold_count"],
        item["min_positive_fold_count"],
        item["total_pnl_at_max_slippage"],
        item["min_profit_factor_at_max_slippage"],
        -item["worst_drawdown_percent_at_max_slippage"],
        item["total_buys_at_max_slippage"],
    )


def collect_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for bucket in report.get("buckets", []):
        label = bucket.get("label", "")
        for slippage_result in bucket.get("slippage_results", []):
            slippage = dec(slippage_result.get("slippage_bps"))
            for item in slippage_result.get("top", []):
                candidate = item.get("candidate") or {}
                name = candidate.get("name", "")
                key = (label, name)
                record = grouped.setdefault(
                    key,
                    {
                        "bucket": label,
                        "candidate": candidate_summary(item),
                        "slippage_results": [],
                    },
                )
                record["slippage_results"].append(
                    {
                        "slippage_bps": slippage,
                        "stable": bool(item.get("stable")),
                        "total_pnl": dec(item.get("total_pnl")),
                        "total_buys": int(item.get("total_buys") or 0),
                        "active_fold_count": int(item.get("active_fold_count") or 0),
                        "positive_fold_count": int(item.get("positive_fold_count") or 0),
                        "fold_count": int(item.get("fold_count") or 0),
                        "min_profit_factor": dec(item.get("min_profit_factor")),
                        "worst_drawdown_percent": dec(item.get("worst_drawdown_percent")),
                    }
                )

    ranked: list[dict[str, Any]] = []
    for record in grouped.values():
        stable_results = [item for item in record["slippage_results"] if item["stable"]]
        fold_basis = stable_results or record["slippage_results"]
        if stable_results:
            max_result = max(stable_results, key=lambda item: item["slippage_bps"])
            max_slippage = max_result["slippage_bps"]
        else:
            max_result = max(record["slippage_results"], key=lambda item: (item["total_pnl"], item["active_fold_count"]))
            max_slippage = Decimal("0")
        ranked.append(
            {
                **record,
                "stable_slippage_count": len(stable_results),
                "max_stable_slippage_bps": max_slippage,
                "total_pnl_at_max_slippage": max_result["total_pnl"],
                "total_buys_at_max_slippage": max_result["total_buys"],
                "min_active_fold_count": min((item["active_fold_count"] for item in fold_basis), default=0),
                "min_positive_fold_count": min((item["positive_fold_count"] for item in fold_basis), default=0),
                "min_profit_factor_at_max_slippage": max_result["min_profit_factor"],
                "worst_drawdown_percent_at_max_slippage": max_result["worst_drawdown_percent"],
            }
        )
    ranked.sort(key=rank_key, reverse=True)
    return ranked


def app_config_patch(candidate: dict[str, Any]) -> dict[str, Any]:
    entry = candidate.get("entry") or {}
    exit_plan = candidate.get("exit") or {}
    rsi = entry.get("rsi") or [None, None]
    vwap = entry.get("vwap_distance") or [None, None]
    pullback = entry.get("pullback_max") or [None, None]
    return {
        "buy_rsi_min": rsi[0],
        "buy_rsi_max": rsi[1],
        "min_entry_score": entry.get("min_entry_score"),
        "min_momentum_percent": entry.get("min_momentum"),
        "min_recent_momentum_percent": entry.get("min_recent_momentum"),
        "min_long_momentum_percent": entry.get("min_long_momentum"),
        "min_session_change_percent": entry.get("min_session_change"),
        "min_vwap_distance_percent": vwap[0],
        "max_vwap_distance_percent": vwap[1],
        "max_session_pullback_percent": pullback[0],
        "max_recent_pullback_percent": pullback[1],
        "late_momentum_floor_percent": "0",
        "min_smi": entry.get("min_smi"),
        "volume_multiplier": entry.get("min_relative_volume"),
        "take_profit_percent": exit_plan.get("take_profit_percent") if exit_plan.get("style") == "fixed" else "0",
        "stop_loss_percent": exit_plan.get("stop_loss_percent"),
        "profit_trail_start_percent": "0" if exit_plan.get("style") == "fixed" else exit_plan.get("trail_activation_percent"),
        "profit_trail_drop_percent": "0" if exit_plan.get("style") == "fixed" else exit_plan.get("trail_distance_percent"),
        "exit_close_guard_minutes": 5,
    }


def to_plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.quantize(Decimal("0.0001")), "f")
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    return value


def markdown_report(source: Path, candidates: list[dict[str, Any]], top: int) -> str:
    lines = [
        "# Day Tape Strategy Recommendation",
        "",
        f"Source: `{source}`",
        "",
        "| Rank | Candidate | Max stable bps | P&L at max bps | Buys | Min PF | Worst DD | Notes |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for rank, item in enumerate(candidates[:top], start=1):
        candidate = item["candidate"]
        notes = []
        if item["max_stable_slippage_bps"] < Decimal("10"):
            notes.append("cost fragile")
        if item["min_active_fold_count"] < 3:
            notes.append("inactive fold")
        if item["total_buys_at_max_slippage"] < 10:
            notes.append("thin sample")
        note_text = ", ".join(notes) or "passes fold gates"
        lines.append(
            "| "
            f"{rank} | {candidate['name']} | {item['max_stable_slippage_bps']} | "
            f"{item['total_pnl_at_max_slippage']} | {item['total_buys_at_max_slippage']} | "
            f"{item['min_profit_factor_at_max_slippage']} | {item['worst_drawdown_percent_at_max_slippage']}% | "
            f"{note_text} |"
        )
    if candidates:
        best = candidates[0]["candidate"]
        patch = app_config_patch(best)
        lines.extend(
            [
                "",
                "## Best Candidate",
                "",
                f"`{best['name']}`",
                "",
                "Entry:",
                f"- RSI: `{best['entry']['rsi'][0]}` to `{best['entry']['rsi'][1]}`",
                f"- Score: `>= {best['entry']['min_entry_score']}`",
                f"- Momentum/recent/long/session: `>= {best['entry']['min_momentum']}`, `>= {best['entry']['min_recent_momentum']}`, `>= {best['entry']['min_long_momentum']}`, `>= {best['entry']['min_session_change']}`",
                f"- VWAP distance: `{best['entry']['vwap_distance'][0]}` to `{best['entry']['vwap_distance'][1]}`",
                f"- Pullback max: `{best['entry']['pullback_max'][0]}` / `{best['entry']['pullback_max'][1]}`",
                f"- SMI: `>= {best['entry']['min_smi']}`",
                f"- Relative volume: `>= {best['entry']['min_relative_volume']}`",
                "",
                "Exit:",
                f"- Style: `{best['exit']['style']}`",
                f"- Take profit: `{best['exit']['take_profit_percent']}%`",
                f"- Stop loss: `{best['exit']['stop_loss_percent']}%`",
                f"- Trail activation/drop: `{best['exit']['trail_activation_percent']}%` / `{best['exit']['trail_distance_percent']}%`",
                "",
                "App config patch:",
                "",
                "```json",
                json.dumps(to_plain(patch), indent=2),
                "```",
                "",
                "Caveat: this is an offline replay recommendation. It should remain in paper/dry-run validation until more completed tape days confirm it.",
            ]
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a ranked recommendation from a cross-validation JSON report.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    candidates = collect_candidates(report)
    output = {
        "source": str(args.report),
        "top": [
            to_plain(item | {"app_config_patch": app_config_patch(item["candidate"])})
            for item in candidates[: max(1, args.top)]
        ],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"JSON recommendation: {args.json_output}")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown_report(args.report, candidates, max(1, args.top)), encoding="utf-8")
        print(f"Markdown recommendation: {args.markdown_output}")
    for rank, item in enumerate(candidates[: max(1, args.top)], start=1):
        print(
            f"#{rank} {item['candidate']['name']} max_bps={item['max_stable_slippage_bps']} "
            f"pnl={item['total_pnl_at_max_slippage']} buys={item['total_buys_at_max_slippage']} "
            f"min_pf={item['min_profit_factor_at_max_slippage']} "
            f"worst_dd={item['worst_drawdown_percent_at_max_slippage']}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
