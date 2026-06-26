from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_APP = REPO_ROOT / "python_app"
if str(PYTHON_APP) not in sys.path:
    sys.path.insert(0, str(PYTHON_APP))

from alpaca_desktop.backtester import StrategyEvaluationContext
from alpaca_desktop.engine import (
    AppConfig,
    DASHBOARD_TOP_LIMIT,
    PROFILE_STRATEGY_KEYS,
    TOP_VOLUME_SOURCE,
    TraderEngine,
    retune_strategy_config,
)
from alpaca_desktop.strategy import decimal_value, money, order_quantity

REPLAY_EQUITY = Decimal("1000")
REPLAY_CASH = Decimal("1000")
REPLAY_MAX_POSITIONS = 20
REPLAY_TRADE_PERCENT = Decimal("5")
REPLAY_TRADE_NOTIONAL = Decimal("0")
REPLAY_TOTAL_EXPOSURE_PERCENT = Decimal("100")
REPLAY_TRADE_SIZE_MODE = "percent"

BACKTEST_STRATEGY_KEYS = set(PROFILE_STRATEGY_KEYS) | {
    "score_weight_rsi",
    "score_weight_relative_volume",
    "score_weight_momentum",
    "score_weight_recent_momentum",
    "score_weight_long_momentum",
    "score_weight_session_change",
    "score_weight_vwap",
    "score_weight_smi",
    "score_weight_volatility",
    "score_weight_liquidity_bonus",
    "score_weight_flow",
    "score_weight_pullback_penalty",
    "score_weight_overbought_penalty",
    "score_weight_volatility_penalty",
    "score_weight_session_extension_penalty",
    "score_weight_vwap_extension_penalty",
    "score_weight_session_pullback_penalty",
    "score_weight_recent_pullback_penalty",
    "score_weight_smi_overheat_penalty",
}


@dataclass(frozen=True)
class ReplayHarness:
    starting_equity: Decimal = REPLAY_EQUITY
    starting_cash: Decimal = REPLAY_CASH
    trade_size_mode: str = REPLAY_TRADE_SIZE_MODE
    trade_percent: Decimal = REPLAY_TRADE_PERCENT
    trade_notional: Decimal = REPLAY_TRADE_NOTIONAL
    max_positions: int = REPLAY_MAX_POSITIONS
    total_exposure_percent: Decimal = REPLAY_TOTAL_EXPOSURE_PERCENT
    diagnostic: bool = False

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None = None) -> "ReplayHarness":
        raw = overrides if isinstance(overrides, dict) else {}
        mode = str(raw.get("trade_size_mode") or REPLAY_TRADE_SIZE_MODE).strip().lower()
        if mode not in {"percent", "notional"}:
            mode = REPLAY_TRADE_SIZE_MODE
        trade_percent = clamp_decimal_value(raw.get("trade_percent"), REPLAY_TRADE_PERCENT, Decimal("0"), Decimal("100"))
        trade_notional = clamp_decimal_value(raw.get("trade_notional"), REPLAY_TRADE_NOTIONAL, Decimal("0"), Decimal("1000000"))
        if mode == "percent":
            trade_notional = Decimal("0")
            if trade_percent <= 0:
                trade_percent = REPLAY_TRADE_PERCENT
        else:
            trade_percent = Decimal("0")
            if trade_notional <= 0:
                trade_notional = Decimal("10")
        return cls(
            starting_equity=clamp_decimal_value(raw.get("starting_equity"), REPLAY_EQUITY, Decimal("1"), Decimal("100000000")),
            starting_cash=clamp_decimal_value(raw.get("starting_cash"), REPLAY_CASH, Decimal("0"), Decimal("100000000")),
            trade_size_mode=mode,
            trade_percent=trade_percent,
            trade_notional=trade_notional,
            max_positions=clamp_int_value(raw.get("max_positions"), REPLAY_MAX_POSITIONS, 1, 200),
            total_exposure_percent=clamp_decimal_value(raw.get("total_exposure_percent"), REPLAY_TOTAL_EXPOSURE_PERCENT, Decimal("0"), Decimal("1000")),
            diagnostic=bool(raw),
        )

    def config_overrides(self) -> dict[str, Any]:
        return {
            "trade_size_mode": self.trade_size_mode,
            "max_trade_percent": str(self.trade_percent),
            "max_trade_notional": str(self.trade_notional),
            "max_total_exposure_percent": str(self.total_exposure_percent),
            "max_open_positions": self.max_positions,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "starting_equity": str(self.starting_equity),
            "starting_cash": str(self.starting_cash),
            "trade_size_mode": self.trade_size_mode,
            "trade_percent": str(self.trade_percent),
            "trade_notional": str(self.trade_notional),
            "max_positions": self.max_positions,
            "total_exposure_percent": str(self.total_exposure_percent),
            "diagnostic": self.diagnostic,
        }

