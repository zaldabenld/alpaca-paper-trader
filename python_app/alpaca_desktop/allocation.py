"""Buy and hold with a trend switch (entry_mode "allocation"): the pure decisions.

Hold the risk-on set in equal weights while the signal symbol is above its simple moving average,
otherwise the risk-off set. The regime is re-decided on check days only (the last session of the
week, or every session), so a price wobbling around its average cannot flip the account daily.

Nothing here talks to the broker or the network; the engine feeds in prices, sessions and holdings
and executes the plan this module returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal

MIN_ORDER_NOTIONAL = Decimal("1")


@dataclass(frozen=True)
class AllocationSignal:
    price: Decimal
    average: Decimal
    gap_percent: Decimal
    regime: str  # "on" or "off"
    days: int

    def describe(self, symbol: str) -> str:
        side = "above" if self.gap_percent >= 0 else "below"
        return (
            f"{symbol} {self.price:.2f} is {abs(self.gap_percent):.2f}% {side} its {self.days}-day average "
            f"{self.average:.2f}"
        )


def allocation_signal(previous_closes: list[Decimal], live_price: Decimal | None, days: int) -> AllocationSignal | None:
    """The trend signal from the previous days-1 closes plus the live price; None without enough data."""
    if days < 2 or live_price is None or live_price <= 0:
        return None
    closes = [Decimal(value) for value in previous_closes if value is not None and Decimal(value) > 0]
    if len(closes) < days - 1:
        return None
    window = closes[-(days - 1):] + [Decimal(live_price)]
    average = sum(window, Decimal("0")) / Decimal(days)
    if average <= 0:
        return None
    gap = (Decimal(live_price) / average - Decimal("1")) * Decimal("100")
    return AllocationSignal(
        price=Decimal(live_price),
        average=average,
        gap_percent=gap,
        regime="on" if Decimal(live_price) > average else "off",
        days=days,
    )


def is_check_day(today: date, sessions: list[date], check: str) -> bool:
    """True when today is a session and the regime should be re-decided today.

    "daily": every session. "weekly": the last session of the ISO week, i.e. the next session falls
    in a different week (so a Thursday before a Good Friday holiday counts, and so does a short
    Wednesday before Thanksgiving only when Thursday and Friday are both closed).
    """
    upcoming = sorted(day for day in sessions if day >= today)
    if not upcoming or upcoming[0] != today:
        return False
    if check == "daily":
        return True
    later = [day for day in upcoming if day > today]
    if not later:
        return False  # without the next session we cannot tell; repair still runs
    return later[0].isocalendar()[:2] != today.isocalendar()[:2]


def next_check_day(today: date, sessions: list[date], check: str) -> date | None:
    for day in sorted(day for day in sessions if day >= today):
        if is_check_day(day, sessions, check):
            return day
    return None


@dataclass(frozen=True)
class Holding:
    symbol: str
    qty: Decimal
    market_value: Decimal
    qty_available: Decimal


@dataclass
class AllocationPlan:
    target: list[str]
    sells: list[tuple[str, Decimal, str]] = field(default_factory=list)
    buys: list[tuple[str, Decimal, str]] = field(default_factory=list)
    weights: dict[str, Decimal] = field(default_factory=dict)
    target_weight: Decimal = Decimal("0")
    note: str = ""


def held_regime(holdings: list[Holding], risk_on: list[str], risk_off: list[str]) -> str:
    """Which set the account holds now: "on", "off", "mixed" (both sets) or "none".

    Symbols outside both sets do not count: they are sold at the next window whatever the regime,
    so a stray holding can never let the signal switch the portfolio mid-week.
    """
    symbols = {item.symbol for item in holdings if item.qty > 0}
    in_on = bool(symbols & set(risk_on))
    in_off = bool(symbols & set(risk_off))
    if in_on and in_off:
        return "mixed"
    if in_on:
        return "on"
    return "off" if in_off else "none"


def portfolio_is_valid(
    holdings: list[Holding],
    target: list[str],
    equity: Decimal,
    invest_percent: Decimal,
    drift_percent: Decimal,
) -> bool:
    """Everything held is in the target set, every target symbol is held, and each is near its weight."""
    held = {item.symbol: item for item in holdings if item.qty > 0}
    if set(held) != set(target) or equity <= 0:
        return False
    target_weight = invest_percent / Decimal(len(target))
    for item in held.values():
        weight = item.market_value / equity * Decimal("100")
        if weight < target_weight - drift_percent:
            return False
    return True


def plan_allocation(
    holdings: list[Holding],
    target: list[str],
    equity: Decimal,
    cash: Decimal,
    buying_power: Decimal,
    invest_percent: Decimal,
    drift_percent: Decimal,
    rebalance: bool,
) -> AllocationPlan:
    """What to sell and buy to hold the target set in equal weights.

    Sells come first: anything held outside the target, and (only when rebalance is True: a check
    day or a switch) target holdings more than drift_percent points over their weight. Buys are only
    planned when there is nothing to sell, so they spend cash that has actually settled from the
    sells. Buys top up target symbols that are missing or more than drift_percent points under
    weight, scaled down to the cash left above the reserve the invest percent keeps back. A buy is
    never sized from margin.
    """
    plan = AllocationPlan(target=list(target))
    if not target or equity <= 0:
        plan.note = "no target or no equity"
        return plan
    target_weight = invest_percent / Decimal(len(target))
    plan.target_weight = target_weight
    held = {item.symbol: item for item in holdings if item.qty > 0}
    for symbol, item in held.items():
        plan.weights[symbol] = item.market_value / equity * Decimal("100")

    for symbol, item in held.items():
        if symbol not in target:
            if item.qty_available > 0:
                plan.sells.append((symbol, item.qty_available, "not in the target set"))
            continue
        weight = plan.weights[symbol]
        if rebalance and weight > target_weight + drift_percent and item.market_value > 0:
            excess_value = (weight - target_weight) / Decimal("100") * equity
            qty = (item.qty * excess_value / item.market_value).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
            qty = min(qty, item.qty_available)
            if qty > 0 and excess_value >= MIN_ORDER_NOTIONAL:
                plan.sells.append((symbol, qty, f"trim {weight:.1f}% to {target_weight:.1f}%"))
    if plan.sells:
        return plan

    reserve = equity * (Decimal("100") - invest_percent) / Decimal("100")
    budget = min(cash, buying_power) - reserve
    wanted: list[tuple[str, Decimal]] = []
    for symbol in target:
        current = held[symbol].market_value if symbol in held else Decimal("0")
        weight = current / equity * Decimal("100")
        if symbol in held and weight >= target_weight - drift_percent:
            continue
        need = target_weight / Decimal("100") * equity - current
        if need > 0:
            wanted.append((symbol, need))
    total = sum((need for _, need in wanted), Decimal("0"))
    if not wanted or budget <= 0:
        if wanted:
            plan.note = "waiting for cash"
        return plan
    scale = min(Decimal("1"), budget / total) if total > 0 else Decimal("0")
    for symbol, need in wanted:
        notional = (need * scale).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if notional >= MIN_ORDER_NOTIONAL:
            plan.buys.append((symbol, notional, f"to {target_weight:.1f}% of equity"))
    return plan
