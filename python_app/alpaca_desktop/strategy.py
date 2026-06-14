from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any


def decimal_value(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def money(value: Any) -> str:
    amount = decimal_value(value)
    return f"${amount:,.2f}"


def number(value: Any, places: int = 4) -> str:
    amount = decimal_value(value)
    quant = Decimal("1").scaleb(-places)
    return str(amount.quantize(quant).normalize())


def clean_symbols(symbols: str | list[str]) -> list[str]:
    if isinstance(symbols, str):
        raw = symbols.split(",")
    else:
        raw = symbols
    cleaned: list[str] = []
    for item in raw:
        symbol = str(item).strip().upper()
        if symbol and all(ch.isalnum() or ch in ".-" for ch in symbol) and symbol not in cleaned:
            cleaned.append(symbol)
    return cleaned


@dataclass
class BarPoint:
    timestamp: str
    close: Decimal
    volume: Decimal
    high: Decimal
    low: Decimal


@dataclass
class StrategySnapshot:
    symbol: str
    price: Decimal | None
    short_sma: Decimal | None
    long_sma: Decimal | None
    rsi: Decimal | None
    volume: Decimal | None
    avg_volume: Decimal | None
    relative_volume: Decimal | None
    volatility_percent: Decimal | None
    momentum_percent: Decimal | None
    recent_momentum_percent: Decimal | None
    long_momentum_percent: Decimal | None
    session_change_percent: Decimal | None
    session_pullback_percent: Decimal | None
    recent_pullback_percent: Decimal | None
    vwap: Decimal | None
    vwap_distance_percent: Decimal | None
    smi: Decimal | None
    atr_percent: Decimal | None
    volume_ok: bool
    bias: str
    bars: int
    last_action: str = ""
    entry_score: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": money(self.price) if self.price is not None else "-",
            "short_sma": money(self.short_sma) if self.short_sma is not None else "-",
            "long_sma": money(self.long_sma) if self.long_sma is not None else "-",
            "rsi": _format_decimal(self.rsi, 1),
            "volume": _format_volume(self.volume),
            "avg_volume": _format_volume(self.avg_volume),
            "relative_volume": f"{self.relative_volume:.2f}x" if self.relative_volume is not None else "-",
            "volatility": f"{self.volatility_percent:.2f}%" if self.volatility_percent is not None else "-",
            "volatility_raw": float(self.volatility_percent) if self.volatility_percent is not None else 0,
            "momentum": f"{self.momentum_percent:+.2f}%" if self.momentum_percent is not None else "-",
            "momentum_raw": float(self.momentum_percent) if self.momentum_percent is not None else 0,
            "recent_momentum": f"{self.recent_momentum_percent:+.2f}%" if self.recent_momentum_percent is not None else "-",
            "recent_momentum_raw": float(self.recent_momentum_percent) if self.recent_momentum_percent is not None else 0,
            "long_momentum": f"{self.long_momentum_percent:+.2f}%" if self.long_momentum_percent is not None else "-",
            "long_momentum_raw": float(self.long_momentum_percent) if self.long_momentum_percent is not None else 0,
            "session_change": f"{self.session_change_percent:+.2f}%" if self.session_change_percent is not None else "-",
            "session_change_raw": float(self.session_change_percent) if self.session_change_percent is not None else 0,
            "session_pullback": f"{self.session_pullback_percent:.2f}%" if self.session_pullback_percent is not None else "-",
            "session_pullback_raw": float(self.session_pullback_percent) if self.session_pullback_percent is not None else 0,
            "recent_pullback": f"{self.recent_pullback_percent:.2f}%" if self.recent_pullback_percent is not None else "-",
            "recent_pullback_raw": float(self.recent_pullback_percent) if self.recent_pullback_percent is not None else 0,
            "vwap": money(self.vwap) if self.vwap is not None else "-",
            "vwap_distance": f"{self.vwap_distance_percent:+.2f}%" if self.vwap_distance_percent is not None else "-",
            "vwap_distance_raw": float(self.vwap_distance_percent) if self.vwap_distance_percent is not None else 0,
            "smi": _format_decimal(self.smi, 1),
            "smi_raw": float(self.smi) if self.smi is not None else 0,
            "atr": f"{self.atr_percent:.2f}%" if self.atr_percent is not None else "-",
            "atr_raw": float(self.atr_percent) if self.atr_percent is not None else 0,
            "volume_ok": "Yes" if self.volume_ok else "No",
            "bias": self.bias,
            "bars": self.bars,
            "entry_score": _format_decimal(self.entry_score, 1),
            "entry_score_raw": float(self.entry_score) if self.entry_score is not None else 0,
            "last_action": self.last_action,
        }