ENTRY_INDICATOR_KEYS = (
    "entry_score_raw",
    "rsi_raw",
    "momentum_raw",
    "recent_momentum_raw",
    "long_momentum_raw",
    "session_change_raw",
    "session_pullback_raw",
    "recent_pullback_raw",
    "vwap_distance_raw",
    "smi_raw",
    "atr_raw",
    "volatility_raw",
)


@dataclass
class ReplayPosition:
    symbol: str
    qty: Decimal
    entry_price: Decimal
    entry_event: dict[str, Any]


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def selected_files(path: Path, days: int) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)[-max(1, days) :]


def clamp_decimal_value(value: Any, fallback: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return fallback
    try:
        parsed = decimal_value(value)
    except Exception:
        parsed = fallback
    if parsed.is_nan():
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def clamp_int_value(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def sanitized_strategy_overrides(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = overrides if isinstance(overrides, dict) else {}
    return {key: value for key, value in raw.items() if key in BACKTEST_STRATEGY_KEYS}


def json_object_arg(raw_value: str, flag_name: str) -> dict[str, Any]:
    raw = str(raw_value or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag_name} must be a JSON object: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{flag_name} must be a JSON object.")
    return value


def parse_tape_event(path_name: str, line_number: int, raw_line: str) -> dict[str, Any]:
    line = raw_line.strip()
    if not line:
        return {}
    try:
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "kind": "parse_error",
            "payload": {"file": path_name, "line": line_number, "error": str(exc)},
        }
    return event


def tail_file_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    block_size = 64 * 1024
    data = b""
    lines: list[bytes] = []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + data
            lines = data.splitlines()
            if len(lines) > limit:
                break
    return [line.decode("utf-8", errors="replace") for line in lines[-limit:]]


def iter_latest_tape_events(files: Iterable[Path], max_events: int, warmup_events: int = 0) -> Iterable[dict[str, Any]]:
    if max_events <= 0:
        yield from iter_tape_events(files, max_events=0)
        return
    selected: list[tuple[Path, list[str]]] = []
    warmup_events = max(0, int(warmup_events or 0))
    requested = max_events + warmup_events
    remaining = requested
    for path in reversed(list(files)):
        lines = tail_file_lines(path, remaining)
        if lines:
            selected.append((path, lines))
            remaining -= len(lines)
        if remaining <= 0:
            break
    parsed: list[dict[str, Any]] = []
    for path, lines in reversed(selected):
        for line_number, raw_line in enumerate(lines, start=1):
            event = parse_tape_event(path.name, line_number, raw_line)
            if not event:
                continue
            parsed.append(event)
    warmup_cutoff = max(0, len(parsed) - max_events)
    emitted = 0
    for index, event in enumerate(parsed):
        if index < warmup_cutoff:
            event = dict(event)
            event["_backtest_warmup"] = True
            yield event
            continue
        yield event
        emitted += 1
        if emitted >= max_events:
            return


def iter_tape_events(
    files: Iterable[Path],
    max_events: int = 0,
    *,
    latest_events: bool = False,
    warmup_events: int = 0,
) -> Iterable[dict[str, Any]]:
    if latest_events:
        yield from iter_latest_tape_events(files, max_events=max_events, warmup_events=warmup_events)
        return
    emitted = 0
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                event = parse_tape_event(path.name, line_number, raw_line)
                if not event:
                    continue
                yield event
                emitted += 1
                if max_events and emitted >= max_events:
                    return


def replay_config(
    raw_config: dict[str, Any] | None = None,
    strategy_overrides: dict[str, Any] | None = None,
    harness: ReplayHarness | None = None,
) -> AppConfig:
    payload = dict(raw_config or {})
    payload.setdefault("symbols", ["SPY", "QQQ"])
    payload.update(
        {
            "use_top_volume_symbols": True,
            "dry_run": True,
            "market_hours_only": False,
        }
    )
    active_harness = harness or ReplayHarness()
    payload.update(sanitized_strategy_overrides(strategy_overrides))
    payload.update(active_harness.config_overrides())
    payload.update(
        {
            "use_top_volume_symbols": True,
            "dry_run": True,
            "market_hours_only": False,
        }
    )
    return retune_strategy_config(AppConfig(**payload))


def event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def top_volume_symbols(payload: dict[str, Any]) -> list[str]:
    symbols = [
        str(symbol or "").strip().upper()
        for symbol in payload.get("symbols") or []
        if str(symbol or "").strip()
    ]
    if symbols:
        return symbols[:DASHBOARD_TOP_LIMIT]
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    return [
        str(row.get("symbol") or "").strip().upper()
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    ][:DASHBOARD_TOP_LIMIT]


def ingest_market_bar(engine: TraderEngine, payload: dict[str, Any]) -> None:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        return
    engine.strategy_state.add_bar(
        symbol,
        payload.get("close"),
        payload.get("timestamp"),
        payload.get("volume"),
        payload.get("high"),
        payload.get("low"),
    )


def position_dict(position: ReplayPosition) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "qty": str(position.qty),
        "avg_entry_price": str(position.entry_price),
        "market_value": str(position.qty * position.entry_price),
    }


def entry_indicators(snapshot_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot_dict.get(key)
        for key in ENTRY_INDICATOR_KEYS
        if snapshot_dict.get(key) not in (None, "")
    }


def indicator_averages(trades: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for trade in trades:
        indicators = trade.get("entry_indicators")
        if not isinstance(indicators, dict):
            continue
        for key in ENTRY_INDICATOR_KEYS:
            value = decimal_value(indicators.get(key), Decimal("NaN"))
            if value.is_nan():
                continue
            totals[key] = totals.get(key, Decimal("0")) + value
            counts[key] = counts.get(key, 0) + 1
    return {key: float((totals[key] / Decimal(counts[key])).quantize(Decimal("0.0001"))) for key in totals}


class DayTapeBacktester:
    def __init__(
        self,
        strategy_overrides: dict[str, Any] | None = None,
        sizing_overrides: dict[str, Any] | None = None,
    ) -> None:
        self.strategy_overrides = sanitized_strategy_overrides(strategy_overrides)
        self.harness = ReplayHarness.from_overrides(sizing_overrides)
        self.engine = TraderEngine("day-tape-backtest", "Day Tape Backtest")
        self.engine.config = replay_config(strategy_overrides=self.strategy_overrides, harness=self.harness)
        self.boundary = self.engine.backtester_boundary()
        self.account = {
            "equity": str(self.harness.starting_equity),
            "buying_power": str(self.harness.starting_cash),
            "cash": str(self.harness.starting_cash),
        }
        self.positions: dict[str, ReplayPosition] = {}
        self.closed_trades: list[dict[str, Any]] = []
        self.accepted_trades: list[dict[str, Any]] = []
        self.rejected_candidates: list[dict[str, Any]] = []
        self.evaluations = 0
        self.market_bars = 0
        self.top_volume_snapshots = 0
        self.top_volume_contexts = 0
        self.strategy_scan_top_volume_contexts = 0
        self.parse_errors = 0
        self.top_volume_sources: set[str] = set()
        self.current_top_volume_source = ""
        self.evaluations_by_top_volume_source: dict[str, int] = {}
        self.top_volume_snapshots_by_source: dict[str, int] = {}
        self.top_volume_contexts_by_source: dict[str, int] = {}
        self.warmup_events = 0

    def apply_top_volume(self, payload: dict[str, Any], *, snapshot_event: bool = True) -> None:
        rows = [dict(row) for row in payload.get("rows") or [] if isinstance(row, dict)]
        symbols = top_volume_symbols(payload)
        source = str(payload.get("source") or "unknown")
        if not symbols and not rows:
            return
        self.top_volume_sources.add(source)
        self.current_top_volume_source = source
        self.top_volume_contexts_by_source[source] = self.top_volume_contexts_by_source.get(source, 0) + 1
        if snapshot_event:
            self.top_volume_snapshots_by_source[source] = self.top_volume_snapshots_by_source.get(source, 0) + 1
        with self.engine.lock:
            self.engine.top_volume_rows = rows
            self.engine.top_volume_symbols = symbols
            self.engine.top_volume_updated = str(payload.get("updated_at") or "")
            self.engine.top_volume_error = ""
        self.top_volume_contexts += 1
        if snapshot_event:
            self.top_volume_snapshots += 1
        else:
            self.strategy_scan_top_volume_contexts += 1

    def apply_strategy_scan_top_volume(self, payload: dict[str, Any]) -> None:
        source = str(payload.get("top_volume_source") or "").strip()
        rows = payload.get("top_volume_rows") if isinstance(payload.get("top_volume_rows"), list) else []
        symbols = payload.get("top_volume_symbols") if isinstance(payload.get("top_volume_symbols"), list) else []
        if not source or (not rows and not symbols):
            return
        self.apply_top_volume(
            {
                "source": source,
                "symbols": symbols,
                "rows": rows,
                "updated_at": payload.get("top_volume_updated_at") or "",
            },
            snapshot_event=False,
        )

    def update_config(self, payload: dict[str, Any]) -> None:
        raw_config = payload.get("config")
        if isinstance(raw_config, dict):
            self.engine.config = replay_config(raw_config, self.strategy_overrides, self.harness)

    def ingest_bar(self, payload: dict[str, Any]) -> None:
        ingest_market_bar(self.engine, payload)
        self.market_bars += 1
        self.evaluate_exits(str(payload.get("symbol") or "").strip().upper())

    def total_exposure(self) -> Decimal:
        return sum(position.qty * position.entry_price for position in self.positions.values())

    def evaluate_exits(self, changed_symbol: str = "") -> None:
        for symbol, position in list(self.positions.items()):
            if changed_symbol and symbol != changed_symbol:
                continue
            snapshot = self.boundary.strategy.snapshot(symbol)
            if snapshot.price is None:
                continue
            reason, hold_reason = self.engine.local_protection_exit_decision(
                symbol,
                self.engine.config,
                position_dict(position),
                snapshot.price,
                False,
                False,
            )
            if hold_reason or not reason:
                continue
            exit_price = snapshot.price
            realized = (exit_price - position.entry_price) * position.qty
            closed = dict(position.entry_event)
            closed.update(
                {
                    "exit_price": str(exit_price),
                    "exit_reason": reason,
                    "realized_pl": str(realized.quantize(Decimal("0.000001"))),
                    "winner": realized > 0,
                }
            )
            self.closed_trades.append(closed)
            self.positions.pop(symbol, None)
            self.account["buying_power"] = str(decimal_value(self.account["buying_power"]) + position.qty * exit_price)

    def evaluation_universe(self) -> tuple[str, str]:
        if self.engine.config.inverse_etf_mode == "inverse_only":
            return "inverse_only", "inverse_only"
        if self.engine.config.use_top_volume_symbols:
            if self.engine.top_volume_symbols:
                return "top_volume", self.current_top_volume_source or "missing_top_volume"
            return "missing_top_volume", "missing_top_volume"
        return "manual", "manual"

    def evaluate_entries(self, event_time: str = "") -> None:
        self.evaluations += 1
        universe_source, evaluation_source = self.evaluation_universe()
        self.evaluations_by_top_volume_source[evaluation_source] = (
            self.evaluations_by_top_volume_source.get(evaluation_source, 0) + 1
        )
        candidates: list[dict[str, Any]] = []
        symbols = self.engine.trading_symbols()
        open_position_count = len(self.positions)
        for rank, symbol in enumerate(symbols):
            position = self.positions.get(symbol)
            context = StrategyEvaluationContext(
                account=self.account,
                position=position_dict(position) if position else None,
                open_position_count=open_position_count,
                open_orders=[],
                total_exposure=self.total_exposure(),
                entries_allowed=True,
            )
            candidate = self.boundary.strategy.entry_candidate(symbol, rank, context)
            snapshot = self.boundary.strategy.snapshot(symbol)
            snapshot_dict = snapshot.as_dict()
            if candidate:
                candidates.append(candidate)
                continue
            self.rejected_candidates.append(
                {
                    "time": event_time,
                    "symbol": symbol,
                    "reason": self.engine.strategy_state.last_action.get(symbol, "Hold (not selected)"),
                    "indicators": entry_indicators(snapshot_dict),
                }
            )

        candidates.sort(key=lambda item: (-float(item["score"]), item["rank"], item["symbol"]))
        for candidate in candidates:
            symbol = str(candidate.get("symbol") or "").strip().upper()
            if not symbol or symbol in self.positions:
                continue
            if len(self.positions) >= self.engine.config.max_open_positions:
                self.rejected_candidates.append(
                    {"time": event_time, "symbol": symbol, "reason": "Hold (max positions)", "indicators": {}}
                )
                continue
            snapshot = self.boundary.strategy.snapshot(symbol)
            if snapshot.price is None:
                continue
            notional = self.engine.trade_notional(
                self.engine.config,
                self.harness.starting_equity,
                decimal_value(self.account["buying_power"]),
                self.total_exposure(),
                snapshot.price,
            )
            qty = order_quantity(notional, snapshot.price)
            if notional <= 0 or qty <= 0:
                self.rejected_candidates.append(
                    {
                        "time": event_time,
                        "symbol": symbol,
                        "reason": "Hold (block budget)",
                        "indicators": entry_indicators(snapshot.as_dict()),
                    }
                )
                continue
            entry_event = {
                "time": event_time,
                "symbol": symbol,
                "entry_price": str(snapshot.price),
                "qty": str(qty),
                "notional": str(notional.quantize(Decimal("0.000001"))),
                "score": str(candidate.get("score")),
                "selection_engine": "app_engine",
                "universe_source": universe_source,
                "top_volume_source": evaluation_source if universe_source == "top_volume" else "",
                "entry_indicators": entry_indicators(snapshot.as_dict()),
            }
            self.positions[symbol] = ReplayPosition(symbol, qty, snapshot.price, entry_event)
            self.accepted_trades.append(entry_event)
            self.account["buying_power"] = str(decimal_value(self.account["buying_power"]) - notional)

    def handle_event(self, event: dict[str, Any]) -> None:
        kind = str(event.get("kind") or "")
        payload = event_payload(event)
        warmup = bool(event.get("_backtest_warmup"))
        if warmup:
            self.warmup_events += 1
        if kind == "parse_error":
            self.parse_errors += 1
        elif kind == "top_volume_snapshot":
            self.apply_top_volume(payload)
        elif kind == "market_bar":
            self.ingest_bar(payload)
        elif kind == "strategy_scan":
            self.update_config(payload)
            self.apply_strategy_scan_top_volume(payload)
            if not warmup:
                self.evaluate_entries(str(event.get("time") or ""))

    def summary(self) -> dict[str, Any]:
        winners = [trade for trade in self.closed_trades if trade.get("winner")]
        losers = [trade for trade in self.closed_trades if not trade.get("winner")]
        return {
            "mode": "day_tape_backtest",
            "selection_engine": "app_engine",
            "strategy_overrides": dict(sorted(self.strategy_overrides.items())),
            "sizing_harness": self.harness.as_dict(),
            "counts": {
                "top_volume_snapshots": self.top_volume_snapshots,
                "top_volume_contexts": self.top_volume_contexts,
                "strategy_scan_top_volume_contexts": self.strategy_scan_top_volume_contexts,
                "market_bars": self.market_bars,
                "evaluations": self.evaluations,
                "accepted_trades": len(self.accepted_trades),
                "closed_trades": len(self.closed_trades),
                "open_positions": len(self.positions),
                "rejected_candidates": len(self.rejected_candidates),
                "parse_errors": self.parse_errors,
                "warmup_events": self.warmup_events,
            },
            "top_volume_sources": sorted(self.top_volume_sources),
            "expected_top_volume_source": TOP_VOLUME_SOURCE,
            "top_volume_snapshots_by_source": dict(sorted(self.top_volume_snapshots_by_source.items())),
            "top_volume_contexts_by_source": dict(sorted(self.top_volume_contexts_by_source.items())),
            "evaluations_by_top_volume_source": dict(sorted(self.evaluations_by_top_volume_source.items())),
            "accepted_trades": self.accepted_trades,
            "closed_trades": self.closed_trades,
            "rejected_candidates_sample": self.rejected_candidates[:50],
            "winner_indicator_averages": indicator_averages(winners),
            "loser_indicator_averages": indicator_averages(losers),
        }


def run_backtest(
    files: list[Path],
    max_events: int = 0,
    *,
    latest_events: bool = False,
    warmup_events: int = 0,
    strategy_overrides: dict[str, Any] | None = None,
    sizing_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    backtester = DayTapeBacktester(strategy_overrides=strategy_overrides, sizing_overrides=sizing_overrides)
    for event in iter_tape_events(
        files,
        max_events=max_events,
        latest_events=latest_events,
        warmup_events=warmup_events,
    ):
        backtester.handle_event(event)
    return backtester.summary()


def print_summary(summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    print("Day-tape backtest")
    print(f"  selection_engine: {summary['selection_engine']}")
    print(f"  top-volume sources: {', '.join(summary['top_volume_sources']) or 'none'}")
    expected_source = str(summary.get("expected_top_volume_source") or TOP_VOLUME_SOURCE)
    snapshots_by_source = summary.get("top_volume_snapshots_by_source")
    if isinstance(snapshots_by_source, dict):
        print(f"  {expected_source} snapshots: {int(snapshots_by_source.get(expected_source) or 0):,}")
    contexts_by_source = summary.get("top_volume_contexts_by_source")
    if isinstance(contexts_by_source, dict):
        print(f"  {expected_source} contexts: {int(contexts_by_source.get(expected_source) or 0):,}")
    evaluations_by_source = summary.get("evaluations_by_top_volume_source")
    if isinstance(evaluations_by_source, dict):
        print(f"  {expected_source} evaluations: {int(evaluations_by_source.get(expected_source) or 0):,}")
    print(f"  evaluations: {counts['evaluations']:,}")
    print(f"  top-volume contexts: {counts.get('top_volume_contexts', 0):,}")
    print(f"  scan-embedded top-volume contexts: {counts.get('strategy_scan_top_volume_contexts', 0):,}")
    print(f"  accepted trades: {counts['accepted_trades']:,}")
    print(f"  closed trades: {counts['closed_trades']:,}")
    print(f"  open positions: {counts['open_positions']:,}")
    print(f"  rejected candidates: {counts['rejected_candidates']:,}")
    print(f"  parse errors: {counts['parse_errors']:,}")
    print(f"  warmup events: {counts.get('warmup_events', 0):,}")
    print()
    print("Replay sizing harness")
    for key, value in summary["sizing_harness"].items():
        print(f"  {key}: {value}")
    if summary.get("strategy_overrides"):
        print()
        print("Strategy overrides")
        for key, value in summary["strategy_overrides"].items():
            print(f"  {key}: {value}")
    print()
    if summary["accepted_trades"]:
        print("Accepted trades")
        for trade in summary["accepted_trades"][:20]:
            print(
                f"  {trade['symbol']} score={trade['score']} "
                f"entry={trade['entry_price']} qty={trade['qty']} notional={trade['notional']}"
            )
    else:
        print("Accepted trades: none")
    print()
    if summary["rejected_candidates_sample"]:
        print("Rejected candidates sample")
        for row in summary["rejected_candidates_sample"][:20]:
            print(f"  {row['symbol']}: {row['reason']}")
    else:
        print("Rejected candidates sample: none")
    print()
    print("Winner indicator averages")
    print(json.dumps(summary["winner_indicator_averages"], indent=2, sort_keys=True))
    print("Loser indicator averages")
    print(json.dumps(summary["loser_indicator_averages"], indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest Alpaca Paper Trader day-tape files offline.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=1, help="Most-recent tape files to replay when --path is a directory.")
    parser.add_argument("--max-events", type=int, default=0, help="Stop after this many tape events. 0 means no limit.")
    parser.add_argument("--latest-events", action="store_true", help="Use the latest bounded event window instead of the start of the selected file set.")
    parser.add_argument("--warmup-events", type=int, default=0, help="When using --latest-events, process this many earlier events as indicator warm-up without entry evaluations.")
    parser.add_argument("--strategy-overrides-json", default="", help="JSON object of strategy parameter overrides.")
    parser.add_argument("--sizing-overrides-json", default="", help="JSON object of sizing harness overrides for labeled diagnostics.")
    parser.add_argument("--json", action="store_true", help="Print the full JSON summary.")
    args = parser.parse_args()

    files = selected_files(args.path, args.days)
    if not files:
        print(f"No day-tape files found in {args.path}")
        return 0
    summary = run_backtest(
        files,
        max(0, args.max_events),
        latest_events=bool(args.latest_events),
        warmup_events=max(0, args.warmup_events),
        strategy_overrides=json_object_arg(args.strategy_overrides_json, "--strategy-overrides-json"),
        sizing_overrides=json_object_arg(args.sizing_overrides_json, "--sizing-overrides-json"),
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
