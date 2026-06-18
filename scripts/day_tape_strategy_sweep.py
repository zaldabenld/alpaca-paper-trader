from __future__ import annotations

import argparse
import json
import os
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from decimal import Decimal
from decimal import ROUND_HALF_UP
from pathlib import Path
from typing import Any

from day_tape_simulator import (
    BucketMeta,
    BPS,
    ZERO,
    DayTapeSimulator,
    Position,
    bucket_key,
    money,
    parse_decimal,
    parse_time,
    percent,
    selected_files,
)


DEFAULT_EXIT_PAIRS = (
    ("scalp_1_0.5", Decimal("1.0"), Decimal("0.5")),
    ("scalp_1.5_0.75", Decimal("1.5"), Decimal("0.75")),
    ("balanced_2_1", Decimal("2.0"), Decimal("1.0")),
    ("balanced_2.5_1.25", Decimal("2.5"), Decimal("1.25")),
    ("trend_3_1.5", Decimal("3.0"), Decimal("1.5")),
    ("trend_4_2", Decimal("4.0"), Decimal("2.0")),
    ("wide_5_2", Decimal("5.0"), Decimal("2.0")),
)

ADAPTIVE_EXIT_PLANS = (
    ("trail_1.5_0.75", "trail", Decimal("0"), Decimal("1.0"), Decimal("1.5"), Decimal("0.75"), ZERO),
    ("trail_2_1", "trail", Decimal("0"), Decimal("1.25"), Decimal("2.0"), Decimal("1.0"), ZERO),
    ("trail_3_1.25", "trail", Decimal("0"), Decimal("1.5"), Decimal("3.0"), Decimal("1.25"), ZERO),
    ("lock_1.5_0.25", "lock", Decimal("0"), Decimal("1.0"), Decimal("1.5"), ZERO, Decimal("0.25")),
    ("lock_2_0.5", "lock", Decimal("0"), Decimal("1.25"), Decimal("2.0"), ZERO, Decimal("0.50")),
    ("lock_3_1", "lock", Decimal("0"), Decimal("1.5"), Decimal("3.0"), ZERO, Decimal("1.00")),
)

PROFILE_LIMITS = {
    "conservative": {
        "min_price": ZERO,
        "min_recent_momentum": Decimal("0.03"),
        "max_vwap_extension": Decimal("3.0"),
        "max_session_pullback": Decimal("1.5"),
        "max_recent_pullback": Decimal("0.75"),
    },
    "neutral": {
        "min_price": ZERO,
        "min_recent_momentum": Decimal("0.03"),
        "max_vwap_extension": Decimal("4.0"),
        "max_session_pullback": Decimal("2.0"),
        "max_recent_pullback": Decimal("1.0"),
    },
    "aggressive": {
        "min_price": ZERO,
        "min_recent_momentum": Decimal("0.02"),
        "max_vwap_extension": Decimal("5.0"),
        "max_session_pullback": Decimal("2.5"),
        "max_recent_pullback": Decimal("1.25"),
    },
}


@dataclass(frozen=True)
class EntryTemplate:
    name: str
    rsi_min: Decimal
    rsi_max: Decimal
    min_entry_score: Decimal
    min_momentum: Decimal
    min_recent_momentum: Decimal
    min_long_momentum: Decimal
    min_session_change: Decimal
    min_vwap_distance: Decimal
    max_vwap_distance: Decimal
    max_session_pullback: Decimal
    max_recent_pullback: Decimal
    min_smi: Decimal
    min_relative_volume: Decimal
    min_price: Decimal
    max_price: Decimal = ZERO
    max_relative_volume: Decimal = ZERO
    max_atr_percent: Decimal = ZERO
    max_volatility_percent: Decimal = ZERO
    score_weights: tuple[tuple[str, Decimal], ...] = ()
    score_bias: Decimal = ZERO


@dataclass(frozen=True)
class Candidate:
    name: str
    entry: EntryTemplate
    take_profit_percent: Decimal
    stop_loss_percent: Decimal
    reentry_score_boost: Decimal
    exit_style: str = "fixed"
    trail_activation_percent: Decimal = ZERO
    trail_distance_percent: Decimal = ZERO
    profit_lock_percent: Decimal = ZERO


@dataclass
class ScanEvent:
    time: Any
    bucket: str
    market_open: bool
    trading_enabled: bool
    entries_allowed: bool
    rows: list[dict[str, Any]]


@dataclass
class PriceEvent:
    time: Any
    symbol: str
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass
class BucketProfile:
    key: str
    label: str
    config: dict[str, Any]
    starting_equity: Decimal
    starting_cash: Decimal
    source_keys: list[str] = field(default_factory=list)


@dataclass
class SweepMetrics:
    candidate: Candidate
    bucket: str
    label: str
    starting_equity: Decimal
    ending_equity: Decimal = ZERO
    cash: Decimal = ZERO
    realized_pl: Decimal = ZERO
    unrealized_pl: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    peak_equity: Decimal = ZERO
    buys: int = 0
    exits: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    open_positions: int = 0
    exposure: Decimal = ZERO
    gross_profit: Decimal = ZERO
    gross_loss: Decimal = ZERO
    skipped_budget: int = 0
    skipped_reentry: int = 0
    trades: list[dict[str, Any]] = field(default_factory=list)

    @property
    def pnl(self) -> Decimal:
        return self.ending_equity - self.starting_equity

    @property
    def pnl_percent(self) -> Decimal:
        if self.starting_equity <= ZERO:
            return ZERO
        return self.pnl / self.starting_equity * Decimal("100")

    @property
    def drawdown_percent(self) -> Decimal:
        if self.peak_equity <= ZERO:
            return ZERO
        return self.max_drawdown / self.peak_equity * Decimal("100")

    @property
    def profit_factor(self) -> Decimal | None:
        if self.gross_loss > ZERO:
            return self.gross_profit / self.gross_loss
        if self.gross_profit > ZERO:
            return Decimal("99")
        return None

    @property
    def win_rate(self) -> Decimal:
        closed = self.wins + self.losses + self.flats
        if closed <= 0:
            return ZERO
        return Decimal(self.wins) / Decimal(closed) * Decimal("100")

    @property
    def expectancy(self) -> Decimal:
        if self.exits <= 0:
            return ZERO
        return self.realized_pl / Decimal(self.exits)


@dataclass
class SweepState:
    profile: BucketProfile
    candidate: Candidate
    cash: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    entry_times: dict[str, Any] = field(default_factory=dict)
    high_water: dict[str, Decimal] = field(default_factory=dict)
    active_stops: dict[str, Decimal] = field(default_factory=dict)
    last_prices: dict[str, Decimal] = field(default_factory=dict)
    realized_pl: Decimal = ZERO
    gross_profit: Decimal = ZERO
    gross_loss: Decimal = ZERO
    peak_equity: Decimal = ZERO
    max_drawdown: Decimal = ZERO
    buys: int = 0
    exits: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    skipped_budget: int = 0
    skipped_reentry: int = 0
    reentry_floors: dict[str, Decimal] = field(default_factory=dict)
    min_stop_hold_minutes: int = 0
    collect_trades: bool = False
    trades: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.peak_equity = self.profile.starting_equity

    def equity(self) -> Decimal:
        return self.cash + sum((position.market_value for position in self.positions.values()), ZERO)

    def exposure(self) -> Decimal:
        return sum((position.market_value for position in self.positions.values()), ZERO)

    def record_equity(self) -> None:
        current = self.equity()
        if current > self.peak_equity:
            self.peak_equity = current
        drawdown = self.peak_equity - current
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def update_price(self, symbol: str, price: Decimal) -> None:
        self.last_prices[symbol] = price
        position = self.positions.get(symbol)
        if position:
            position.last_price = price

    def held_minutes(self, symbol: str, when: Any) -> Decimal:
        entry_time = self.entry_times.get(symbol)
        if entry_time is None or when is None:
            return ZERO
        return Decimal(str(round((when - entry_time).total_seconds() / 60, 4)))

    def fill_entry(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        score: Decimal,
        when: Any = None,
        row: dict[str, Any] | None = None,
    ) -> None:
        if qty <= ZERO or price <= ZERO:
            return
        cost = qty * price
        if cost > self.cash:
            self.skipped_budget += 1
            return
        position = self.positions.setdefault(symbol, Position(symbol=symbol))
        position.buy(qty, price)
        self.entry_times.setdefault(symbol, when)
        self.high_water[symbol] = max(self.high_water.get(symbol, price), price)
        self.cash -= cost
        self.buys += 1
        self.reentry_floors[symbol] = max(
            self.candidate.entry.min_entry_score,
            score + self.candidate.reentry_score_boost,
        )
        if self.collect_trades:
            self.trades.append(
                {
                    "event": "entry",
                    "time": time_payload(when),
                    "symbol": symbol,
                    "qty": decimal_payload(qty),
                    "price": decimal_payload(price),
                    "score": decimal_payload(score),
                    "cash_after": decimal_payload(self.cash),
                    "features": entry_feature_payload(row, score) if row is not None else {},
                }
            )
        self.record_equity()

    def fill_exit(self, symbol: str, price: Decimal, reason: str = "exit", when: Any = None) -> None:
        position = self.positions.get(symbol)
        if not position or position.qty <= ZERO:
            return
        qty = position.qty
        entry_price = position.average_price
        entry_time = self.entry_times.get(symbol)
        sold, cost = position.sell(qty)
        if sold <= ZERO:
            return
        proceeds = sold * price
        realized = proceeds - cost
        self.cash += proceeds
        self.realized_pl += realized
        self.exits += 1
        if realized > ZERO:
            self.wins += 1
            self.gross_profit += realized
        elif realized < ZERO:
            self.losses += 1
            self.gross_loss += abs(realized)
        else:
            self.flats += 1
        self.positions.pop(symbol, None)
        self.entry_times.pop(symbol, None)
        self.high_water.pop(symbol, None)
        self.active_stops.pop(symbol, None)
        if self.collect_trades:
            held_minutes = self.held_minutes(symbol, when)
            if entry_time is not None and when is not None:
                held_minutes = Decimal(str(round((when - entry_time).total_seconds() / 60, 4)))
            self.trades.append(
                {
                    "event": "exit",
                    "time": time_payload(when),
                    "symbol": symbol,
                    "qty": decimal_payload(sold),
                    "entry_price": decimal_payload(entry_price),
                    "exit_price": decimal_payload(price),
                    "reason": reason,
                    "realized_pl": decimal_payload(realized),
                    "gain_percent": decimal_payload((price - entry_price) / entry_price * Decimal("100") if entry_price > ZERO else ZERO),
                    "held_minutes": decimal_payload(held_minutes),
                    "cash_after": decimal_payload(self.cash),
                }
            )
        self.record_equity()

    def maybe_exit(self, symbol: str, high: Decimal, low: Decimal, close: Decimal, when: Any = None) -> None:
        position = self.positions.get(symbol)
        if not position or position.qty <= ZERO:
            return
        entry = position.average_price
        if entry <= ZERO:
            return
        base_stop = entry * (Decimal("1") - self.candidate.stop_loss_percent / Decimal("100"))
        stop = max(base_stop, self.active_stops.get(symbol, ZERO))
        if low <= stop:
            if stop <= base_stop and self.min_stop_hold_minutes > 0:
                if self.held_minutes(symbol, when) < Decimal(self.min_stop_hold_minutes):
                    return
            self.fill_exit(symbol, min(stop, close), "stop_loss", when)
            return

        if self.candidate.exit_style == "fixed":
            target = entry * (Decimal("1") + self.candidate.take_profit_percent / Decimal("100"))
            if high >= target:
                self.fill_exit(symbol, target, "take_profit", when)
            return

        high_water = max(self.high_water.get(symbol, entry), high)
        self.high_water[symbol] = high_water
        gain_percent = (high_water - entry) / entry * Decimal("100")
        adaptive_stop = ZERO
        if self.candidate.exit_style == "trail" and gain_percent >= self.candidate.trail_activation_percent:
            adaptive_stop = high_water * (Decimal("1") - self.candidate.trail_distance_percent / Decimal("100"))
        elif self.candidate.exit_style == "lock" and gain_percent >= self.candidate.trail_activation_percent:
            adaptive_stop = entry * (Decimal("1") + self.candidate.profit_lock_percent / Decimal("100"))
        if adaptive_stop > ZERO:
            stop = max(stop, adaptive_stop)
            self.active_stops[symbol] = stop
        if low <= stop:
            self.fill_exit(symbol, min(stop, close), f"{self.candidate.exit_style}_stop", when)

    def maybe_time_exit(self, symbol: str, when: Any, price: Decimal, max_hold_minutes: int) -> None:
        if max_hold_minutes <= 0:
            return
        position = self.positions.get(symbol)
        entry_time = self.entry_times.get(symbol)
        if not position or position.qty <= ZERO or entry_time is None or when is None:
            return
        if (when - entry_time).total_seconds() >= max_hold_minutes * 60:
            self.fill_exit(symbol, price, "time_exit", when)

    def liquidate_all(self, slippage_bps: Decimal, when: Any = None) -> None:
        for symbol, position in list(self.positions.items()):
            price = self.last_prices.get(symbol, position.last_price)
            if price <= ZERO:
                price = position.average_price
            if price <= ZERO:
                continue
            if slippage_bps > ZERO:
                price = max(ZERO, price - price * slippage_bps / BPS)
            self.fill_exit(symbol, price, "close_liquidation", when)

    def metrics(self) -> SweepMetrics:
        ending = self.equity()
        unrealized = sum((position.market_value - position.cost_basis for position in self.positions.values()), ZERO)
        return SweepMetrics(
            candidate=self.candidate,
            bucket=self.profile.key,
            label=self.profile.label,
            starting_equity=self.profile.starting_equity,
            ending_equity=ending,
            cash=self.cash,
            realized_pl=self.realized_pl,
            unrealized_pl=unrealized,
            max_drawdown=self.max_drawdown,
            peak_equity=self.peak_equity,
            buys=self.buys,
            exits=self.exits,
            wins=self.wins,
            losses=self.losses,
            flats=self.flats,
            open_positions=len(self.positions),
            exposure=self.exposure(),
            gross_profit=self.gross_profit,
            gross_loss=self.gross_loss,
            skipped_budget=self.skipped_budget,
            skipped_reentry=self.skipped_reentry,
            trades=self.trades,
        )


