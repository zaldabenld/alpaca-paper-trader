"""Tick-level replay of movers-mode buys and sells on recorded days.

What it is for: comparing movers settings against each other on the same days, with fills that a
bar replay cannot give (a 1.25% stop on a stock quoted a cent wide is decided inside a minute).

How a day is replayed:
  - The stock list is the day's own most-active list, read from the day tape (the app records it
    about once a minute), so the replay looks at the symbols the app looked at, when it did.
  - Readings come from the app's own code (TraderEngine.mover_readings and movers.score) fed with
    Alpaca's consolidated 1-minute bars, the same 14-session volume profile the live worker
    builds, and the same 16-minute delay on volume.
  - A buy is decided at the end of a minute. The quote just after it gives the spread for the
    pre-order recheck and the fill (the ask). A stop sells at the bid of the first quote at or
    under it. Stop and trail prices come from TraderEngine.position_stop_price.
  - While a position is held, a minute is stepped through quote by quote whenever its bar could
    have touched the stop; other minutes only move the trail.
  - Everything is sold ten minutes before the close at the bid, as the account does.

What it leaves out, so read results as old-versus-new, not as a forecast:
  - Decisions are once a minute on consolidated prices. The live app decides every 5 seconds on
    IEX prices, which can lag.
  - Inverse funds bought by the trend-hold rules are not replayed (the settings under test do not
    touch them), and halts are ignored.
  - Whether a stock can be bought at all (active, tradable, fractional shares) is Alpaca's status
    today, assumed to have been the same on the replayed day.
  - Paper fills are modelled as the quote at that instant, with no queue and no partial fills.
  - Sizing is the repo's standard replay account: $1,000, 5% a position, 20 positions.

Nothing here places orders. It reads market data with the named account's saved keys and never
prints them. Data is cached under --cache so a second run is quick.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pickle
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_APP = REPO_ROOT / "python_app"
if str(PYTHON_APP) not in sys.path:
    sys.path.insert(0, str(PYTHON_APP))
os.environ.setdefault("ALPACA_TRADER_DISABLE_AUTO_CONNECT", "1")
os.environ.setdefault("ALPACA_TRADER_DISABLE_AUTO_START", "1")
os.environ.setdefault("ALPACA_TRADER_DISABLE_DAY_TAPE", "1")
os.environ.setdefault("ALPACA_TRADER_DISABLE_ALERTS", "1")

from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.historical import StockHistoricalDataClient  # noqa: E402
from alpaca.data.requests import StockBarsRequest, StockQuotesRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402
from alpaca.common.enums import Sort  # noqa: E402
from alpaca.trading.client import TradingClient  # noqa: E402

from alpaca_desktop import inplay as inplay_logic  # noqa: E402
from alpaca_desktop import movers as movers_logic  # noqa: E402
from alpaca_desktop import storage  # noqa: E402
from alpaca_desktop.engine import (  # noqa: E402
    MARKET_TIMEZONE,
    MAX_ENTRY_REFERENCE_PREMIUM_PERCENT,
    AppConfig,
    TraderEngine,
    direction_checks,
)

D = Decimal
REPLAY_EQUITY = D("1000")
SIP_DELAY_MINUTES = TraderEngine.INPLAY_SIP_DELAY_MINUTES
ORDER_LATENCY = timedelta(seconds=2)
QUOTE_KEEP = timedelta(minutes=10)
REQUEST_GAP_SECONDS = 0.4  # about 150 requests a minute, under the data plan's 200

# The settings under test. Everything else comes from the account's saved movers settings.
VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("A  before 11-13 (no re-entry bar, no spread cost)", dict(boost="0", spread="0", volume_current=False, new_high=False)),
    ("B  + re-entry +20 per losing exit", dict(boost="20", spread="0", volume_current=False, new_high=False)),
    ("C  + spread cost 40", dict(boost="20", spread="40", volume_current=False, new_high=False)),
    ("D  + volume must be current", dict(boost="20", spread="40", volume_current=True, new_high=False)),
    ("E  + new-high rule after a winning sale (live now)", dict(boost="20", spread="40", volume_current=True, new_high=True)),
    ("F  live now, but spread cost 20", dict(boost="20", spread="20", volume_current=True, new_high=True)),
    ("G  live now, but spread cost 60", dict(boost="20", spread="60", volume_current=True, new_high=True)),
    ("W  weighted only: the 3 going-up checks become points", dict(boost="20", spread="40", volume_current=True, new_high=True, style="weighted")),
]


class Market:
    """Market data with a disk cache and a request pace."""

    def __init__(self, api_key: str, secret_key: str, cache: Path) -> None:
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self.trading = TradingClient(api_key, secret_key, paper=True)
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.last_request = 0.0
        self.requests = 0
        self.quote_cache: dict[str, dict[Any, Any]] = {}
        self.quote_cache_dirty: set[str] = set()

    def pace(self) -> None:
        wait = REQUEST_GAP_SECONDS - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        self.last_request = time.monotonic()
        self.requests += 1

    def call(self, fetch: Any) -> Any:
        for attempt in range(6):
            self.pace()
            try:
                return fetch()
            except Exception as exc:  # rate limit or a network blip: wait and try again
                if attempt == 5:
                    raise
                time.sleep(5 * (attempt + 1) if "429" in str(exc) or "rate" in str(exc).lower() else 2)
        return None

    def cached(self, name: str, build: Any) -> Any:
        path = self.cache / f"{name}.pkl"
        if path.exists():
            with path.open("rb") as handle:
                return pickle.load(handle)
        value = build()
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as handle:
            pickle.dump(value, handle)
        tmp.replace(path)
        return value

    # ----- bars -----------------------------------------------------------------------------

    def minute_bars(self, day: date, symbols: list[str]) -> dict[str, list[tuple[datetime, D, D, D, D, D]]]:
        def build() -> dict[str, list[tuple[datetime, D, D, D, D, D]]]:
            start = datetime.combine(day, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30)
            end = start.replace(hour=16, minute=0)
            out: dict[str, list[tuple[datetime, D, D, D, D, D]]] = {}
            for index in range(0, len(symbols), 50):
                batch = symbols[index : index + 50]
                bars = self.call(lambda: self.data.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=batch, timeframe=TimeFrame.Minute, start=start, end=end - timedelta(seconds=1),
                    feed=DataFeed.SIP, adjustment=Adjustment.RAW, sort=Sort.ASC)))
                for symbol, rows in (getattr(bars, "data", {}) or {}).items():
                    out[symbol] = [
                        (bar.timestamp.astimezone(timezone.utc), D(str(bar.open)), D(str(bar.high)), D(str(bar.low)),
                         D(str(bar.close)), D(str(bar.volume)))
                        for bar in rows
                    ]
            return out
        return self.cached(f"{day:%Y%m%d}-minute-bars", build)

    def volume_data(self, day: date, symbols: list[str], engine: TraderEngine) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """(usual volume by slot, today's running volume by slot, daily range stats), built the way the live worker does."""
        def build() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
            sessions = engine.mover_previous_sessions(self.trading, day)
            per_symbol: dict[str, list[list[float]]] = {symbol: [] for symbol in symbols}
            for session in sessions:
                bars = self.call(lambda: engine.mover_fetch_volume(self.data, symbols, session, None))
                for symbol in symbols:
                    per_symbol[symbol].append(movers_logic.cumulative_volume(bars.get(symbol, [])))
            profiles = {symbol: movers_logic.average_profile(per_symbol[symbol]) for symbol in symbols}
            today_bars = self.call(lambda: engine.mover_fetch_volume(self.data, symbols, day, None))
            today = {symbol: movers_logic.cumulative_volume(today_bars.get(symbol, [])) for symbol in symbols}
            stats: dict[str, Any] = {}
            start = datetime.combine(day - timedelta(days=60), datetime.min.time(), MARKET_TIMEZONE)
            end = datetime.combine(day, datetime.min.time(), MARKET_TIMEZONE) - timedelta(seconds=1)
            for index in range(0, len(symbols), 100):
                batch = symbols[index : index + 100]
                bars = self.call(lambda: self.data.get_stock_bars(StockBarsRequest(
                    symbol_or_symbols=batch, timeframe=TimeFrame.Day, start=start, end=end, feed=DataFeed.SIP,
                    adjustment=Adjustment.SPLIT, sort=Sort.ASC)))
                for symbol, rows in (getattr(bars, "data", {}) or {}).items():
                    stat = inplay_logic.daily_stats([
                        (D(str(bar.open)), D(str(bar.high)), D(str(bar.low)), D(str(bar.close)), D(str(bar.volume)))
                        for bar in rows if bar.timestamp.astimezone(MARKET_TIMEZONE).date() < day
                    ])
                    if stat is not None:
                        stats[symbol] = stat
            return profiles, today, stats
        return self.cached(f"{day:%Y%m%d}-volume", build)

    def not_buyable(self, symbols: list[str]) -> dict[str, str]:
        """Symbols the app would hold for the asset itself (inactive, not tradable, or no fractional
        shares, which the account's dollar-sized buys need). Alpaca reports today's status, which is
        taken to have held on the replayed day too."""
        path = self.cache / "assets.pkl"
        known: dict[str, str] = pickle.loads(path.read_bytes()) if path.exists() else {}
        missing = [symbol for symbol in symbols if symbol not in known]
        for symbol in missing:
            try:
                asset = self.call(lambda: self.trading.get_asset(symbol))
                status = str(getattr(asset, "status", "") or "").split(".")[-1].lower()
                if status and status != "active":
                    known[symbol] = f"asset {status}"
                elif getattr(asset, "tradable", True) is False:
                    known[symbol] = "not tradable"
                elif getattr(asset, "fractionable", True) is False:
                    known[symbol] = "not fractionable"
                else:
                    known[symbol] = ""
            except Exception:
                known[symbol] = ""  # the app leaves a symbol eligible when the check fails
        if missing:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(known))
            tmp.replace(path)
        return {symbol: known[symbol] for symbol in symbols if known.get(symbol)}

    # ----- quotes ---------------------------------------------------------------------------

    def day_quotes(self, day: date) -> dict[Any, Any]:
        key = f"{day:%Y%m%d}"
        if key not in self.quote_cache:
            path = self.cache / f"{key}-quotes.pkl"
            self.quote_cache[key] = pickle.loads(path.read_bytes()) if path.exists() else {}
        return self.quote_cache[key]

    def save_quotes(self) -> None:
        for key in list(self.quote_cache_dirty):
            path = self.cache / f"{key}-quotes.pkl"
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(self.quote_cache[key]))
            tmp.replace(path)
        self.quote_cache_dirty.clear()

    def quote_at(self, symbol: str, at: datetime) -> tuple[D, D] | None:
        """The newest consolidated bid and ask at or before `at`; None when there is none nearby."""
        store = self.day_quotes(at.astimezone(MARKET_TIMEZONE).date())
        key = ("at", symbol, at)
        if key not in store:
            quotes = self.call(lambda: self.data.get_stock_quotes(StockQuotesRequest(
                symbol_or_symbols=symbol, start=at - timedelta(minutes=15), end=at, limit=1, feed=DataFeed.SIP, sort=Sort.DESC)))
            rows = (getattr(quotes, "data", {}) or {}).get(symbol, [])
            store[key] = (D(str(rows[0].bid_price)), D(str(rows[0].ask_price))) if rows else None
            self.quote_cache_dirty.add(f"{at.astimezone(MARKET_TIMEZONE).date():%Y%m%d}")
        return store[key]

    def quotes_in_minute(self, symbol: str, start: datetime) -> list[tuple[datetime, D, D]]:
        store = self.day_quotes(start.astimezone(MARKET_TIMEZONE).date())
        key = ("minute", symbol, start)
        if key not in store:
            quotes = self.call(lambda: self.data.get_stock_quotes(StockQuotesRequest(
                symbol_or_symbols=symbol, start=start, end=start + timedelta(seconds=60) - timedelta(microseconds=1),
                feed=DataFeed.SIP, sort=Sort.ASC)))
            rows = (getattr(quotes, "data", {}) or {}).get(symbol, [])
            store[key] = [(row.timestamp.astimezone(timezone.utc), D(str(row.bid_price)), D(str(row.ask_price))) for row in rows]
            self.quote_cache_dirty.add(f"{start.astimezone(MARKET_TIMEZONE).date():%Y%m%d}")
        return store[key]