@dataclass
class StrategyState:
    histories: dict[str, list[BarPoint]] = field(default_factory=lambda: defaultdict(list))
    last_trade_at: dict[str, datetime] = field(default_factory=dict)
    last_action: dict[str, str] = field(default_factory=dict)
    entry_score: dict[str, Decimal] = field(default_factory=dict)

    def add_bar(
        self,
        symbol: str,
        close: Any,
        timestamp: Any = None,
        volume: Any = 0,
        high: Any = None,
        low: Any = None,
        max_bars: int = 500,
    ) -> None:
        clean = symbol.strip().upper()
        price = decimal_value(close)
        if not clean or price <= 0:
            return

        bar_volume = decimal_value(volume)
        bar_high = decimal_value(high, price)
        bar_low = decimal_value(low, price)
        if bar_high <= 0:
            bar_high = price
        if bar_low <= 0:
            bar_low = price
        if bar_low > bar_high:
            bar_low, bar_high = bar_high, bar_low
        when = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or datetime.now(timezone.utc).isoformat())
        history = self.histories[clean]
        if history and history[-1].timestamp == when:
            history[-1] = BarPoint(when, price, bar_volume, bar_high, bar_low)
        else:
            history.append(BarPoint(when, price, bar_volume, bar_high, bar_low))

        if len(history) > max_bars:
            del history[: len(history) - max_bars]

    def snapshot(
        self,
        symbol: str,
        short_period: int,
        long_period: int,
        rsi_period: int = 14,
        volume_period: int = 20,
        volume_multiplier: Decimal = Decimal("1"),
        min_avg_volume: Decimal = Decimal("0"),
        momentum_period: int = 6,
        smi_period: int = 10,
        atr_period: int = 14,
    ) -> StrategySnapshot:
        clean = symbol.strip().upper()
        history = self.histories.get(clean, [])
        closes = [point.close for point in history]
        volumes = [point.volume for point in history]
        highs = [point.high for point in history]
        lows = [point.low for point in history]
        price = closes[-1] if closes else None
        session_points = _latest_session_points(history)
        session_closes = [point.close for point in session_points]
        short_sma = _sma(closes, short_period)
        long_sma = _sma(closes, long_period)
        rsi = _rsi(closes, rsi_period)
        volatility_percent = _average_abs_percent_change(closes, rsi_period)
        momentum_percent = _percent_change_over(closes, momentum_period)
        recent_momentum_percent = _percent_change_over(closes, 3)
        long_momentum_period = max(30, long_period * 3, momentum_period * 5)
        long_momentum_percent = _percent_change_over(session_closes, long_momentum_period)
        smi = _smi(closes, highs, lows, smi_period)
        atr_percent = _atr_percent(highs, lows, closes, atr_period)
        session_change_percent = None
        if price is not None and session_closes:
            session_change_percent = _percent_change(price, session_closes[0])
        session_high = max((point.high for point in session_points), default=None)
        session_pullback_percent = _pullback_from_high_percent(price, session_high)
        recent_points = history[-5:]
        recent_high = max((point.high for point in recent_points), default=None)
        recent_pullback_percent = _pullback_from_high_percent(price, recent_high)
        if long_momentum_percent is None:
            long_momentum_percent = session_change_percent
        vwap = _vwap(session_points)
        vwap_distance_percent = _percent_change(price, vwap) if price is not None and vwap is not None else None
        current_volume = volumes[-1] if volumes else None
        avg_volume = _previous_average(volumes, volume_period)
        relative_volume = None
        volume_ok = False
        if current_volume is not None and avg_volume is not None and avg_volume > 0:
            relative_volume = current_volume / avg_volume
            volume_ok = avg_volume >= min_avg_volume and current_volume >= avg_volume * volume_multiplier

        bias = "Waiting"
        if short_sma is not None and long_sma is not None:
            if short_sma > long_sma:
                bias = "Bullish"
            elif short_sma < long_sma:
                bias = "Bearish"
            else:
                bias = "Neutral"

        return StrategySnapshot(
            symbol=clean,
            price=price,
            short_sma=short_sma,
            long_sma=long_sma,
            rsi=rsi,
            volume=current_volume,
            avg_volume=avg_volume,
            relative_volume=relative_volume,
            volatility_percent=volatility_percent,
            momentum_percent=momentum_percent,
            recent_momentum_percent=recent_momentum_percent,
            long_momentum_percent=long_momentum_percent,
            session_change_percent=session_change_percent,
            session_pullback_percent=session_pullback_percent,
            recent_pullback_percent=recent_pullback_percent,
            vwap=vwap,
            vwap_distance_percent=vwap_distance_percent,
            smi=smi,
            atr_percent=atr_percent,
            volume_ok=volume_ok,
            bias=bias,
            bars=len(closes),
            last_action=self.last_action.get(clean, ""),
            entry_score=self.entry_score.get(clean),
        )