def default_tape_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader" / "day-tape"


def tape_file_date(path: Path) -> str:
    name = path.name
    if name.startswith("tape-") and name.endswith(".jsonl"):
        return name[5:13]
    return ""


def selected_sweep_files(path: Path, days: int, end_date: str = "") -> list[Path]:
    if path.is_file():
        return [path]
    files = sorted(path.glob("tape-*.jsonl"), key=lambda item: item.name)
    if end_date:
        files = [item for item in files if tape_file_date(item) <= end_date]
    return files[-max(1, days) :]


def move_validation_date_to_end(files: list[Path], validation_date: str) -> list[Path]:
    if not validation_date:
        return files
    validation_files = [path for path in files if tape_file_date(path) == validation_date]
    if not validation_files:
        names = ", ".join(path.name for path in files) or "none"
        raise ValueError(f"validation date {validation_date} is not in selected files: {names}")
    train_files = [path for path in files if tape_file_date(path) != validation_date]
    return train_files + validation_files


def line_matches_kind(line: str, kind: str) -> bool:
    return f'"kind":"{kind}"' in line or f'"kind": "{kind}"' in line


def iter_relevant_events(files: list[Path], kinds: set[str]):
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if not any(line_matches_kind(line, kind) for kind in kinds):
                    continue
                try:
                    yield path, line_number, json.loads(line)
                except json.JSONDecodeError:
                    continue


def parse_row_decimal(row: dict[str, Any], raw_key: str, display_key: str = "") -> Decimal:
    if raw_key in row:
        return parse_decimal(row.get(raw_key))
    if display_key:
        return parse_decimal(row.get(display_key))
    return ZERO


def parse_relative_volume(row: dict[str, Any]) -> Decimal:
    value = row.get("relative_volume_raw")
    if value not in (None, ""):
        return parse_decimal(value)
    text = str(row.get("relative_volume") or "").lower().replace("x", "")
    return parse_decimal(text)


def parse_buy_flow_ratio(row: dict[str, Any]) -> Decimal | None:
    buy_volume = parse_row_decimal(row, "buy_volume_raw", "buy_volume")
    sell_volume = parse_row_decimal(row, "sell_volume_raw", "sell_volume")
    classified = buy_volume + sell_volume
    if classified <= ZERO:
        return None
    return buy_volume / classified


def clamp_unit(value: Decimal) -> Decimal:
    return max(ZERO, min(Decimal("1"), value))


def entry_feature_payload(row: dict[str, Any], score: Decimal) -> dict[str, Any]:
    return {
        "row_price": decimal_payload(parse_row_decimal(row, "price_raw", "price")),
        "score": decimal_payload(score),
        "rsi": decimal_payload(parse_row_decimal(row, "rsi_raw", "rsi")),
        "momentum": decimal_payload(parse_row_decimal(row, "momentum_raw", "momentum")),
        "recent_momentum": decimal_payload(parse_row_decimal(row, "recent_momentum_raw", "recent_momentum")),
        "long_momentum": decimal_payload(parse_row_decimal(row, "long_momentum_raw", "long_momentum")),
        "session_change": decimal_payload(parse_row_decimal(row, "session_change_raw", "session_change")),
        "vwap_distance": decimal_payload(parse_row_decimal(row, "vwap_distance_raw", "vwap_distance")),
        "session_pullback": decimal_payload(parse_row_decimal(row, "session_pullback_raw", "session_pullback")),
        "recent_pullback": decimal_payload(parse_row_decimal(row, "recent_pullback_raw", "recent_pullback")),
        "smi": decimal_payload(parse_row_decimal(row, "smi_raw", "smi")),
        "relative_volume": decimal_payload(parse_relative_volume(row)),
        "atr": decimal_payload(parse_row_decimal(row, "atr_raw", "atr")),
        "volatility": decimal_payload(parse_row_decimal(row, "volatility_raw", "volatility")),
        "bias": str(row.get("bias") or ""),
        "last_action": str(row.get("last_action") or ""),
    }


def config_decimal(config: dict[str, Any], key: str, default: Decimal = ZERO) -> Decimal:
    return parse_decimal(config.get(key), default)


