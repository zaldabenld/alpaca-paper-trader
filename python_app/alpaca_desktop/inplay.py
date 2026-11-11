"""Day trade the stocks in play (entry_mode "inplay"): the pure decisions.

Each session, once the opening range is over and its consolidated (SIP) bars can be read, the liquid
symbols are ranked by relative opening-range volume: the volume of today's first minutes against
the average volume of the same minutes on recent sessions. A stock trading two or three times its
usual opening volume is "in play" (news, earnings, a sector move) and tends to keep moving.

The top picks with a green range (closed above where it opened), a wide enough daily range and
enough dollars traded each day are watched. Each is bought once when it trades above its range
high, but not when it has already run more than the chase limit past it, with its stop at the range
middle (or low). Exits are the stop or the sell-off before the close.

Backtest (SIP 5-minute bars, Nov 2025 - Nov 2026, ~300 liquid symbols, 0.03% cost each side,
10 picks at 10% of equity): about 48% a year, worst drawdown 3.2%, Sharpe 2.2, 11 of 13 months up.
At 0.10% cost each side: about 39% a year, Sharpe 1.8.

Nothing here talks to the broker or the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Large and popular names always ranked, on top of the recent most-active lists.
CORE_SYMBOLS = (
    "AAPL MSFT NVDA AMZN META GOOGL AVGO TSLA AMD NFLX COST PEP ADBE CSCO INTC QCOM TXN AMAT MU LRCX KLAC "
    "MRVL ASML PANW CRWD SNOW PLTR SHOP UBER ABNB COIN MSTR HOOD SOFI RIVN LCID NIO F GM BA DIS JPM BAC WFC C "
    "GS MS XOM CVX OXY SLB COP PFE MRK LLY UNH JNJ ABBV WMT TGT HD LOW NKE SBUX MCD KO T VZ CMCSA ORCL CRM IBM "
    "DELL SMCI ARM TSM BABA JD PDD SNAP PINS RBLX ROKU DKNG AFRM UPST MARA RIOT CLSK IREN APLD BE ONDS RKLB "
    "ASTS IONQ RGTI QBTS SOUN BBAI AAL DAL UAL CCL NCLH RCL LUV PYPL XYZ"
).split()
# Broad index funds move with the market rather than on their own news; they are never picks.
NEVER_PICK = {"SPY", "QQQ", "DIA", "IWM"}
MIN_HISTORY_SESSIONS = 10
HISTORY_SESSIONS = 14
ATR_DAYS = 14
DOLLAR_VOLUME_DAYS = 20


@dataclass(frozen=True)
class RangeBar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class DailyStats:
    atr_percent: Decimal
    dollar_volume: Decimal


@dataclass(frozen=True)
class Pick:
    symbol: str
    rank: int
    high: Decimal
    low: Decimal
    open: Decimal
    close: Decimal
    relative_volume: Decimal
    atr_percent: Decimal
    dollar_volume: Decimal
    stop: Decimal

    def describe(self) -> str:
        return (
            f"range {self.low}-{self.high}, {self.relative_volume:.1f}x range volume, "
            f"daily range {self.atr_percent:.1f}%, stop {self.stop}"
        )


def combine_range(bars: list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]) -> RangeBar | None:
    """One opening-range bar from the session's first bars (open, high, low, close, volume)."""
    if not bars:
        return None
    return RangeBar(
        open=bars[0][0],
        high=max(bar[1] for bar in bars),
        low=min(bar[2] for bar in bars),
        close=bars[-1][3],
        volume=sum((bar[4] for bar in bars), Decimal("0")),
    )


def daily_stats(bars: list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]]) -> DailyStats | None:
    """14-day average true range as a percent of the last close, and 20-day average dollars traded.

    bars are finished daily bars (open, high, low, close, volume), oldest first, before today.
    """
    if len(bars) < max(ATR_DAYS, DOLLAR_VOLUME_DAYS) + 1:
        return None
    true_ranges = []
    for index in range(len(bars) - ATR_DAYS, len(bars)):
        _, high, low, _, _ = bars[index]
        previous_close = bars[index - 1][3]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    last_close = bars[-1][3]
    if last_close <= 0:
        return None
    atr = sum(true_ranges, Decimal("0")) / Decimal(ATR_DAYS)
    recent = bars[-DOLLAR_VOLUME_DAYS:]
    dollar_volume = sum((bar[3] * bar[4] for bar in recent), Decimal("0")) / Decimal(DOLLAR_VOLUME_DAYS)
    return DailyStats(atr_percent=atr / last_close * Decimal("100"), dollar_volume=dollar_volume)


def stop_price(bar: RangeBar, stop_mode: str) -> Decimal:
    if stop_mode == "range_low":
        return bar.low - Decimal("0.01")
    return (bar.high + bar.low) / Decimal("2")


def rank_picks(
    today: dict[str, RangeBar],
    history_volumes: dict[str, list[Decimal]],
    stats: dict[str, DailyStats],
    *,
    min_relative_volume: Decimal,
    min_atr_percent: Decimal,
    min_dollar_volume: Decimal,
    max_picks: int,
    stop_mode: str,
) -> tuple[list[Pick], dict[str, int]]:
    """The day's picks in rank order, and how many symbols each filter turned away."""
    rejected = {"no data": 0, "liquidity": 0, "daily range": 0, "range volume": 0, "red range": 0, "index fund": 0}
    ranked: list[tuple[Decimal, str, RangeBar, DailyStats]] = []
    for symbol, bar in today.items():
        if symbol in NEVER_PICK:
            rejected["index fund"] += 1
            continue
        past = [volume for volume in history_volumes.get(symbol, []) if volume > 0][-HISTORY_SESSIONS:]
        stat = stats.get(symbol)
        if stat is None or len(past) < MIN_HISTORY_SESSIONS or bar.high <= 0:
            rejected["no data"] += 1
            continue
        if stat.dollar_volume < min_dollar_volume:
            rejected["liquidity"] += 1
            continue
        if stat.atr_percent < min_atr_percent:
            rejected["daily range"] += 1
            continue
        relative = bar.volume / (sum(past, Decimal("0")) / Decimal(len(past)))
        if relative < min_relative_volume:
            rejected["range volume"] += 1
            continue
        if not bar.close > bar.open:
            rejected["red range"] += 1
            continue
        ranked.append((relative, symbol, bar, stat))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    picks = [
        Pick(
            symbol=symbol,
            rank=index,
            high=bar.high,
            low=bar.low,
            open=bar.open,
            close=bar.close,
            relative_volume=relative,
            atr_percent=stat.atr_percent,
            dollar_volume=stat.dollar_volume,
            stop=stop_price(bar, stop_mode),
        )
        for index, (relative, symbol, bar, stat) in enumerate(ranked[:max_picks])
    ]
    return picks, rejected


def entry_hold_reason(pick: Pick, price: Decimal | None, max_chase_percent: Decimal) -> str:
    """Empty when price has cleared the range high and is still within the chase limit."""
    if price is None or price <= 0:
        return "Hold (in play: waiting for a price)"
    trigger = pick.high + Decimal("0.01")
    if price < trigger:
        return f"Hold (in play: waiting for a break of {pick.high})"
    past = (price / pick.high - Decimal("1")) * Decimal("100")
    if max_chase_percent > 0 and past > max_chase_percent:
        return f"Hold (in play: {past:.2f}% past the range high, more than {max_chase_percent}%)"
    if price <= pick.stop:
        return "Hold (in play: price at or under the stop)"
    return ""