def _sma(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) < period:
        return None
    section = values[-period:]
    return sum(section) / Decimal(period)


def _previous_average(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) <= period:
        return None
    section = values[-(period + 1) : -1]
    return sum(section) / Decimal(period)


def _rsi(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) <= period:
        return None

    window = values[-(period + 1) :]
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(window, window[1:]):
        change = current - previous
        if change > 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    average_gain = sum(gains) / Decimal(period)
    average_loss = sum(losses) / Decimal(period)
    if average_gain == 0 and average_loss == 0:
        return Decimal("50")
    if average_loss == 0:
        return Decimal("100")
    if average_gain == 0:
        return Decimal("0")

    rs = average_gain / average_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def _average_abs_percent_change(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) <= period:
        return None

    window = values[-(period + 1) :]
    changes: list[Decimal] = []
    for previous, current in zip(window, window[1:]):
        if previous <= 0:
            continue
        changes.append(abs((current - previous) / previous) * Decimal("100"))
    if not changes:
        return None
    return sum(changes) / Decimal(len(changes))


def _percent_change_over(values: list[Decimal], period: int) -> Decimal | None:
    if period <= 0 or len(values) <= period:
        return None
    previous = values[-(period + 1)]
    current = values[-1]
    return _percent_change(current, previous)


def _percent_change(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current - previous) / previous * Decimal("100")


def _pullback_from_high_percent(current: Decimal | None, high: Decimal | None) -> Decimal | None:
    if current is None or high is None or high <= 0:
        return None
    if current >= high:
        return Decimal("0")
    return (high - current) / high * Decimal("100")


def _latest_session_points(history: list[BarPoint]) -> list[BarPoint]:
    if not history:
        return []
    latest_key = _timestamp_session_key(history[-1].timestamp)
    if not latest_key:
        return list(history)
    return [point for point in history if _timestamp_session_key(point.timestamp) == latest_key]


def _timestamp_session_key(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return raw[:10]


def _vwap(points: list[BarPoint]) -> Decimal | None:
    weighted = Decimal("0")
    total_volume = Decimal("0")
    for point in points:
        if point.close <= 0 or point.volume <= 0:
            continue
        weighted += point.close * point.volume
        total_volume += point.volume
    if total_volume <= 0:
        return None
    return weighted / total_volume


def _smi(
    closes: list[Decimal],
    highs: list[Decimal],
    lows: list[Decimal],
    period: int,
    smooth: int = 3,
) -> Decimal | None:
    if period <= 0 or len(closes) < period:
        return None

    raw_values: list[Decimal] = []
    window_count = max(1, smooth)
    start_index = max(period, len(closes) - window_count + 1)
    for end in range(start_index, len(closes) + 1):
        high_window = highs[end - period : end]
        low_window = lows[end - period : end]
        if not high_window or not low_window:
            continue
        highest = max(high_window)
        lowest = min(low_window)
        range_half = (highest - lowest) / Decimal("2")
        if range_half <= 0:
            raw_values.append(Decimal("0"))
            continue
        midpoint = (highest + lowest) / Decimal("2")
        raw_values.append((closes[end - 1] - midpoint) / range_half * Decimal("100"))

    if not raw_values:
        return None
    return sum(raw_values) / Decimal(len(raw_values))


def _atr_percent(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int,
) -> Decimal | None:
    if period <= 0 or len(closes) <= period:
        return None

    true_ranges: list[Decimal] = []
    start = len(closes) - period
    for index in range(start, len(closes)):
        high = highs[index]
        low = lows[index]
        previous_close = closes[index - 1]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    current = closes[-1]
    if not true_ranges or current <= 0:
        return None
    return (sum(true_ranges) / Decimal(len(true_ranges))) / current * Decimal("100")


def _format_decimal(value: Decimal | None, places: int) -> str:
    if value is None:
        return "-"
    quant = Decimal("1").scaleb(-places)
    return str(value.quantize(quant))


def _format_volume(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def order_quantity(notional: Decimal, price: Decimal) -> Decimal:
    if notional <= 0 or price <= 0:
        return Decimal("0")
    qty = notional / price
    return qty.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
