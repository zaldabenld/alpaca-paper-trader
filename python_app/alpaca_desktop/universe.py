"""Daily stock list ranked by relative volume ("stocks in play").

Relative volume is today's cumulative volume divided by the symbol's average daily volume over
the prior sessions. Every symbol is ranked at the same moment, so the time-of-day factor that a
"volume so far vs. normal by this time" ratio would apply is the same for all of them and does not
change the order; the plain ratio ranks identically. Both sides come from the same feed (IEX on
the free plan) so a partial feed does not skew one side. Share price is never an input.

The list is picked once a session, PICK_AFTER_OPEN_MINUTES after the open, then rechecked every
RECHECK_SECONDS: symbols newly in the current top PICK_COUNT are added, and nothing is removed
until the next session. This module is pure logic plus the date-stamped file; the TraderManager
owns fetching and sharing the list.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime, timedelta, tzinfo
from pathlib import Path
from typing import Any

PICK_COUNT = 25
MAX_SYMBOLS = 40  # 25 picked plus room for 15 additions; only the top PICK_COUNT are streamed
PICK_AFTER_OPEN_MINUTES = 15
RECHECK_SECONDS = 30 * 60
MIN_SESSIONS = 5
LOOKBACK_SESSIONS = 20
DAILY_BARS_LOOKBACK_DAYS = 45  # calendar days that cover LOOKBACK_SESSIONS plus holidays
MARKET_OPEN_ET = dtime(9, 30)
FILE_VERSION = 1


@dataclass
class DailyUniverse:
    session_date: str
    feed: str
    picked_at: str = ""  # ISO timestamp, US/Eastern
    last_check_at: str = ""
    symbols: list[str] = field(default_factory=list)  # current-rank order; never shrinks intraday
    picked: list[str] = field(default_factory=list)
    added: list[dict[str, str]] = field(default_factory=list)  # {"symbol", "at"}
    ranks: dict[str, dict[str, Any]] = field(default_factory=dict)  # rvol, today_volume, avg_volume, sessions

    def stream_symbols(self) -> list[str]:
        return list(self.symbols[:PICK_COUNT])


def bar_value(bar: Any, name: str) -> Any:
    if isinstance(bar, dict):
        return bar.get(name)
    return getattr(bar, name, None)


def bar_session_date(timestamp: Any, market_tz: tzinfo) -> date | None:
    """Daily bars are stamped at midnight US/Eastern; read the session date in that zone."""
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(timestamp, datetime):
        return None
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(market_tz)
    return timestamp.date()


def pick_time(session: date, market_tz: tzinfo) -> datetime:
    return datetime.combine(session, MARKET_OPEN_ET, tzinfo=market_tz) + timedelta(minutes=PICK_AFTER_OPEN_MINUTES)


def average_daily_volumes(
    bars_by_symbol: dict[str, list[Any]],
    session_date: date,
    market_tz: tzinfo,
    lookback: int = LOOKBACK_SESSIONS,
    min_sessions: int = MIN_SESSIONS,
) -> dict[str, tuple[float, int] | None]:
    """Average volume of the last `lookback` sessions before `session_date`, or None if too few."""
    result: dict[str, tuple[float, int] | None] = {}
    for symbol, bars in bars_by_symbol.items():
        by_date: dict[date, float] = {}
        for bar in bars or []:
            bar_date = bar_session_date(bar_value(bar, "timestamp"), market_tz)
            volume = float(bar_value(bar, "volume") or 0)
            if bar_date is not None and bar_date < session_date:
                by_date[bar_date] = volume
        volumes = [by_date[key] for key in sorted(by_date)][-lookback:]
        if len(volumes) < min_sessions or sum(volumes) <= 0:
            result[str(symbol).upper()] = None
        else:
            result[str(symbol).upper()] = (sum(volumes) / len(volumes), len(volumes))
    return result


def rank_by_rvol(
    today: dict[str, tuple[float, date | None]],
    adv: dict[str, tuple[float, int] | None],
    session_date: date,
) -> list[dict[str, Any]]:
    """Rank symbols by today's volume / average daily volume (highest first).

    `today` maps symbol -> (today's cumulative volume, session date of that daily bar). A daily bar
    from an earlier session means the symbol has not traded on this feed today, so it is skipped.
    """
    rows: list[dict[str, Any]] = []
    for symbol, (volume, bar_date) in today.items():
        average = adv.get(symbol)
        if bar_date != session_date or volume <= 0 or not average:
            continue
        avg_volume, sessions = average
        rows.append(
            {
                "symbol": symbol,
                "rvol": volume / avg_volume,
                "today_volume": volume,
                "avg_volume": avg_volume,
                "sessions": sessions,
            }
        )
    rows.sort(key=lambda row: (-row["rvol"], -row["today_volume"], row["symbol"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def pick_due(universe: DailyUniverse | None, now_et: datetime, is_open: bool) -> bool:
    if not is_open or now_et < pick_time(now_et.date(), now_et.tzinfo or now_et.astimezone().tzinfo):
        return False
    return universe is None or universe.session_date != now_et.date().isoformat()


def recheck_due(universe: DailyUniverse | None, now_et: datetime, is_open: bool) -> bool:
    if not is_open or universe is None or universe.session_date != now_et.date().isoformat():
        return False
    try:
        last_check = datetime.fromisoformat(universe.last_check_at)
    except ValueError:
        return True
    if last_check.tzinfo is None:
        return True
    return (now_et - last_check).total_seconds() >= RECHECK_SECONDS


def rank_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "rvol": round(float(row["rvol"]), 4),
        "today_volume": float(row["today_volume"]),
        "avg_volume": round(float(row["avg_volume"]), 2),
        "sessions": int(row["sessions"]),
    }


def new_universe(ranked: list[dict[str, Any]], now_et: datetime, feed: str) -> DailyUniverse:
    picked = [row["symbol"] for row in ranked[:PICK_COUNT]]
    stamp = now_et.isoformat(timespec="seconds")
    return DailyUniverse(
        session_date=now_et.date().isoformat(),
        feed=feed,
        picked_at=stamp,
        last_check_at=stamp,
        symbols=list(picked),
        picked=list(picked),
        ranks={row["symbol"]: rank_entry(row) for row in ranked if row["symbol"] in picked},
    )


def merge_additions(
    universe: DailyUniverse,
    ranked: list[dict[str, Any]],
    now_et: datetime,
    max_symbols: int = MAX_SYMBOLS,
) -> list[str]:
    """Add symbols newly in the current top PICK_COUNT; never remove any. Returns the symbols added.

    The order stays picked-then-added, so the streamed first PICK_COUNT (the 9:45 pick) is stable all
    day: rank shuffles never force a websocket reconnect. Additions are scanned through REST bars.
    """
    members = set(universe.symbols)
    added: list[str] = []
    for row in ranked[:PICK_COUNT]:
        symbol = row["symbol"]
        if symbol in members or len(members) >= max_symbols:
            continue
        members.add(symbol)
        added.append(symbol)
    stamp = now_et.isoformat(timespec="seconds")
    universe.added.extend({"symbol": symbol, "at": stamp} for symbol in added)
    current = {row["symbol"]: row for row in ranked}
    for symbol in members:
        if symbol in current:
            universe.ranks[symbol] = rank_entry(current[symbol])
    universe.symbols = universe.symbols + added
    universe.last_check_at = stamp
    return added


def universe_payload(universe: DailyUniverse) -> dict[str, Any]:
    return {"version": FILE_VERSION, **asdict(universe)}


def load_daily_universe(path: Path, session_date: str, feed: str) -> DailyUniverse | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != FILE_VERSION:
        return None
    if raw.get("session_date") != session_date or raw.get("feed") != feed:
        return None
    try:
        universe = DailyUniverse(
            session_date=str(raw["session_date"]),
            feed=str(raw["feed"]),
            picked_at=str(raw.get("picked_at") or ""),
            last_check_at=str(raw.get("last_check_at") or ""),
            symbols=[str(symbol).upper() for symbol in raw.get("symbols") or []],
            picked=[str(symbol).upper() for symbol in raw.get("picked") or []],
            added=[dict(item) for item in raw.get("added") or [] if isinstance(item, dict)],
            ranks={str(key).upper(): dict(value) for key, value in (raw.get("ranks") or {}).items() if isinstance(value, dict)},
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return universe if universe.symbols else None