def tape_universe(tape: Path, cache: Path) -> list[tuple[datetime, tuple[str, ...]]]:
    """(time, most-active symbols) each time the day's list changed, from the day tape."""
    out_path = cache / f"{tape.stem}-universe.json"
    if out_path.exists():
        raw = json.loads(out_path.read_text())
        return [(datetime.fromisoformat(stamp), tuple(symbols)) for stamp, symbols in raw]
    lines = subprocess.run(["grep", "-F", '"top_volume_snapshot"', str(tape)], capture_output=True, text=True, check=False).stdout
    out: list[tuple[datetime, tuple[str, ...]]] = []
    for line in lines.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        symbols = tuple(str(symbol).upper() for symbol in (event.get("payload") or {}).get("symbols") or [])
        if symbols and (not out or out[-1][1] != symbols):
            out.append((datetime.fromisoformat(event["time"]), symbols))
    cache.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([(stamp.isoformat(), list(symbols)) for stamp, symbols in out]))
    return out


@dataclass
class Position:
    symbol: str
    entry: D
    qty: D
    bought_at: datetime
    stop: D
    peak: D
    spread: D
    score: D


@dataclass
class Trade:
    day: str
    symbol: str
    bought_at: str
    sold_at: str
    entry: D
    exit: D
    qty: D
    pnl: D
    reason: str
    score: D
    spread_percent: D


