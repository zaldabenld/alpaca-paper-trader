"""Market movers (entry_mode "movers"): a weighted buy score and a stop sized to the stock.

The idea: a stock that is going up on unusually heavy volume tends to keep going. No single reading
vetoes a buy. Each reading earns points and the buy happens when the total clears the account's
minimum score, so heavy volume can outweigh anything else. RSI is one of the weights (0 by default),
never a ceiling.

Three things are still yes/no, because they are what "going up" means: the stock is up on the
session, above its VWAP, and not lower than it was five minutes ago.

What the weights are built on (consolidated 5-minute bars, Nov 2025 - Nov 2026, about 330 liquid
symbols, one buy per symbol per day, at most 20 a day at 5% each, volume read 15 minutes late):
  - buying anything that is up and rising, no volume weighting: about -8% a year;
  - the same with an RSI <= 65 ceiling: about -11% a year, and with a 2.25% VWAP cap too: -14%;
  - this score at 60 with the stop below: about +28% a year, both halves of the year positive;
  - of those buys, the ones with RSI above 65 made most of the money.
Volume is measured as today's total volume so far against the stock's own average by this time of
day over its last 14 sessions.

The stop is sized to the stock: a fraction of its average daily range, so a stock that moves 8% a
day is not shaken out by a 1.25% wiggle. Once the position is up by that same distance the stop
follows the peak at that distance and never goes back down.

Nothing here talks to the broker or the network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

SLOTS = 78  # 5-minute bars in a regular session, 09:30 .. 15:55 ET
SLOT_MINUTES = 5
MIN_PROFILE_SESSIONS = 10
PROFILE_SESSIONS = 14

# Where each reading earns its full points.
FULL_HALF_HOUR_MOVE = Decimal("2")     # +2% over the last 30 minutes
FULL_VWAP_DISTANCE = Decimal("3")      # 3% above VWAP
FULL_FIVE_MIN_MOVE = Decimal("0.7")    # +0.7% over the last 5 minutes
RANGE_FLOOR = Decimal("2")             # daily range (ATR %) where points start ...
RANGE_FULL = Decimal("8")              # ... and where they are full
FULL_SESSION_MOVE = Decimal("5")       # +5% on the session
RSI_FLOOR = Decimal("50")
RSI_FULL = Decimal("90")


@dataclass(frozen=True)
class Weights:
    volume: Decimal = Decimal("45")
    half_hour_move: Decimal = Decimal("15")
    vwap: Decimal = Decimal("15")
    five_min_move: Decimal = Decimal("10")
    daily_range: Decimal = Decimal("10")
    session: Decimal = Decimal("5")
    rsi: Decimal = Decimal("0")
    volume_full_at: Decimal = Decimal("5")  # times the usual volume that earns the full volume points


@dataclass(frozen=True)
class Readings:
    relative_volume: Decimal | None      # today's volume so far / usual by this time of day
    half_hour_move: Decimal | None       # % change over the last 30 minutes (or since the open)
    five_min_move: Decimal | None        # % change over the last 5 minutes
    vwap_distance: Decimal | None        # % above (+) or below (-) the session VWAP
    session_change: Decimal | None       # % change on the session
    daily_range: Decimal | None          # 14-day average true range as % of price
    rsi: Decimal | None = None


@dataclass(frozen=True)
class Score:
    total: Decimal
    parts: tuple[tuple[str, Decimal], ...]

    def describe(self) -> str:
        """The points each reading earned. Volume is always shown, even at zero, since it carries the most."""
        return ", ".join(
            f"{label} +{points:.0f}"
            for index, (label, points) in enumerate(self.parts)
            if index == 0 or points >= Decimal("0.5")
        )


def _fraction(value: Decimal | None, low: Decimal, high: Decimal) -> Decimal:
    if value is None or high <= low:
        return Decimal("0")
    return min(Decimal("1"), max(Decimal("0"), (value - low) / (high - low)))


def volume_fraction(relative_volume: Decimal | None, full_at: Decimal) -> Decimal:
    """0 at the usual volume, 1 at full_at times usual, on a log scale (2x is worth more than half of 4x)."""
    if relative_volume is None or relative_volume <= 1 or full_at <= 1:
        return Decimal("0")
    fraction = math.log2(float(relative_volume)) / math.log2(float(full_at))
    return Decimal(str(min(1.0, max(0.0, fraction))))


def score(readings: Readings, weights: Weights) -> Score:
    """The weighted buy score, 0-100 with the default weights."""
    zero = Decimal("0")
    volume_label = (
        f"volume {readings.relative_volume:.1f}x" if readings.relative_volume is not None else "volume loading"
    )
    parts = (
        (volume_label, weights.volume * volume_fraction(readings.relative_volume, weights.volume_full_at)),
        ("30-min move", weights.half_hour_move * _fraction(readings.half_hour_move, zero, FULL_HALF_HOUR_MOVE)),
        ("above VWAP", weights.vwap * _fraction(readings.vwap_distance, zero, FULL_VWAP_DISTANCE)),
        ("5-min move", weights.five_min_move * _fraction(readings.five_min_move, zero, FULL_FIVE_MIN_MOVE)),
        ("daily range", weights.daily_range * _fraction(readings.daily_range, RANGE_FLOOR, RANGE_FULL)),
        ("session", weights.session * _fraction(readings.session_change, zero, FULL_SESSION_MOVE)),
        ("RSI", weights.rsi * _fraction(readings.rsi, RSI_FLOOR, RSI_FULL)),
    )
    total = sum((points for _, points in parts), zero)
    return Score(total=total.quantize(Decimal("0.1")), parts=tuple((label, points) for label, points in parts))


def direction_hold_reason(readings: Readings) -> str:
    """The three yes/no checks that define "going up"; empty when all pass."""
    if readings.session_change is None or readings.vwap_distance is None or readings.five_min_move is None:
        return "Hold (movers: price history warming up)"
    if readings.session_change <= 0:
        return f"Hold (movers: down {abs(readings.session_change):.2f}% on the session)"
    if readings.vwap_distance <= 0:
        return f"Hold (movers: {abs(readings.vwap_distance):.2f}% under VWAP)"
    if readings.five_min_move < 0:
        return f"Hold (movers: fell {abs(readings.five_min_move):.2f}% in the last 5 minutes)"
    return ""


def stop_distance_percent(
    daily_range: Decimal | None, fraction: Decimal, minimum: Decimal, maximum: Decimal, fallback: Decimal
) -> Decimal:
    """How far below the buy the stop sits, as a percent: a fraction of the daily range, kept in bounds."""
    if daily_range is None or daily_range <= 0:
        return min(max(fallback, minimum), maximum)
    return min(max(daily_range * fraction, minimum), maximum).quantize(Decimal("0.01"))


# ----- time-of-day volume -------------------------------------------------------------------------


def slot_of(minute_of_day: int) -> int | None:
    """The 5-minute slot a bar starting at minute_of_day (ET) belongs to; None outside regular hours."""
    index = (minute_of_day - 570) // SLOT_MINUTES
    return index if 0 <= index < SLOTS and minute_of_day >= 570 else None


def cumulative_volume(bars: list[tuple[int, Decimal]]) -> list[float]:
    """Running total of volume by slot from (minute_of_day, volume) bars; missing bars add nothing."""
    by_slot = [0.0] * SLOTS
    for minute, volume in bars:
        index = slot_of(minute)
        if index is not None and volume and volume > 0:
            by_slot[index] += float(volume)
    total = 0.0
    out: list[float] = []
    for value in by_slot:
        total += value
        out.append(total)
    return out


def average_profile(sessions: list[list[float]]) -> list[float] | None:
    """The usual running total of volume by slot, averaged over recent sessions that traded."""
    traded = [session for session in sessions if len(session) == SLOTS and session[-1] > 0]
    if len(traded) < MIN_PROFILE_SESSIONS:
        return None
    recent = traded[-PROFILE_SESSIONS:]
    return [sum(session[index] for session in recent) / len(recent) for index in range(SLOTS)]


def last_complete_slot(minutes_since_open: float, delay_minutes: float) -> int | None:
    """The newest slot whose consolidated bar can be read, given the data delay; None before the first one."""
    usable = minutes_since_open - delay_minutes
    index = int(usable // SLOT_MINUTES) - 1
    if index < 0:
        return None
    return min(index, SLOTS - 1)


def relative_volume(today: list[float], profile: list[float] | None, slot: int | None) -> Decimal | None:
    if profile is None or slot is None or not (0 <= slot < SLOTS) or len(today) != SLOTS:
        return None
    usual = profile[slot]
    if usual <= 0:
        return None
    return Decimal(str(round(today[slot] / usual, 4)))