def config_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(1, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def profile_with_simulation_overrides(
    profile: BucketProfile,
    simulation_max_positions: int = 0,
    simulation_sizing_positions: int = 0,
    inverse_etf_mode: str = "",
) -> BucketProfile:
    config = dict(profile.config)
    if simulation_max_positions > 0:
        value = max(1, int(simulation_max_positions))
        config["simulation_max_open_positions"] = value
        config["max_open_positions"] = value
    if simulation_sizing_positions > 0:
        config["simulation_sizing_positions"] = max(1, int(simulation_sizing_positions))
    if inverse_etf_mode:
        config["inverse_etf_mode"] = inverse_etf_mode
    return BucketProfile(
        key=profile.key,
        label=profile.label,
        config=config,
        starting_equity=profile.starting_equity,
        starting_cash=profile.starting_cash,
        source_keys=list(profile.source_keys),
    )


def profile_limits(config: dict[str, Any]) -> dict[str, Decimal]:
    profile = str(config.get("profile") or "neutral").lower()
    return PROFILE_LIMITS.get(profile, PROFILE_LIMITS["neutral"])


def entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    current = EntryTemplate(
        name="current_gates",
        rsi_min=config_decimal(config, "buy_rsi_min", Decimal("40")),
        rsi_max=config_decimal(config, "buy_rsi_max", Decimal("70")),
        min_entry_score=config_decimal(config, "min_entry_score", Decimal("38")),
        min_momentum=config_decimal(config, "min_momentum_percent", Decimal("0.05")),
        min_recent_momentum=limits["min_recent_momentum"],
        min_long_momentum=ZERO,
        min_session_change=ZERO,
        min_vwap_distance=ZERO,
        max_vwap_distance=limits["max_vwap_extension"],
        max_session_pullback=limits["max_session_pullback"],
        max_recent_pullback=limits["max_recent_pullback"],
        min_smi=config_decimal(config, "min_smi", Decimal("5")),
        min_relative_volume=config_decimal(config, "volume_multiplier", Decimal("1.0")),
        min_price=limits["min_price"],
    )
    return [
        current,
        EntryTemplate(
            name="balanced_quality",
            rsi_min=Decimal("40"),
            rsi_max=Decimal("72"),
            min_entry_score=max(current.min_entry_score, Decimal("42")),
            min_momentum=Decimal("0.08"),
            min_recent_momentum=Decimal("0.05"),
            min_long_momentum=Decimal("0.03"),
            min_session_change=Decimal("0.03"),
            min_vwap_distance=Decimal("0.03"),
            max_vwap_distance=min(current.max_vwap_distance, Decimal("3.5")),
            max_session_pullback=min(current.max_session_pullback, Decimal("1.25")),
            max_recent_pullback=min(current.max_recent_pullback, Decimal("0.75")),
            min_smi=max(current.min_smi, Decimal("5")),
            min_relative_volume=max(Decimal("0.80"), min(current.min_relative_volume, Decimal("1.0"))),
            min_price=current.min_price,
        ),
        EntryTemplate(
            name="strict_trend",
            rsi_min=Decimal("45"),
            rsi_max=Decimal("68"),
            min_entry_score=max(current.min_entry_score, Decimal("48")),
            min_momentum=Decimal("0.12"),
            min_recent_momentum=Decimal("0.08"),
            min_long_momentum=Decimal("0.08"),
            min_session_change=Decimal("0.08"),
            min_vwap_distance=Decimal("0.05"),
            max_vwap_distance=min(current.max_vwap_distance, Decimal("2.5")),
            max_session_pullback=min(current.max_session_pullback, Decimal("0.9")),
            max_recent_pullback=min(current.max_recent_pullback, Decimal("0.6")),
            min_smi=max(current.min_smi, Decimal("10")),
            min_relative_volume=max(Decimal("0.90"), current.min_relative_volume),
            min_price=current.min_price,
        ),
        EntryTemplate(
            name="momentum_breakout",
            rsi_min=Decimal("45"),
            rsi_max=Decimal("78"),
            min_entry_score=max(current.min_entry_score, Decimal("45")),
            min_momentum=Decimal("0.18"),
            min_recent_momentum=Decimal("0.10"),
            min_long_momentum=Decimal("0.10"),
            min_session_change=Decimal("0.15"),
            min_vwap_distance=Decimal("0.10"),
            max_vwap_distance=min(current.max_vwap_distance, Decimal("4.0")),
            max_session_pullback=min(current.max_session_pullback, Decimal("1.0")),
            max_recent_pullback=min(current.max_recent_pullback, Decimal("0.7")),
            min_smi=max(current.min_smi, Decimal("8")),
            min_relative_volume=max(Decimal("1.0"), current.min_relative_volume),
            min_price=current.min_price,
        ),
        EntryTemplate(
            name="vwap_pullback_control",
            rsi_min=Decimal("38"),
            rsi_max=Decimal("66"),
            min_entry_score=max(current.min_entry_score, Decimal("44")),
            min_momentum=Decimal("0.08"),
            min_recent_momentum=Decimal("0.04"),
            min_long_momentum=Decimal("0.05"),
            min_session_change=Decimal("0.05"),
            min_vwap_distance=Decimal("0.02"),
            max_vwap_distance=min(current.max_vwap_distance, Decimal("2.0")),
            max_session_pullback=min(current.max_session_pullback, Decimal("0.65")),
            max_recent_pullback=min(current.max_recent_pullback, Decimal("0.45")),
            min_smi=max(current.min_smi, Decimal("5")),
            min_relative_volume=max(Decimal("0.85"), min(current.min_relative_volume, Decimal("1.0"))),
            min_price=current.min_price,
        ),
        EntryTemplate(
            name="defensive_confirmation",
            rsi_min=Decimal("42"),
            rsi_max=Decimal("65"),
            min_entry_score=max(current.min_entry_score, Decimal("50")),
            min_momentum=Decimal("0.15"),
            min_recent_momentum=Decimal("0.08"),
            min_long_momentum=Decimal("0.12"),
            min_session_change=Decimal("0.12"),
            min_vwap_distance=Decimal("0.05"),
            max_vwap_distance=min(current.max_vwap_distance, Decimal("2.25")),
            max_session_pullback=min(current.max_session_pullback, Decimal("0.75")),
            max_recent_pullback=min(current.max_recent_pullback, Decimal("0.5")),
            min_smi=max(current.min_smi, Decimal("12")),
            min_relative_volume=max(Decimal("1.0"), current.min_relative_volume),
            min_price=current.min_price,
        ),
    ]


def candidates_for_config(config: dict[str, Any]) -> list[Candidate]:
    templates = entry_templates(config)
    return build_candidates(config, templates)


def quantile_decimal(values: list[Decimal], pct: Decimal, default: Decimal = ZERO) -> Decimal:
    if not values:
        return default
    ordered = sorted(values)
    clipped = min(Decimal("1"), max(ZERO, pct))
    index = int(Decimal(len(ordered) - 1) * clipped)
    return ordered[index]


def clamp_decimal(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(max(value, low), high)


def build_price_index(events: list[Any]) -> tuple[dict[str, list[PriceEvent]], dict[str, list[Any]]]:
    bars_by_symbol: dict[str, list[PriceEvent]] = {}
    for event in events:
        if isinstance(event, PriceEvent) and event.time is not None:
            bars_by_symbol.setdefault(event.symbol, []).append(event)
    times_by_symbol: dict[str, list[Any]] = {}
    for symbol, bars in bars_by_symbol.items():
        bars.sort(key=lambda item: item.time)
        times_by_symbol[symbol] = [bar.time for bar in bars]
    return bars_by_symbol, times_by_symbol


def forward_outcome_percent(
    event_time: Any,
    row: dict[str, Any],
    bars_by_symbol: dict[str, list[PriceEvent]],
    times_by_symbol: dict[str, list[Any]],
    take_profit_percent: Decimal,
    stop_loss_percent: Decimal,
) -> Decimal | None:
    if event_time is None:
        return None
    symbol = str(row.get("symbol") or "").strip().upper()
    entry = parse_row_decimal(row, "price_raw", "price")
    bars = bars_by_symbol.get(symbol)
    times = times_by_symbol.get(symbol)
    if not symbol or entry <= ZERO or not bars or not times:
        return None
    stop = entry * (Decimal("1") - stop_loss_percent / Decimal("100"))
    target = entry * (Decimal("1") + take_profit_percent / Decimal("100"))
    index = bisect_right(times, event_time)
    if index >= len(bars):
        return None
    exit_price = entry
    for bar in bars[index:]:
        exit_price = bar.close
        if bar.low <= stop:
            exit_price = min(stop, bar.close)
            break
        if bar.high >= target:
            exit_price = target
            break
    return (exit_price - entry) / entry * Decimal("100")


def research_feature_samples(events: list[Any], config: dict[str, Any]) -> list[dict[str, Decimal]]:
    current_tp = config_decimal(config, "take_profit_percent", Decimal("3"))
    current_sl = config_decimal(config, "stop_loss_percent", Decimal("2"))
    if current_tp <= ZERO or current_sl <= ZERO:
        return []
    bars_by_symbol, times_by_symbol = build_price_index(events)
    min_price = profile_limits(config)["min_price"]
    samples: list[dict[str, Decimal]] = []
    for event in events:
        if not isinstance(event, ScanEvent):
            continue
        if not event.market_open or not event.trading_enabled or not event.entries_allowed:
            continue
        for row in event.rows:
            if str(row.get("bias") or "").strip() != "Bullish":
                continue
            price = parse_row_decimal(row, "price_raw", "price")
            if price < min_price:
                continue
            outcome = forward_outcome_percent(
                event.time,
                row,
                bars_by_symbol,
                times_by_symbol,
                current_tp,
                current_sl,
            )
            if outcome is None:
                continue
            samples.append(
                {
                    "outcome": outcome,
                    "price": price,
                    "rsi": parse_row_decimal(row, "rsi_raw", "rsi"),
                    "entry_score": parse_row_decimal(row, "entry_score_raw", "entry_score"),
                    "momentum": parse_row_decimal(row, "momentum_raw", "momentum"),
                    "recent_momentum": parse_row_decimal(row, "recent_momentum_raw", "recent_momentum"),
                    "long_momentum": parse_row_decimal(row, "long_momentum_raw", "long_momentum"),
                    "session_change": parse_row_decimal(row, "session_change_raw", "session_change"),
                    "vwap_distance": parse_row_decimal(row, "vwap_distance_raw", "vwap_distance"),
                    "session_pullback": parse_row_decimal(row, "session_pullback_raw", "session_pullback"),
                    "recent_pullback": parse_row_decimal(row, "recent_pullback_raw", "recent_pullback"),
                    "smi": parse_row_decimal(row, "smi_raw", "smi"),
                    "relative_volume": parse_relative_volume(row),
                }
            )
    return samples


def sample_quantile(samples: list[dict[str, Decimal]], key: str, pct: Decimal, default: Decimal = ZERO) -> Decimal:
    return quantile_decimal([sample[key] for sample in samples if key in sample], pct, default)


def research_entry_templates(events: list[Any], config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    samples = research_feature_samples(events, config)
    current_score = config_decimal(config, "min_entry_score", Decimal("38"))
    score_floor = min(current_score, Decimal("30"))
    qualified = [sample for sample in samples if sample["entry_score"] >= score_floor]
    qualified_winners = [sample for sample in qualified if sample["outcome"] > ZERO]
    all_winners = [sample for sample in samples if sample["outcome"] > ZERO]
    if len(qualified_winners) >= 5:
        source = qualified_winners
    elif len(qualified) >= 5:
        source = qualified
    elif len(all_winners) >= 20:
        source = all_winners
    else:
        source = samples
    if len(source) < 5:
        return entry_templates(config)

    specs = (
        ("research_win_q10_90", Decimal("0.10"), Decimal("0.90")),
        ("research_win_q20_80", Decimal("0.20"), Decimal("0.80")),
        ("research_win_q35_70", Decimal("0.35"), Decimal("0.70")),
        ("research_win_q50_65", Decimal("0.50"), Decimal("0.65")),
    )
    templates: list[EntryTemplate] = []
    seen: set[tuple[Any, ...]] = set()
    for name, lower_q, upper_q in specs:
        min_vwap = max(ZERO, sample_quantile(source, "vwap_distance", lower_q))
        max_vwap = min(
            limits["max_vwap_extension"],
            max(min_vwap + Decimal("0.05"), sample_quantile(source, "vwap_distance", upper_q)),
        )
        rsi_min = clamp_decimal(sample_quantile(source, "rsi", lower_q, Decimal("40")), Decimal("20"), Decimal("85"))
        rsi_max = clamp_decimal(sample_quantile(source, "rsi", upper_q, Decimal("75")), rsi_min, Decimal("90"))
        template = EntryTemplate(
            name=name,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
            min_entry_score=max(score_floor, sample_quantile(source, "entry_score", lower_q)),
            min_momentum=max(ZERO, sample_quantile(source, "momentum", lower_q)),
            min_recent_momentum=max(ZERO, sample_quantile(source, "recent_momentum", lower_q)),
            min_long_momentum=max(ZERO, sample_quantile(source, "long_momentum", lower_q)),
            min_session_change=max(ZERO, sample_quantile(source, "session_change", lower_q)),
            min_vwap_distance=min_vwap,
            max_vwap_distance=max_vwap,
            max_session_pullback=min(limits["max_session_pullback"], max(ZERO, sample_quantile(source, "session_pullback", upper_q))),
            max_recent_pullback=min(limits["max_recent_pullback"], max(ZERO, sample_quantile(source, "recent_pullback", upper_q))),
            min_smi=max(ZERO, sample_quantile(source, "smi", lower_q)),
            min_relative_volume=max(Decimal("0.01"), sample_quantile(source, "relative_volume", lower_q)),
            min_price=limits["min_price"],
        )
        key = (
            template.rsi_min,
            template.rsi_max,
            template.min_entry_score,
            template.min_momentum,
            template.min_recent_momentum,
            template.min_long_momentum,
            template.min_session_change,
            template.min_vwap_distance,
            template.max_vwap_distance,
            template.max_session_pullback,
            template.max_recent_pullback,
            template.min_smi,
            template.min_relative_volume,
        )
        if key in seen:
            continue
        seen.add(key)
        templates.append(template)
    return templates or entry_templates(config)


def broad_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    current_score = config_decimal(config, "min_entry_score", Decimal("38"))
    base_min_price = limits["min_price"]
    families = [
        (
            "loose_direction",
            Decimal("35"),
            Decimal("82"),
            Decimal("0.03"),
            Decimal("0.02"),
            ZERO,
            ZERO,
            ZERO,
            limits["max_vwap_extension"],
            limits["max_session_pullback"],
            limits["max_recent_pullback"],
            config_decimal(config, "min_smi", Decimal("5")),
            max(Decimal("0.75"), min(config_decimal(config, "volume_multiplier", Decimal("1")), Decimal("1"))),
        ),
        (
            "balanced_quality",
            Decimal("40"),
            Decimal("72"),
            Decimal("0.08"),
            Decimal("0.05"),
            Decimal("0.03"),
            Decimal("0.03"),
            Decimal("0.03"),
            min(limits["max_vwap_extension"], Decimal("3.5")),
            min(limits["max_session_pullback"], Decimal("1.25")),
            min(limits["max_recent_pullback"], Decimal("0.75")),
            max(config_decimal(config, "min_smi", Decimal("5")), Decimal("5")),
            max(Decimal("0.80"), min(config_decimal(config, "volume_multiplier", Decimal("1")), Decimal("1"))),
        ),
        (
            "strict_trend",
            Decimal("45"),
            Decimal("68"),
            Decimal("0.12"),
            Decimal("0.08"),
            Decimal("0.08"),
            Decimal("0.08"),
            Decimal("0.05"),
            min(limits["max_vwap_extension"], Decimal("2.5")),
            min(limits["max_session_pullback"], Decimal("0.9")),
            min(limits["max_recent_pullback"], Decimal("0.6")),
            max(config_decimal(config, "min_smi", Decimal("5")), Decimal("10")),
            max(Decimal("0.90"), config_decimal(config, "volume_multiplier", Decimal("1"))),
        ),
        (
            "momentum_breakout",
            Decimal("45"),
            Decimal("78"),
            Decimal("0.18"),
            Decimal("0.10"),
            Decimal("0.10"),
            Decimal("0.15"),
            Decimal("0.10"),
            min(limits["max_vwap_extension"], Decimal("4.0")),
            min(limits["max_session_pullback"], Decimal("1.0")),
            min(limits["max_recent_pullback"], Decimal("0.7")),
            max(config_decimal(config, "min_smi", Decimal("5")), Decimal("8")),
            max(Decimal("1.0"), config_decimal(config, "volume_multiplier", Decimal("1"))),
        ),
        (
            "vwap_pullback_control",
            Decimal("38"),
            Decimal("66"),
            Decimal("0.08"),
            Decimal("0.04"),
            Decimal("0.05"),
            Decimal("0.05"),
            Decimal("0.02"),
            min(limits["max_vwap_extension"], Decimal("2.0")),
            min(limits["max_session_pullback"], Decimal("0.65")),
            min(limits["max_recent_pullback"], Decimal("0.45")),
            max(config_decimal(config, "min_smi", Decimal("5")), Decimal("5")),
            max(Decimal("0.85"), min(config_decimal(config, "volume_multiplier", Decimal("1")), Decimal("1"))),
        ),
        (
            "defensive_confirmation",
            Decimal("42"),
            Decimal("65"),
            Decimal("0.15"),
            Decimal("0.08"),
            Decimal("0.12"),
            Decimal("0.12"),
            Decimal("0.05"),
            min(limits["max_vwap_extension"], Decimal("2.25")),
            min(limits["max_session_pullback"], Decimal("0.75")),
            min(limits["max_recent_pullback"], Decimal("0.5")),
            max(config_decimal(config, "min_smi", Decimal("5")), Decimal("12")),
            max(Decimal("1.0"), config_decimal(config, "volume_multiplier", Decimal("1"))),
        ),
    ]
    score_levels = sorted(
        {
            max(Decimal("30"), current_score - Decimal("5")),
            current_score,
            max(current_score + Decimal("4"), Decimal("42")),
            max(current_score + Decimal("8"), Decimal("46")),
            max(current_score + Decimal("12"), Decimal("50")),
        }
    )
    templates: list[EntryTemplate] = []
    seen: set[tuple[Any, ...]] = set()
    for score in score_levels:
        for (
            family,
            rsi_min,
            rsi_max,
            momentum,
            recent,
            long_momentum,
            session,
            min_vwap,
            max_vwap,
            max_session_pullback,
            max_recent_pullback,
            min_smi,
            rel_volume,
        ) in families:
            key = (
                family,
                score,
                rsi_min,
                rsi_max,
                momentum,
                recent,
                long_momentum,
                session,
                min_vwap,
                max_vwap,
                max_session_pullback,
                max_recent_pullback,
                min_smi,
                rel_volume,
            )
            if key in seen:
                continue
            seen.add(key)
            templates.append(
                EntryTemplate(
                    name=f"{family}_score_{score}",
                    rsi_min=rsi_min,
                    rsi_max=rsi_max,
                    min_entry_score=score,
                    min_momentum=momentum,
                    min_recent_momentum=recent,
                    min_long_momentum=long_momentum,
                    min_session_change=session,
                    min_vwap_distance=min_vwap,
                    max_vwap_distance=max_vwap,
                    max_session_pullback=max_session_pullback,
                    max_recent_pullback=max_recent_pullback,
                    min_smi=min_smi,
                    min_relative_volume=rel_volume,
                    min_price=base_min_price,
                )
            )
    return templates


def impulse_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    base_min_price = limits["min_price"]
    templates: list[EntryTemplate] = []
    for score in (Decimal("35"), Decimal("42"), Decimal("50")):
        for session in (Decimal("1.0"), Decimal("1.3")):
            for smi in (Decimal("70"), Decimal("75")):
                templates.append(
                    EntryTemplate(
                        name=f"impulse_session_{session}_smi_{smi}_score_{score}",
                        rsi_min=Decimal("50"),
                        rsi_max=Decimal("72"),
                        min_entry_score=score,
                        min_momentum=Decimal("0.45"),
                        min_recent_momentum=Decimal("0.50"),
                        min_long_momentum=Decimal("0.80"),
                        min_session_change=session,
                        min_vwap_distance=Decimal("0.25"),
                        max_vwap_distance=Decimal("2.25"),
                        max_session_pullback=Decimal("0.50"),
                        max_recent_pullback=Decimal("0.35"),
                        min_smi=smi,
                        min_relative_volume=Decimal("1.0"),
                        min_price=base_min_price,
                        max_relative_volume=Decimal("5.0"),
                        max_atr_percent=Decimal("0.50"),
                        max_volatility_percent=Decimal("0.50"),
                    )
                )
    return templates


def riskbox_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    """Evidence-focused templates around the trade-price near misses."""
    limits = profile_limits(config)
    base_min_price = limits["min_price"]
    templates: list[EntryTemplate] = []
    for score in (Decimal("30"), Decimal("35")):
        for smi in (Decimal("30"), Decimal("40"), Decimal("50")):
            for session in (Decimal("0.05"), Decimal("0.25"), Decimal("0.40")):
                for cap_name, max_relative_volume, max_atr, max_volatility in (
                    ("open", ZERO, ZERO, ZERO),
                    ("relvol8", Decimal("8.0"), ZERO, ZERO),
                    ("wide_calm", Decimal("12.0"), Decimal("1.20"), Decimal("1.00")),
                    ("calm", Decimal("8.0"), Decimal("0.50"), Decimal("0.50")),
                ):
                    templates.append(
                        EntryTemplate(
                            name=f"riskbox_{cap_name}_smi_{smi}_session_{session}_score_{score}",
                            rsi_min=Decimal("42"),
                            rsi_max=Decimal("65"),
                            min_entry_score=score,
                            min_momentum=Decimal("0.15"),
                            min_recent_momentum=Decimal("0.08"),
                            min_long_momentum=Decimal("0.12"),
                            min_session_change=session,
                            min_vwap_distance=Decimal("0.05"),
                            max_vwap_distance=min(limits["max_vwap_extension"], Decimal("2.25")),
                            max_session_pullback=min(limits["max_session_pullback"], Decimal("0.75")),
                            max_recent_pullback=min(limits["max_recent_pullback"], Decimal("0.50")),
                            min_smi=smi,
                            min_relative_volume=Decimal("1.0"),
                            min_price=base_min_price,
                            max_relative_volume=max_relative_volume,
                            max_atr_percent=max_atr,
                            max_volatility_percent=max_volatility,
                        )
                    )
    return templates


def pricebox_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    base_min_price = limits["min_price"]
    templates: list[EntryTemplate] = []
    for score in (Decimal("30"), Decimal("35")):
        for smi in (Decimal("35"), Decimal("40"), Decimal("50")):
            for max_price in (Decimal("75"), Decimal("125"), Decimal("150"), Decimal("200"), Decimal("300")):
                templates.append(
                    EntryTemplate(
                        name=f"pricebox_max_{max_price}_smi_{smi}_score_{score}",
                        rsi_min=Decimal("42"),
                        rsi_max=Decimal("65"),
                        min_entry_score=score,
                        min_momentum=Decimal("0.15"),
                        min_recent_momentum=Decimal("0.08"),
                        min_long_momentum=Decimal("0.12"),
                        min_session_change=Decimal("0.05"),
                        min_vwap_distance=Decimal("0.05"),
                        max_vwap_distance=min(limits["max_vwap_extension"], Decimal("2.25")),
                        max_session_pullback=min(limits["max_session_pullback"], Decimal("0.75")),
                        max_recent_pullback=min(limits["max_recent_pullback"], Decimal("0.50")),
                        min_smi=smi,
                        min_relative_volume=Decimal("1.0"),
                        min_price=base_min_price,
                        max_price=max_price,
                    )
                )
    return templates


def pricebox_session_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    """Focused pricebox variants that require stronger same-session direction."""
    limits = profile_limits(config)
    base_min_price = limits["min_price"]
    templates: list[EntryTemplate] = []
    for score in (Decimal("30"), Decimal("35")):
        for smi in (Decimal("50"), Decimal("60")):
            for session in (Decimal("0.25"), Decimal("0.30"), Decimal("0.35"), Decimal("0.50")):
                for max_price in (Decimal("200"), Decimal("300")):
                    templates.append(
                        EntryTemplate(
                            name=f"pricebox_session_{session}_max_{max_price}_smi_{smi}_score_{score}",
                            rsi_min=Decimal("42"),
                            rsi_max=Decimal("65"),
                            min_entry_score=score,
                            min_momentum=Decimal("0.15"),
                            min_recent_momentum=Decimal("0.08"),
                            min_long_momentum=Decimal("0.12"),
                            min_session_change=session,
                            min_vwap_distance=Decimal("0.05"),
                            max_vwap_distance=min(limits["max_vwap_extension"], Decimal("2.25")),
                            max_session_pullback=min(limits["max_session_pullback"], Decimal("0.75")),
                            max_recent_pullback=min(limits["max_recent_pullback"], Decimal("0.50")),
                            min_smi=smi,
                            min_relative_volume=Decimal("1.0"),
                            min_price=base_min_price,
                            max_price=max_price,
                        )
                    )
    return templates


def conservative_bridge_entry_templates(config: dict[str, Any]) -> list[EntryTemplate]:
    limits = profile_limits(config)
    base_min_price = limits["min_price"]
    templates: list[EntryTemplate] = []
    for score in (Decimal("35"), Decimal("38"), Decimal("40")):
        for smi in (Decimal("15"), Decimal("20"), Decimal("30")):
            for session in (Decimal("0.35"), Decimal("0.50")):
                templates.append(
                    EntryTemplate(
                        name=f"conservative_bridge_smi_{smi}_session_{session}_score_{score}",
                        rsi_min=Decimal("50"),
                        rsi_max=Decimal("70"),
                        min_entry_score=score,
                        min_momentum=Decimal("0.15"),
                        min_recent_momentum=Decimal("0.05"),
                        min_long_momentum=Decimal("0.40"),
                        min_session_change=session,
                        min_vwap_distance=Decimal("0.05"),
                        max_vwap_distance=min(limits["max_vwap_extension"], Decimal("2.50")),
                        max_session_pullback=min(limits["max_session_pullback"], Decimal("1.00")),
                        max_recent_pullback=min(limits["max_recent_pullback"], Decimal("0.60")),
                        min_smi=smi,
                        min_relative_volume=Decimal("1.0"),
                        min_price=base_min_price,
                        max_price=ZERO,
                    )
                )
    return templates


def build_candidates(config: dict[str, Any], templates: list[EntryTemplate], exit_mode: str = "fixed") -> list[Candidate]:
    current_tp = config_decimal(config, "take_profit_percent", Decimal("3"))
    current_sl = config_decimal(config, "stop_loss_percent", Decimal("2"))
    fixed_exits = [
        (exit_name, "fixed", take_profit, stop_loss, ZERO, ZERO, ZERO)
        for exit_name, take_profit, stop_loss in DEFAULT_EXIT_PAIRS
    ]
    if current_tp > ZERO and current_sl > ZERO:
        fixed_exits.append(("current_exit", "fixed", current_tp, current_sl, ZERO, ZERO, ZERO))
    adaptive_exits = list(ADAPTIVE_EXIT_PLANS)
    if exit_mode == "adaptive":
        exits = adaptive_exits
    elif exit_mode == "all":
        exits = fixed_exits + adaptive_exits
    else:
        exits = fixed_exits
    reentry_boost = config_decimal(config, "reentry_score_boost", Decimal("10"))
    candidates: list[Candidate] = []
    for template in templates:
        for exit_name, exit_style, take_profit, stop_loss, activation, trail_distance, profit_lock in exits:
            candidates.append(
                Candidate(
                    name=f"{template.name}|{exit_name}",
                    entry=template,
                    take_profit_percent=take_profit,
                    stop_loss_percent=stop_loss,
                    reentry_score_boost=reentry_boost,
                    exit_style=exit_style,
                    trail_activation_percent=activation,
                    trail_distance_percent=trail_distance,
                    profit_lock_percent=profit_lock,
                )
            )
    return candidates


def candidates_for_mode(
    config: dict[str, Any],
    mode: str,
    research_events: list[Any] | None = None,
    exit_mode: str = "fixed",
) -> list[Candidate]:
    if mode == "broad":
        return build_candidates(config, broad_entry_templates(config), exit_mode)
    if mode == "riskbox":
        return build_candidates(config, riskbox_entry_templates(config), exit_mode)
    if mode == "pricebox":
        return build_candidates(config, pricebox_entry_templates(config), exit_mode)
    if mode == "pricebox_session":
        return build_candidates(config, pricebox_session_entry_templates(config), exit_mode)
    if mode == "conservative_bridge":
        return build_candidates(config, conservative_bridge_entry_templates(config), exit_mode)
    if mode == "impulse":
        return build_candidates(config, impulse_entry_templates(config), exit_mode)
    if mode == "research":
        return build_candidates(config, research_entry_templates(research_events or [], config), exit_mode)
    return build_candidates(config, entry_templates(config), exit_mode)


def order_qty(notional: Decimal, price: Decimal) -> Decimal:
    if notional <= ZERO or price <= ZERO:
        return ZERO
    return (notional / price).quantize(Decimal("0.0001"))


def planned_notional(config: dict[str, Any], equity: Decimal, cash: Decimal, exposure: Decimal) -> Decimal:
    sizing_positions = config_int(config, "simulation_sizing_positions", config_int(config, "max_open_positions", 1))
    max_positions = Decimal(sizing_positions)
    options: list[Decimal] = []
    max_trade = config_decimal(config, "max_trade_notional")
    max_trade_pct = config_decimal(config, "max_trade_percent")
    max_total_exposure_pct = config_decimal(config, "max_total_exposure_percent")
    if max_trade > ZERO:
        options.append(max_trade)
    if max_trade_pct > ZERO and equity > ZERO:
        options.append(equity * max_trade_pct / Decimal("100"))
    if max_total_exposure_pct > ZERO and max_positions > ZERO and equity > ZERO:
        exposure_budget = equity * max_total_exposure_pct / Decimal("100")
        options.append(exposure_budget / max_positions)
    positive = [item for item in options if item > ZERO]
    if not positive:
        return ZERO
    block = min(positive)
    if block < Decimal("1") or block > cash:
        return ZERO
    if max_total_exposure_pct > ZERO and equity > ZERO:
        room = equity * max_total_exposure_pct / Decimal("100") - exposure
        if block > room:
            return ZERO
    return block


def score_weight_map(entry: EntryTemplate) -> dict[str, Decimal]:
    return {str(key): Decimal(value) for key, value in entry.score_weights}


def weighted_score_features(row: dict[str, Any], entry: EntryTemplate) -> dict[str, Decimal]:
    rsi = parse_row_decimal(row, "rsi_raw", "rsi")
    momentum = parse_row_decimal(row, "momentum_raw", "momentum")
    recent_momentum = parse_row_decimal(row, "recent_momentum_raw", "recent_momentum")
    long_momentum = parse_row_decimal(row, "long_momentum_raw", "long_momentum")
    session_change = parse_row_decimal(row, "session_change_raw", "session_change")
    vwap_distance = parse_row_decimal(row, "vwap_distance_raw", "vwap_distance")
    session_pullback = parse_row_decimal(row, "session_pullback_raw", "session_pullback")
    recent_pullback = parse_row_decimal(row, "recent_pullback_raw", "recent_pullback")
    smi = parse_row_decimal(row, "smi_raw", "smi")
    relative_volume = parse_relative_volume(row)
    atr = parse_row_decimal(row, "atr_raw", "atr")
    volatility = parse_row_decimal(row, "volatility_raw", "volatility")
    flow_ratio = parse_buy_flow_ratio(row)

    rsi_range = max(entry.rsi_max - entry.rsi_min, Decimal("1"))
    ideal_rsi = entry.rsi_min + (rsi_range * Decimal("0.55"))
    rsi_half_range = max(rsi_range / Decimal("2"), Decimal("1"))
    rsi_fit = Decimal("1") - (abs(rsi - ideal_rsi) / rsi_half_range)
    smi_range = max(Decimal("80") - entry.min_smi, Decimal("1"))
    vwap_extension_range = max(entry.max_vwap_distance - Decimal("2"), Decimal("1"))
    session_pullback_limit = max(entry.max_session_pullback, Decimal("0.01"))
    recent_pullback_limit = max(entry.max_recent_pullback, Decimal("0.01"))
    return {
        "rsi_fit": clamp_unit(rsi_fit),
        "relative_volume": clamp_unit(relative_volume / Decimal("2.5")),
        "momentum": clamp_unit((momentum - entry.min_momentum) / Decimal("1.5")),
        "recent_momentum": clamp_unit((recent_momentum - entry.min_recent_momentum) / Decimal("1")),
        "long_momentum": clamp_unit(long_momentum / Decimal("4")),
        "session_change": clamp_unit(session_change / Decimal("5")),
        "vwap_distance": clamp_unit(vwap_distance / Decimal("1.5")),
        "smi": clamp_unit((smi - entry.min_smi) / smi_range),
        "volatility": clamp_unit(max(atr, volatility) / Decimal("2")),
        "volatility_penalty": clamp_unit(max(atr, volatility) / Decimal("2")),
        "buy_flow": clamp_unit(flow_ratio if flow_ratio is not None else Decimal("0.5")),
        "session_extension_penalty": clamp_unit((session_change - Decimal("4")) / Decimal("2")),
        "vwap_extension_penalty": clamp_unit((vwap_distance - Decimal("2")) / vwap_extension_range),
        "session_pullback_penalty": clamp_unit(session_pullback / session_pullback_limit),
        "recent_pullback_penalty": clamp_unit(recent_pullback / recent_pullback_limit),
        "smi_overheat_penalty": clamp_unit((smi - Decimal("85")) / Decimal("15")),
    }


def candidate_entry_score(row: dict[str, Any], candidate: Candidate) -> Decimal:
    entry = candidate.entry
    weights = score_weight_map(entry)
    if not weights:
        return parse_row_decimal(row, "entry_score_raw", "entry_score")
    features = weighted_score_features(row, entry)
    score = entry.score_bias
    for feature, weight in weights.items():
        value = features.get(feature, ZERO)
        if feature.endswith("_penalty"):
            score -= value * weight
        else:
            score += value * weight
    return max(ZERO, score).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def row_eligible(row: dict[str, Any], candidate: Candidate) -> tuple[bool, Decimal]:
    symbol = str(row.get("symbol") or "").strip().upper()
    if not symbol:
        return False, ZERO
    entry = candidate.entry
    price = parse_row_decimal(row, "price_raw", "price")
    rsi = parse_row_decimal(row, "rsi_raw", "rsi")
    score = candidate_entry_score(row, candidate)
    momentum = parse_row_decimal(row, "momentum_raw", "momentum")
    recent_momentum = parse_row_decimal(row, "recent_momentum_raw", "recent_momentum")
    long_momentum = parse_row_decimal(row, "long_momentum_raw", "long_momentum")
    session_change = parse_row_decimal(row, "session_change_raw", "session_change")
    vwap_distance = parse_row_decimal(row, "vwap_distance_raw", "vwap_distance")
    session_pullback = parse_row_decimal(row, "session_pullback_raw", "session_pullback")
    recent_pullback = parse_row_decimal(row, "recent_pullback_raw", "recent_pullback")
    smi = parse_row_decimal(row, "smi_raw", "smi")
    relative_volume = parse_relative_volume(row)
    atr = parse_row_decimal(row, "atr_raw", "atr")
    volatility = parse_row_decimal(row, "volatility_raw", "volatility")
    bias = str(row.get("bias") or "").strip()

    if price < entry.min_price:
        return False, score
    if entry.max_price > ZERO and price > entry.max_price:
        return False, score
    if bias != "Bullish":
        return False, score
    if rsi < entry.rsi_min or rsi > entry.rsi_max:
        return False, score
    if score < entry.min_entry_score:
        return False, score
    if momentum < entry.min_momentum:
        return False, score
    if recent_momentum < entry.min_recent_momentum:
        return False, score
    if long_momentum < entry.min_long_momentum:
        return False, score
    if session_change < entry.min_session_change:
        return False, score
    if vwap_distance < entry.min_vwap_distance or vwap_distance > entry.max_vwap_distance:
        return False, score
    if session_pullback > entry.max_session_pullback:
        return False, score
    if recent_pullback > entry.max_recent_pullback:
        return False, score
    if smi < entry.min_smi:
        return False, score
    if relative_volume < entry.min_relative_volume:
        return False, score
    if entry.max_relative_volume > ZERO and relative_volume > entry.max_relative_volume:
        return False, score
    if entry.max_atr_percent > ZERO and atr > entry.max_atr_percent:
        return False, score
    if entry.max_volatility_percent > ZERO and volatility > entry.max_volatility_percent:
        return False, score
    return True, score


def row_sort_key(row: dict[str, Any], candidate: Candidate) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    return (
        candidate_entry_score(row, candidate),
        parse_row_decimal(row, "session_change_raw", "session_change"),
        parse_row_decimal(row, "momentum_raw", "momentum"),
        parse_row_decimal(row, "vwap_distance_raw", "vwap_distance"),
    )


def load_tape(files: list[Path], price_source: str = "bars") -> tuple[list[Any], dict[str, BucketProfile]]:
    metadata = DayTapeSimulator([])
    events: list[Any] = []
    relevant_kinds = {"strategy_scan", "market_bar"}
    if price_source == "trades":
        relevant_kinds.update({"market_trade", "market_quote"})
    for _path, _line_number, event in iter_relevant_events(files, relevant_kinds):
        kind = str(event.get("kind") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_time = parse_time(event.get("time"))
        if kind == "market_bar":
            symbol = str(payload.get("symbol") or "").strip().upper()
            high = parse_decimal(payload.get("high"))
            low = parse_decimal(payload.get("low"))
            close = parse_decimal(payload.get("close"))
            if symbol and high > ZERO and low > ZERO and close > ZERO:
                events.append(PriceEvent(event_time, symbol, high, low, close))
        elif price_source == "trades" and kind in {"market_trade", "market_quote"}:
            symbol = str(payload.get("symbol") or "").strip().upper()
            if kind == "market_trade":
                value = parse_decimal(payload.get("price"))
            else:
                bid = parse_decimal(payload.get("bid_price"))
                ask = parse_decimal(payload.get("ask_price"))
                value = (bid + ask) / Decimal("2") if bid > ZERO and ask > ZERO else max(bid, ask)
            if symbol and value > ZERO:
                events.append(PriceEvent(event_time, symbol, value, value, value))
        elif kind == "strategy_scan":
            raw_key = bucket_key(payload)
            meta = metadata.metas.setdefault(raw_key, BucketMeta(key=raw_key))
            if not meta.first_payload:
                meta.first_payload = payload
                meta.first_time = event_time
                meta.source_keys = [raw_key]
            meta.latest_payload = payload
            meta.latest_time = event_time
            clock = payload.get("market_clock") if isinstance(payload.get("market_clock"), dict) else {}
            rows = payload.get("strategy") if isinstance(payload.get("strategy"), list) else []
            events.append(
                ScanEvent(
                    time=event_time,
                    bucket=raw_key,
                    market_open=bool(clock.get("is_open")),
                    trading_enabled=bool(payload.get("trading_enabled")),
                    entries_allowed=bool(payload.get("entries_allowed")),
                    rows=[row for row in rows if isinstance(row, dict)],
                )
            )
    metadata.stitch_config_handoffs()
    aliases = metadata.bucket_aliases or {key: key for key in metadata.metas}
    for event in events:
        if isinstance(event, ScanEvent):
            event.bucket = aliases.get(event.bucket, event.bucket)

    profiles: dict[str, BucketProfile] = {}
    for canonical_key, meta in metadata.metas.items():
        payload = meta.first_payload
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        starting_equity = parse_decimal(account.get("equity"))
        starting_cash = starting_equity
        profiles[canonical_key] = BucketProfile(
            key=canonical_key,
            label=meta.key,
            config=config,
            starting_equity=starting_equity,
            starting_cash=starting_cash,
            source_keys=meta.source_keys or [canonical_key],
        )
    return events, profiles


def compact_scan_events(events: list[Any], interval_seconds: int) -> tuple[list[Any], int]:
    if interval_seconds <= 0:
        return events, 0
    compacted: list[Any] = []
    seen_scan_slots: set[tuple[str, int]] = set()
    dropped = 0
    for event in events:
        if not isinstance(event, ScanEvent) or event.time is None:
            compacted.append(event)
            continue
        slot = int(event.time.timestamp()) // interval_seconds
        key = (event.bucket, slot)
        if key in seen_scan_slots:
            dropped += 1
            continue
        seen_scan_slots.add(key)
        compacted.append(event)
    return compacted, dropped


def simulate_candidate(
    events: list[Any],
    profile: BucketProfile,
    candidate: Candidate,
    slippage_bps: Decimal,
    liquidate_at_end: bool,
    max_hold_minutes: int,
    liquidate_on_close: bool,
    collect_trades: bool = False,
    min_stop_hold_minutes: int = 0,
    entry_open_guard_minutes: int = 0,
) -> SweepMetrics:
    state = SweepState(
        profile=profile,
        candidate=candidate,
        cash=profile.starting_cash,
        min_stop_hold_minutes=max(0, min_stop_hold_minutes),
        collect_trades=collect_trades,
    )
    config = profile.config
    max_positions = config_int(config, "simulation_max_open_positions", config_int(config, "max_open_positions", 1))
    session_open_time: Any = None
    previous_scan_open = False

    for event in events:
        if isinstance(event, PriceEvent):
            price = event.close
            if slippage_bps > ZERO:
                price = max(ZERO, price - price * slippage_bps / BPS)
            state.update_price(event.symbol, price)
            state.maybe_exit(event.symbol, event.high, event.low, price, event.time)
            state.maybe_time_exit(event.symbol, event.time, price, max_hold_minutes)
            state.record_equity()
            continue

        if not isinstance(event, ScanEvent) or event.bucket != profile.key:
            continue
        if event.market_open and (not previous_scan_open or session_open_time is None):
            session_open_time = event.time
        if not event.market_open:
            previous_scan_open = False
            session_open_time = None
        else:
            previous_scan_open = True
        if liquidate_on_close and not event.market_open:
            state.liquidate_all(slippage_bps, event.time)
            state.record_equity()
            continue
        if not event.market_open or not event.trading_enabled or not event.entries_allowed:
            continue
        if entry_open_guard_minutes > 0 and session_open_time is not None and event.time is not None:
            seconds_since_open = (event.time - session_open_time).total_seconds()
            if seconds_since_open < entry_open_guard_minutes * 60:
                continue

        slots = max_positions - len(state.positions)
        if slots <= 0:
            continue
        eligible: list[tuple[dict[str, Any], Decimal]] = []
        for row in event.rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or symbol in state.positions:
                continue
            eligible_ok, score = row_eligible(row, candidate)
            if not eligible_ok:
                continue
            reentry_floor = state.reentry_floors.get(symbol)
            if reentry_floor is not None and score < reentry_floor:
                state.skipped_reentry += 1
                continue
            eligible.append((row, score))

        eligible.sort(key=lambda item: row_sort_key(item[0], candidate), reverse=True)
        for row, score in eligible[:slots]:
            symbol = str(row.get("symbol") or "").strip().upper()
            row_price = parse_row_decimal(row, "price_raw", "price")
            price = state.last_prices.get(symbol, row_price)
            if price <= ZERO:
                continue
            notional = planned_notional(config, state.equity(), state.cash, state.exposure())
            qty = order_qty(notional, price)
            if qty <= ZERO:
                state.skipped_budget += 1
                break
            fill_price = price
            if slippage_bps > ZERO:
                fill_price = price + price * slippage_bps / BPS
            state.fill_entry(symbol, qty, fill_price, score, event.time, row)
            if len(state.positions) >= max_positions:
                break

    if liquidate_at_end:
        state.liquidate_all(slippage_bps)
    return state.metrics()


def events_for_bucket(events: list[Any], bucket: str) -> list[Any]:
    return [
        event
        for event in events
        if isinstance(event, PriceEvent) or (isinstance(event, ScanEvent) and event.bucket == bucket)
    ]


def matching_fold_profile(
    profiles: dict[str, BucketProfile],
    bucket_keys: set[str],
) -> tuple[str, BucketProfile] | tuple[None, None]:
    for key in bucket_keys:
        profile = profiles.get(key)
        if profile is not None:
            return key, profile
    for key, profile in profiles.items():
        if key in bucket_keys or any(source_key in bucket_keys for source_key in profile.source_keys):
            return key, profile
    return None, None


def stable_candidate(train: SweepMetrics | None, validation: SweepMetrics, min_trades: int) -> bool:
    if train is None:
        return False
    if validation.buys < min_trades:
        return False
    if validation.open_positions > 0:
        return False
    if validation.pnl <= ZERO:
        return False
    if validation.profit_factor is None or validation.profit_factor < Decimal("1.2"):
        return False
    if validation.drawdown_percent > Decimal("3.0"):
        return False
    if train.buys < min_trades:
        return False
    if train.open_positions > 0:
        return False
    if train.pnl <= ZERO:
        return False
    if train.profit_factor is None or train.profit_factor < Decimal("1.1"):
        return False
    return True


def result_sort_key(item: tuple[SweepMetrics | None, SweepMetrics], min_trades: int) -> tuple[Any, ...]:
    train, validation = item
    pf = validation.profit_factor or ZERO
    train_pnl = train.pnl if train is not None else ZERO
    return (
        stable_candidate(train, validation, min_trades),
        validation.pnl,
        pf,
        -validation.max_drawdown,
        train_pnl,
        validation.buys,
    )


def metric_line(metrics: SweepMetrics) -> str:
    pf = metrics.profit_factor
    pf_text = f"{pf:.2f}" if pf is not None and pf < Decimal("90") else ("inf" if pf else "n/a")
    return (
        f"pnl={money(metrics.pnl)} ({percent(metrics.pnl_percent)}), "
        f"realized={money(metrics.realized_pl)}, unrealized={money(metrics.unrealized_pl)}, "
        f"buys={metrics.buys}, exits={metrics.exits}, win={percent(metrics.win_rate)}, "
        f"pf={pf_text}, exp={money(metrics.expectancy)}, "
        f"dd={money(metrics.max_drawdown)} ({percent(metrics.drawdown_percent)}), "
        f"open={metrics.open_positions}, exposure={money(metrics.exposure)}"
    )


def decimal_payload(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.0001")), "f")


def time_payload(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def profit_factor_text(metrics: SweepMetrics) -> str | None:
    pf = metrics.profit_factor
    if pf is None:
        return None
    if pf >= Decimal("90"):
        return "inf"
    return decimal_payload(pf)


def candidate_payload(candidate: Candidate) -> dict[str, Any]:
    entry = candidate.entry
    return {
        "name": candidate.name,
        "exit_style": candidate.exit_style,
        "entry": {
            "name": entry.name,
            "rsi_min": decimal_payload(entry.rsi_min),
            "rsi_max": decimal_payload(entry.rsi_max),
            "min_entry_score": decimal_payload(entry.min_entry_score),
            "min_momentum": decimal_payload(entry.min_momentum),
            "min_recent_momentum": decimal_payload(entry.min_recent_momentum),
            "min_long_momentum": decimal_payload(entry.min_long_momentum),
            "min_session_change": decimal_payload(entry.min_session_change),
            "min_vwap_distance": decimal_payload(entry.min_vwap_distance),
            "max_vwap_distance": decimal_payload(entry.max_vwap_distance),
            "max_session_pullback": decimal_payload(entry.max_session_pullback),
            "max_recent_pullback": decimal_payload(entry.max_recent_pullback),
            "min_smi": decimal_payload(entry.min_smi),
            "min_relative_volume": decimal_payload(entry.min_relative_volume),
            "min_price": decimal_payload(entry.min_price),
            "max_price": decimal_payload(entry.max_price),
            "max_relative_volume": decimal_payload(entry.max_relative_volume),
            "max_atr_percent": decimal_payload(entry.max_atr_percent),
            "max_volatility_percent": decimal_payload(entry.max_volatility_percent),
            "score_weights": {key: decimal_payload(value) for key, value in entry.score_weights},
            "score_bias": decimal_payload(entry.score_bias),
        },
        "take_profit_percent": decimal_payload(candidate.take_profit_percent),
        "stop_loss_percent": decimal_payload(candidate.stop_loss_percent),
        "reentry_score_boost": decimal_payload(candidate.reentry_score_boost),
        "trail_activation_percent": decimal_payload(candidate.trail_activation_percent),
        "trail_distance_percent": decimal_payload(candidate.trail_distance_percent),
        "profit_lock_percent": decimal_payload(candidate.profit_lock_percent),
    }


def metrics_payload(metrics: SweepMetrics) -> dict[str, Any]:
    payload = {
        "bucket": metrics.bucket,
        "label": metrics.label,
        "starting_equity": decimal_payload(metrics.starting_equity),
        "ending_equity": decimal_payload(metrics.ending_equity),
        "cash": decimal_payload(metrics.cash),
        "pnl": decimal_payload(metrics.pnl),
        "pnl_percent": decimal_payload(metrics.pnl_percent),
        "realized_pl": decimal_payload(metrics.realized_pl),
        "unrealized_pl": decimal_payload(metrics.unrealized_pl),
        "max_drawdown": decimal_payload(metrics.max_drawdown),
        "drawdown_percent": decimal_payload(metrics.drawdown_percent),
        "peak_equity": decimal_payload(metrics.peak_equity),
        "buys": metrics.buys,
        "exits": metrics.exits,
        "wins": metrics.wins,
        "losses": metrics.losses,
        "flats": metrics.flats,
        "win_rate": decimal_payload(metrics.win_rate),
        "expectancy": decimal_payload(metrics.expectancy),
        "profit_factor": profit_factor_text(metrics),
        "open_positions": metrics.open_positions,
        "exposure": decimal_payload(metrics.exposure),
        "gross_profit": decimal_payload(metrics.gross_profit),
        "gross_loss": decimal_payload(metrics.gross_loss),
        "skipped_budget": metrics.skipped_budget,
        "skipped_reentry": metrics.skipped_reentry,
    }
    if metrics.trades:
        payload["trades"] = metrics.trades
    return payload


def simulate_file_folds(
    files: list[Path],
    bucket_keys: set[str],
    candidates: list[Candidate],
    slippage_bps: Decimal,
    price_source: str,
    scan_interval_seconds: int,
    liquidate_at_end: bool,
    max_hold_minutes: int,
    liquidate_on_close: bool,
    simulation_max_positions: int = 0,
    simulation_sizing_positions: int = 0,
    simulation_inverse_etf_mode: str = "",
) -> dict[str, list[dict[str, Any]]]:
    folds: dict[str, list[dict[str, Any]]] = {candidate.name: [] for candidate in candidates}
    for path in files:
        fold_events, fold_profiles = load_tape([path], price_source=price_source)
        fold_events, dropped_scans = compact_scan_events(fold_events, scan_interval_seconds)
        matched_bucket, profile = matching_fold_profile(fold_profiles, bucket_keys)
        if profile is None:
            for candidate in candidates:
                folds[candidate.name].append(
                    {
                        "file": path.name,
                        "status": "bucket_not_found",
                        "dropped_scans": dropped_scans,
                    }
                )
            continue
        bucket_events = events_for_bucket(fold_events, matched_bucket or "")
        simulation_profile = profile_with_simulation_overrides(
            profile,
            simulation_max_positions=simulation_max_positions,
            simulation_sizing_positions=simulation_sizing_positions,
            inverse_etf_mode=simulation_inverse_etf_mode,
        )
        for candidate in candidates:
            metrics = simulate_candidate(
                bucket_events,
                simulation_profile,
                candidate,
                slippage_bps,
                liquidate_at_end,
                max_hold_minutes,
                liquidate_on_close,
            )
            folds[candidate.name].append(
                {
                    "file": path.name,
                    "status": "ok",
                    "matched_bucket": matched_bucket,
                    "matched_label": profile.label,
                    "dropped_scans": dropped_scans,
                    "metrics": metrics_payload(metrics),
                    "line": metric_line(metrics),
                }
            )
    return folds


def run_sweep(
    files: list[Path],
    validation_days: int,
    top: int,
    min_trades: int,
    slippage_bps: Decimal,
    price_source: str,
    scan_interval_seconds: int,
    candidate_mode: str,
    exit_mode: str,
    bucket_contains: str,
    candidate_contains: str,
    liquidate_at_end: bool,
    max_hold_minutes: int,
    liquidate_on_close: bool,
    fold_report_top: int,
    json_output: Path | None,
    simulation_max_positions: int = 20,
    simulation_sizing_positions: int = 20,
    simulation_inverse_etf_mode: str = "",
) -> int:
    if not files:
        print("No day-tape files found.")
        return 0
    validation_count = min(max(1, validation_days), len(files))
    train_files = files[:-validation_count]
    validation_files = files[-validation_count:]

    start = time.perf_counter()
    validation_events, validation_profiles = load_tape(validation_files, price_source=price_source)
    train_events: list[Any] = []
    train_profiles: dict[str, BucketProfile] = {}
    if train_files:
        train_events, train_profiles = load_tape(train_files, price_source=price_source)
    validation_events, dropped_validation_scans = compact_scan_events(validation_events, scan_interval_seconds)
    train_events, dropped_train_scans = compact_scan_events(train_events, scan_interval_seconds)
    load_seconds = time.perf_counter() - start

    print("Day Tape Strategy Sweep")
    print(f"Train files: {', '.join(path.name for path in train_files) or 'none'}")
    print(f"Validation files: {', '.join(path.name for path in validation_files)}")
    print(f"Load time: {load_seconds:.2f}s")
    print()
    print("Method")
    print("  Flat-start accounts use each bucket's first tape equity as cash.")
    print("  Entries are recomputed from recorded strategy rows, not from submitted order intents.")
    print("  Sizing is read from tape config; entry/exit gates are swept offline only.")
    print(f"  Price source: {price_source}; bar mode uses high/low/close and assumes stop-before-target if both touch.")
    print(
        "  Scan interval: "
        f"{scan_interval_seconds}s; dropped repeated scans train={dropped_train_scans:,}, "
        f"validation={dropped_validation_scans:,}."
    )
    print(f"  Candidate mode: {candidate_mode}.")
    print(f"  Exit mode: {exit_mode}.")
    print(f"  Liquidate at fold end for scoring: {liquidate_at_end}.")
    print(f"  Liquidate on market close: {liquidate_on_close}.")
    print(f"  Max hold minutes: {max_hold_minutes or 'disabled'}.")
    print(
        "  Simulation capacity/sizing: "
        f"max positions={simulation_max_positions or 'profile'}, "
        f"sizing positions={simulation_sizing_positions or 'profile'}."
    )
    if simulation_inverse_etf_mode:
        print(f"  Simulation inverse ETF mode override: {simulation_inverse_etf_mode}.")
    if bucket_contains:
        print(f"  Bucket filter: {bucket_contains}.")
    if candidate_contains:
        print(f"  Candidate filter: {candidate_contains}.")
    print("  Stable labels require train/validation profits, enough trades, acceptable PF/DD, and no open positions.")
    print("  Ranking favors positive validation P&L, profit factor, low drawdown, and train consistency.")
    print()

    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": [path.name for path in files],
        "train_files": [path.name for path in train_files],
        "validation_files": [path.name for path in validation_files],
        "settings": {
            "validation_days": validation_count,
            "top": top,
            "min_trades": min_trades,
            "slippage_bps": decimal_payload(slippage_bps),
            "price_source": price_source,
            "scan_interval_seconds": scan_interval_seconds,
            "candidate_mode": candidate_mode,
            "exit_mode": exit_mode,
            "bucket_contains": bucket_contains,
            "candidate_contains": candidate_contains,
            "liquidate_at_end": liquidate_at_end,
            "liquidate_on_close": liquidate_on_close,
            "max_hold_minutes": max_hold_minutes,
            "fold_report_top": fold_report_top,
            "simulation_max_positions": simulation_max_positions,
            "simulation_sizing_positions": simulation_sizing_positions,
            "simulation_inverse_etf_mode": simulation_inverse_etf_mode,
        },
        "load": {
            "seconds": round(load_seconds, 4),
            "dropped_train_scans": dropped_train_scans,
            "dropped_validation_scans": dropped_validation_scans,
        },
        "buckets": [],
    }

    for bucket in sorted(validation_profiles):
        validation_profile = profile_with_simulation_overrides(
            validation_profiles[bucket],
            simulation_max_positions=simulation_max_positions,
            simulation_sizing_positions=simulation_sizing_positions,
            inverse_etf_mode=simulation_inverse_etf_mode,
        )
        if bucket_contains and bucket_contains.lower() not in validation_profile.label.lower():
            continue
        train_bucket_keys = {bucket, *validation_profile.source_keys}
        train_bucket, raw_train_profile = matching_fold_profile(train_profiles, train_bucket_keys)
        train_bucket = train_bucket or bucket
        train_profile = (
            profile_with_simulation_overrides(
                raw_train_profile,
                simulation_max_positions=simulation_max_positions,
                simulation_sizing_positions=simulation_sizing_positions,
                inverse_etf_mode=simulation_inverse_etf_mode,
            )
            if raw_train_profile is not None
            else None
        )
        validation_bucket_events = events_for_bucket(validation_events, bucket)
        train_bucket_events = events_for_bucket(train_events, train_bucket)
        research_events = train_bucket_events if train_bucket_events else validation_bucket_events
        candidates = candidates_for_mode(validation_profile.config, candidate_mode, research_events, exit_mode)
        if candidate_contains:
            candidates = [
                candidate
                for candidate in candidates
                if candidate_contains.lower() in candidate.name.lower()
            ]
        results: list[tuple[SweepMetrics | None, SweepMetrics]] = []
        for candidate in candidates:
            train_metrics = (
                simulate_candidate(
                    train_bucket_events,
                    train_profile,
                    candidate,
                    slippage_bps,
                    liquidate_at_end,
                    max_hold_minutes,
                    liquidate_on_close,
                )
                if train_profile is not None
                else None
            )
            validation_metrics = simulate_candidate(
                validation_bucket_events,
                validation_profile,
                candidate,
                slippage_bps,
                liquidate_at_end,
                max_hold_minutes,
                liquidate_on_close,
                simulation_max_positions=simulation_max_positions,
                simulation_sizing_positions=simulation_sizing_positions,
                simulation_inverse_etf_mode=simulation_inverse_etf_mode,
            )
            results.append((train_metrics, validation_metrics))
        results.sort(key=lambda item: result_sort_key(item, min_trades), reverse=True)
        stable_count = sum(1 for train, validation in results if stable_candidate(train, validation, min_trades))
        top_results = results[:top]
        fold_reports: dict[str, list[dict[str, Any]]] = {}
        if fold_report_top > 0:
            fold_candidates = [validation.candidate for _train, validation in top_results[:fold_report_top]]
            fold_bucket_keys = {bucket, *validation_profile.source_keys}
            if train_profile is not None:
                fold_bucket_keys.update(train_profile.source_keys)
            fold_reports = simulate_file_folds(
                files,
                fold_bucket_keys,
                fold_candidates,
                slippage_bps,
                price_source,
                scan_interval_seconds,
                liquidate_at_end,
                max_hold_minutes,
                liquidate_on_close,
            )

        bucket_report = {
            "bucket": bucket,
            "label": validation_profile.label,
            "candidate_count": len(results),
            "stable_candidate_count": stable_count,
            "top": [],
        }
        print(f"Bucket: {validation_profile.label}")
        print(f"  candidates={len(results)} stable_candidates={stable_count}")
        for rank, (train_metrics, validation_metrics) in enumerate(top_results, start=1):
            is_stable = stable_candidate(train_metrics, validation_metrics, min_trades)
            marker = "stable" if is_stable else "provisional"
            candidate = validation_metrics.candidate
            print(f"  #{rank} {marker} {candidate.name}")
            if train_metrics is not None:
                print(f"     train:      {metric_line(train_metrics)}")
            print(f"     validation: {metric_line(validation_metrics)}")
            print(
                "     params: "
                f"rsi={candidate.entry.rsi_min}-{candidate.entry.rsi_max}, "
                f"score>={candidate.entry.min_entry_score}, "
                f"mom>={candidate.entry.min_momentum}, recent>={candidate.entry.min_recent_momentum}, "
                f"long>={candidate.entry.min_long_momentum}, session>={candidate.entry.min_session_change}, "
                f"vwap={candidate.entry.min_vwap_distance}..{candidate.entry.max_vwap_distance}, "
                f"pullback<={candidate.entry.max_session_pullback}/{candidate.entry.max_recent_pullback}, "
                f"rv>={candidate.entry.min_relative_volume}, "
                f"tp/sl={candidate.take_profit_percent}/{candidate.stop_loss_percent}, "
                f"exit={candidate.exit_style}, "
                f"trail={candidate.trail_activation_percent}/{candidate.trail_distance_percent}, "
                f"lock={candidate.profit_lock_percent}"
            )
            candidate_folds = fold_reports.get(candidate.name, [])
            for fold in candidate_folds:
                if fold.get("status") == "ok":
                    print(f"     fold {fold['file']}: {fold['line']}")
                else:
                    print(f"     fold {fold['file']}: {fold['status']}")
            bucket_report["top"].append(
                {
                    "rank": rank,
                    "label": marker,
                    "stable": is_stable,
                    "candidate": candidate_payload(candidate),
                    "train": metrics_payload(train_metrics) if train_metrics is not None else None,
                    "validation": metrics_payload(validation_metrics),
                    "folds": candidate_folds,
                }
            )
        print()
        report["buckets"].append(bucket_report)

    elapsed = time.perf_counter() - start
    print(f"Elapsed: {elapsed:.2f}s")
    report["elapsed_seconds"] = round(elapsed, 4)
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report: {json_output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep day-tape strategy rows through offline entry/exit candidates.")
    parser.add_argument("--path", type=Path, default=default_tape_dir(), help="Tape directory or one tape file.")
    parser.add_argument("--days", type=int, default=3, help="Most-recent tape files to use.")
    parser.add_argument(
        "--end-date",
        default="",
        help="When --path is a directory, only use tape files up through this YYYYMMDD date.",
    )
    parser.add_argument(
        "--validation-date",
        default="",
        help="Hold out this selected YYYYMMDD tape file as validation and train on the other selected days.",
    )
    parser.add_argument("--validation-days", type=int, default=1, help="Most recent files reserved for validation.")
    parser.add_argument("--top", type=int, default=5, help="Top candidates to print per bucket.")
    parser.add_argument("--min-trades", type=int, default=3, help="Minimum validation buys for stable-candidate label.")
    parser.add_argument(
        "--price-source",
        choices=("bars", "trades"),
        default="bars",
        help="Use minute bars for speed or every trade print for finer but slower fills.",
    )
    parser.add_argument(
        "--scan-interval-seconds",
        type=int,
        default=60,
        help="Evaluate at most one strategy scan per bucket per interval. Default 60 aligns with minute bars.",
    )
    parser.add_argument(
        "--candidate-mode",
        choices=("standard", "broad", "research", "impulse", "riskbox", "pricebox", "pricebox_session", "conservative_bridge"),
        default="standard",
        help="standard uses curated templates; broad expands score bands; research derives thresholds from train folds; impulse tests high-session/high-SMI filters; riskbox tests moderate SMI/session filters mined from diagnostics; conservative_bridge tests lower-score conservative top-row ranges. pricebox modes are explicit price-cap diagnostics only, not stock-selection strategy candidates.",
    )
    parser.add_argument(
        "--exit-mode",
        choices=("fixed", "adaptive", "all"),
        default="fixed",
        help="fixed tests stop/target exits; adaptive tests trailing/profit-lock exits; all tests both.",
    )
    parser.add_argument(
        "--bucket-contains",
        default="",
        help="Only sweep buckets whose printed label contains this case-insensitive text.",
    )
    parser.add_argument(
        "--candidate-contains",
        default="",
        help="Only simulate candidates whose name contains this case-insensitive text.",
    )
    parser.add_argument(
        "--no-liquidate-at-end",
        action="store_true",
        help="Leave fold-end positions open. Default liquidates at the final tape price for complete fold scoring.",
    )
    parser.add_argument(
        "--liquidate-on-close",
        action="store_true",
        help="Offline-only session exit. Close open positions when that bucket's tape clock first reports market closed.",
    )
    parser.add_argument(
        "--max-hold-minutes",
        type=int,
        default=0,
        help="Offline-only time exit. Positions older than this many minutes exit at the next bar close. Default 0 disables it.",
    )
    parser.add_argument(
        "--slippage-bps",
        type=Decimal,
        default=Decimal("1"),
        help="Per-fill slippage in basis points. Default 1 bps adds a small adverse-cost check.",
    )
    parser.add_argument(
        "--fold-report-top",
        type=int,
        default=0,
        help="Print per-tape-file fold metrics for the top N candidates. Default 0 skips extra file passes.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write the full sweep report, top candidates, and optional folds to this JSON file.",
    )
    parser.add_argument(
        "--simulation-max-positions",
        type=int,
        default=20,
        help="Offline-only position capacity. Default 20 keeps candidate count fixed across strategy tests.",
    )
    parser.add_argument(
        "--simulation-sizing-positions",
        type=int,
        default=20,
        help="Offline-only sizing divisor for exposure-budget sizing. Default 20 keeps trade size fixed across tests.",
    )
    parser.add_argument(
        "--simulation-inverse-etf-mode",
        choices=("", "exclude", "allow", "inverse_only"),
        default="",
        help="Offline-only inverse ETF mode override. Empty keeps each tape profile value.",
    )
    args = parser.parse_args()
    files = selected_sweep_files(args.path, args.days, str(args.end_date or ""))
    validation_days = max(1, args.validation_days)
    if args.validation_date:
        files = move_validation_date_to_end(files, str(args.validation_date))
        validation_days = 1
    return run_sweep(
        files,
        validation_days=validation_days,
        top=max(1, args.top),
        min_trades=max(1, args.min_trades),
        slippage_bps=max(ZERO, args.slippage_bps),
        price_source=args.price_source,
        scan_interval_seconds=max(0, args.scan_interval_seconds),
        candidate_mode=args.candidate_mode,
        exit_mode=args.exit_mode,
        bucket_contains=str(args.bucket_contains or ""),
        candidate_contains=str(args.candidate_contains or ""),
        liquidate_at_end=not args.no_liquidate_at_end,
        max_hold_minutes=max(0, args.max_hold_minutes),
        liquidate_on_close=bool(args.liquidate_on_close),
        fold_report_top=max(0, args.fold_report_top),
        json_output=args.json_output,
        simulation_max_positions=max(1, args.simulation_max_positions),
        simulation_sizing_positions=max(1, args.simulation_sizing_positions),
        simulation_inverse_etf_mode=str(args.simulation_inverse_etf_mode or ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