class DayData:
    """One recorded day, with every symbol's readings worked out once for all the variants."""

    def __init__(self, day: date, market: Market, tape_dir: Path, base: AppConfig) -> None:
        self.day = day
        self.open = datetime.combine(day, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30).astimezone(timezone.utc)
        self.close = self.open + timedelta(hours=6, minutes=30)
        universe = tape_universe(tape_dir / f"tape-{day:%Y%m%d}.jsonl", market.cache)
        self.universe = [(stamp, symbols) for stamp, symbols in universe if stamp <= self.close]
        engine = TraderEngine("replay")
        engine.config = base
        skip = lambda symbol: symbol[:1].isdigit() or engine.inverse_trend_active(symbol, base)  # noqa: E731
        self.symbols = sorted({symbol for _, symbols in self.universe for symbol in symbols[: base.most_active_count] if not skip(symbol)})
        self.bars = market.minute_bars(day, self.symbols)
        self.not_buyable = market.not_buyable(self.symbols)
        profiles, today, stats = market.volume_data(day, self.symbols, engine)
        self.by_minute: list[dict[str, tuple[datetime, D, D, D, D, D]]] = [{} for _ in range(390)]
        for symbol, rows in self.bars.items():
            for row in rows:
                index = int((row[0] - self.open).total_seconds() // 60)
                if 0 <= index < 390:
                    self.by_minute[index][symbol] = row
        self.readings = market.cached(
            f"{day:%Y%m%d}-readings-{base.stop_loss_percent}", lambda: self.build_readings(engine, base, profiles, today, stats)
        )

    def listed(self, at: datetime, count: int) -> tuple[str, ...]:
        current: tuple[str, ...] = ()
        for stamp, symbols in self.universe:
            if stamp > at:
                break
            current = symbols
        return current[:count]

    def build_readings(self, engine: TraderEngine, base: AppConfig, profiles: dict[str, Any], today: dict[str, Any], stats: dict[str, Any]) -> list[dict[str, movers_logic.Readings]]:
        engine.mover_session = self.day.isoformat()
        engine.mover_profiles = profiles
        engine.mover_stats = stats
        out: list[dict[str, movers_logic.Readings]] = []
        slot_seen: int | None = -1
        for index in range(390):
            for symbol, (stamp, _open, high, low, close, volume) in self.by_minute[index].items():
                engine.strategy_state.add_bar(symbol, close, stamp.isoformat(), volume, high, low)
            slot = movers_logic.last_complete_slot(index + 1, SIP_DELAY_MINUTES)
            if slot != slot_seen:
                slot_seen = slot
                engine.mover_volume, engine.mover_volume_recent = {}, {}
                for symbol in self.symbols:
                    value = movers_logic.relative_volume(today.get(symbol, []), profiles.get(symbol), slot)
                    if value is not None:
                        engine.mover_volume[symbol] = value
                    recent = movers_logic.recent_relative_volume(today.get(symbol, []), profiles.get(symbol), slot)
                    if recent is not None:
                        engine.mover_volume_recent[symbol] = recent
            engine.mover_volume_at = time.monotonic()
            now = self.open + timedelta(minutes=index + 1)
            minute: dict[str, movers_logic.Readings] = {}
            for symbol in self.listed(now, base.most_active_count):
                if symbol in self.bars and engine.strategy_state.histories.get(symbol):
                    snapshot = engine.snapshot(symbol)
                    if snapshot.price is not None:
                        minute[symbol] = engine.mover_readings(symbol, snapshot)
            out.append(minute)
        return out


def replay_day(data: DayData, market: Market, base: AppConfig, options: dict[str, Any]) -> list[Trade]:
    config = base.model_copy(update={
        "entry_mode": options.get("style", "scored"),
        "reentry_score_boost": D(options["boost"]),
        "mover_weight_spread": D(options["spread"]),
        "mover_volume_current": bool(options["volume_current"]),
    })
    engine = TraderEngine("replay")
    engine.config = config
    weights = engine.mover_weights(config)
    checks = direction_checks(config)  # none in the weighted style
    boost = max(D("0"), config.reentry_score_boost)
    drop = min(max(config.profit_trail_drop_percent, D("0")), D("50"))
    notional = REPLAY_EQUITY * config.max_trade_percent / D("100")
    positions: dict[str, Position] = {}
    losses: dict[str, int] = {}
    old_high: dict[str, tuple[D, datetime]] = {}
    quotes: dict[str, tuple[D, D, datetime]] = {}
    trades: list[Trade] = []
    first_entry = data.open + timedelta(minutes=config.entry_open_guard_minutes)
    last_entry = data.close - timedelta(minutes=config.entry_close_guard_minutes)
    flatten_at = data.close - timedelta(minutes=config.flatten_before_close_minutes) if config.flatten_before_close_minutes else None

    def stop_for(symbol: str, entry: D, peak: D) -> D:
        engine.position_peak_prices[symbol] = peak
        return engine.position_stop_price(symbol, entry, peak, config)

    def sell(position: Position, price: D, at: datetime, reason: str) -> None:
        positions.pop(position.symbol, None)
        engine.position_peak_prices.pop(position.symbol, None)
        pnl = (price - position.entry) * position.qty
        trades.append(Trade(
            day=data.day.isoformat(), symbol=position.symbol,
            bought_at=position.bought_at.astimezone(MARKET_TIMEZONE).strftime("%H:%M:%S"),
            sold_at=at.astimezone(MARKET_TIMEZONE).strftime("%H:%M:%S"), entry=position.entry, exit=price, qty=position.qty,
            pnl=pnl, reason=reason, score=position.score, spread_percent=position.spread / position.entry * 100,
        ))
        if price < position.entry:
            losses[position.symbol] = losses.get(position.symbol, 0) + 1
        elif price > position.entry and options["new_high"]:
            old_high[position.symbol] = (engine.round_exit_price(price / (D("1") - drop / D("100")), ROUND_UP), at)

    for index in range(390):
        bar_start = data.open + timedelta(minutes=index)
        now = bar_start + timedelta(minutes=1)
        bars = data.by_minute[index]

        # A stock sold at a gain is released once a bar that began after the sale trades above the old high.
        for symbol, (target, sold_at) in list(old_high.items()):
            bar = bars.get(symbol)
            if bar is not None and bar_start > sold_at and bar[2] > target:
                old_high.pop(symbol, None)

        # Held positions: this minute's bar, stepped through quote by quote when it could touch the stop.
        for position in list(positions.values()):
            bar = bars.get(position.symbol)
            if bar is None or position.bought_at >= now:
                continue
            _, _open, high, low, _close, _volume = bar
            likely_peak = max(position.peak, high - position.spread)
            stop_after = max(position.stop, stop_for(position.symbol, position.entry, likely_peak))
            if low - position.spread > stop_after:
                position.peak, position.stop = likely_peak, stop_after
                continue
            sold = False
            stepped = False
            for stamp, bid, _ask in market.quotes_in_minute(position.symbol, bar_start):
                if stamp <= position.bought_at or bid <= 0:
                    continue
                stepped = True
                if bid <= position.stop:
                    sell(position, bid, stamp, "trailing stop" if position.stop >= position.entry else "stop loss")
                    sold = True
                    break
                if bid > position.peak:
                    position.peak = bid
                    position.stop = max(position.stop, stop_for(position.symbol, position.entry, position.peak))
            if not sold and not stepped:
                position.peak, position.stop = likely_peak, stop_after  # no quotes that minute: the bar alone
            if not sold:
                engine.position_peak_prices[position.symbol] = position.peak

        if flatten_at is not None and now >= flatten_at:
            for position in list(positions.values()):
                quote = market.quote_at(position.symbol, now + ORDER_LATENCY)
                bar = bars.get(position.symbol)
                price = quote[0] if quote and quote[0] > 0 else (bar[4] if bar else position.entry)
                sell(position, price, now, "sold before the close")
            continue
        if now < first_entry or now > last_entry:
            continue

        readings = data.readings[index]
        candidates: list[tuple[D, str, movers_logic.Readings, D]] = []
        for symbol, reading in readings.items():
            if symbol in positions or symbol in data.not_buyable or movers_logic.direction_hold_reason(reading, *checks):
                continue
            needed = config.min_entry_score + boost * losses.get(symbol, 0) + (boost if symbol in old_high else D("0"))
            kept = quotes.get(symbol)
            if kept is not None and now - kept[2] <= QUOTE_KEEP and kept[0] > 0 and kept[1] > kept[0] and reading.price:
                tick = engine.price_increment_for(reading.price)
                reading = replace(reading, spread_percent=max(tick, kept[1] - kept[0]) / reading.price * 100)
            total = movers_logic.score(reading, weights).total
            if total >= needed:
                candidates.append((total, symbol, reading, needed))
        for _total, symbol, reading, needed in sorted(candidates, key=lambda item: (-item[0], item[1])):
            if config.max_open_positions > 0 and len(positions) >= config.max_open_positions:
                break
            order_at = now + ORDER_LATENCY
            quote = market.quote_at(symbol, order_at)
            if quote is None or quote[1] <= 0 or not reading.price:
                continue
            bid, ask = quote
            quotes[symbol] = (bid, ask, now)
            tick = engine.price_increment_for(reading.price)
            spread = max(tick, ask - bid) if bid > 0 and ask > bid else tick
            checked = replace(reading, spread_percent=spread / reading.price * 100)
            total = movers_logic.score(checked, weights).total
            if total < needed:
                continue  # the pre-order recheck with the real spread
            if (ask / reading.price - 1) * 100 > MAX_ENTRY_REFERENCE_PREMIUM_PERCENT:
                continue  # the app's own "wide order reference" hold
            engine.position_peak_prices.pop(symbol, None)
            position = Position(symbol=symbol, entry=ask, qty=notional / ask, bought_at=order_at, stop=D("0"), peak=ask, spread=spread, score=total)
            position.stop = stop_for(symbol, ask, ask)
            positions[symbol] = position
            old_high.pop(symbol, None)

    for position in list(positions.values()):  # only when the account has no close-out
        bar = data.by_minute[389].get(position.symbol)
        sell(position, bar[4] if bar else position.entry, data.close, "held at the close")
    return trades


def load_account(name: str) -> tuple[str, str, AppConfig]:
    raw = storage.load_settings()
    for account in raw.get("accounts") or []:
        if isinstance(account, dict) and account.get("name") == name:
            def secret(field: str) -> str:
                value = str(account.get(field) or "")
                try:
                    return storage.unprotect_text(value)
                except Exception:
                    return value
            return secret("api_key"), secret("secret_key"), AppConfig(**(account.get("config") or {}))
    raise SystemExit(f"No saved account named {name!r}.")


def summarize(name: str, trades: list[Trade], days: list[date]) -> dict[str, Any]:
    wins = [trade for trade in trades if trade.pnl > 0]
    lost = [trade for trade in trades if trade.pnl < 0]
    total = sum((trade.pnl for trade in trades), D("0"))
    by_day = {day.isoformat(): sum((trade.pnl for trade in trades if trade.day == day.isoformat()), D("0")) for day in days}
    by_symbol: dict[str, D] = {}
    for trade in trades:
        by_symbol[trade.symbol] = by_symbol.get(trade.symbol, D("0")) + trade.pnl
    return {
        "variant": name,
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "avg_win": float(round(sum((t.pnl for t in wins), D("0")) / len(wins), 4)) if wins else 0.0,
        "avg_loss": float(round(sum((t.pnl for t in lost), D("0")) / len(lost), 4)) if lost else 0.0,
        "total": float(round(total, 2)),
        "percent_of_account": float(round(total / REPLAY_EQUITY * 100, 2)),
        "days_up": sum(1 for value in by_day.values() if value > 0),
        "by_day": {day: float(round(value, 2)) for day, value in by_day.items()},
        "worst_symbols": [(symbol, float(round(value, 2))) for symbol, value in sorted(by_symbol.items(), key=lambda item: item[1])[:5]],
        "best_symbols": [(symbol, float(round(value, 2))) for symbol, value in sorted(by_symbol.items(), key=lambda item: -item[1])[:5]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", nargs="*", help="YYYYMMDD days to replay (default: every tape in --tape-dir)")
    parser.add_argument("--tape-dir", default=str(storage.APP_DIR / "day-tape"))
    parser.add_argument("--cache", default=str(Path.home() / ".cache" / "apt-tick-replay"))
    parser.add_argument("--account", default="Account 1", help="saved account whose keys and movers settings are used")
    parser.add_argument("--only", nargs="*", help="run only variants whose name starts with one of these letters")
    args = parser.parse_args()

    api_key, secret_key, saved = load_account(args.account)
    if not api_key or not secret_key:
        raise SystemExit("That account has no saved keys.")
    base = saved  # a movers profile of the scored style; each variant sets the settings under test
    market = Market(api_key, secret_key, Path(args.cache))
    tape_dir = Path(args.tape_dir)
    stamps = args.days or sorted(path.stem.split("-")[1] for path in tape_dir.glob("tape-*.jsonl"))
    days = [datetime.strptime(stamp, "%Y%m%d").date() for stamp in stamps]
    variants = [item for item in VARIANTS if not args.only or item[0][:1] in args.only]

    results: dict[str, list[Trade]] = {name: [] for name, _ in variants}
    for day in days:
        started = time.monotonic()
        data = DayData(day, market, tape_dir, base)
        for name, options in variants:
            results[name].extend(replay_day(data, market, base, options))
            market.save_quotes()
        counts = ", ".join(f"{name[:1]}={sum(1 for trade in results[name] if trade.day == day.isoformat())}" for name, _ in variants)
        print(f"{day}: {len(data.symbols)} symbols ({len(data.not_buyable)} not buyable), trades {counts}, {market.requests} requests so far, {time.monotonic() - started:.0f}s", flush=True)

    out_dir = Path(args.cache) / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = [summarize(name, results[name], days) for name, _ in variants]
    (out_dir / "summary.json").write_text(json.dumps(summaries, indent=1))
    with (out_dir / "trades.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["variant", "day", "symbol", "bought_at", "sold_at", "entry", "exit", "qty", "pnl", "reason", "score", "spread_percent"])
        for name, _ in variants:
            for trade in results[name]:
                writer.writerow([name[:1], trade.day, trade.symbol, trade.bought_at, trade.sold_at, trade.entry, trade.exit,
                                 round(trade.qty, 4), round(trade.pnl, 4), trade.reason, trade.score, round(trade.spread_percent, 3)])
    print()
    for summary in summaries:
        print(f"{summary['variant']}\n    trades {summary['trades']}, won {summary['win_rate']}%, avg win ${summary['avg_win']:.3f},"
              f" avg loss ${summary['avg_loss']:.3f}, total ${summary['total']:.2f} ({summary['percent_of_account']:+.2f}% of $1,000),"
              f" days up {summary['days_up']} of {len(days)}")
    print(f"\nDetails: {out_dir / 'summary.json'} and {out_dir / 'trades.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
