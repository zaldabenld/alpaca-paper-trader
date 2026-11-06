"""Daily stock list ranked by relative volume ("stocks in play").

Relative volume is today's cumulative volume divided by the symbol's average daily volume over
the prior sessions. Every symbol is ranked at the same moment, so the time-of-day factor that a
"volume so far vs. normal by this time" ratio would apply is the same for all of them and does not
change the order; the plain ratio ranks identically. Both sides come from the same feed (IEX on
the free plan) so a partial feed does not skew one side. Share price is never an input.

The list is picked once a session, PICK_AFTER_OPEN_MINUTES after the open, then rechecked every
RECHECK_SECONDS: symbols newly in the current top PICK_COUNT are added, and nothing is removed
until the next session. (Those are the defaults; the timing and lookback are app-wide settings,
snapshotted into the day's `params` at the pick.) This module is pure logic plus the date-stamped
file; the TraderManager owns fetching and sharing the list.

Every check's full ranking is kept, so each account can take its own list size from the same
rankings: `list_for(pick_count, max_symbols)` replays the pick and the additions for that size.
The top-level `symbols`/`picked`/`added` hold the default (PICK_COUNT, MAX_SYMBOLS) list, so a file
written here still loads in older builds.
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


def default_list_params() -> dict[str, int]:
    return {
        "pick_minutes_after_open": PICK_AFTER_OPEN_MINUTES,
        "recheck_seconds": RECHECK_SECONDS,
        "lookback_sessions": LOOKBACK_SESSIONS,
        "min_sessions": MIN_SESSIONS,
    }


def daily_bars_lookback_days(lookback_sessions: int) -> int:
    # Calendar days that cover the sessions plus weekends and holidays (20 sessions -> 45 days).
    return int(lookback_sessions) * 3 // 2 + 15


def replay_list(rankings: list[dict[str, Any]], pick_count: int, max_symbols: int) -> list[str]:
    """The list one account gets: the first ranking's top `pick_count`, then each later ranking's
    top `pick_count` symbols not already in it, up to `max_symbols`. Nothing is ever removed."""
    if not rankings:
        return []
    cap = max(int(max_symbols), int(pick_count))
    members = list(rankings[0].get("symbols", [])[:pick_count])
    seen = set(members)
    for ranking in rankings[1:]:
        for symbol in ranking.get("symbols", [])[:pick_count]:
            if symbol in seen or len(members) >= cap:
                continue
            seen.add(symbol)
            members.append(symbol)
    return members


def legacy_rankings(picked: list[str], added: list[dict[str, str]], picked_at: str) -> list[dict[str, Any]]:
    # Files written before rankings were kept: the pick, then one ranking per addition time. Replaying
    # them at the default size reproduces the stored list exactly; other sizes are approximate that day.
    rankings: list[dict[str, Any]] = [{"at": picked_at, "symbols": list(picked)}]
    for item in added:
        symbol = str(item.get("symbol") or "").upper()
        at = str(item.get("at") or "")
        if not symbol:
            continue
        if rankings[-1]["at"] != at or len(rankings) == 1:
            rankings.append({"at": at, "symbols": []})
        rankings[-1]["symbols"].append(symbol)
    return rankings


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
    rankings: list[dict[str, Any]] = field(default_factory=list)  # {"at", "symbols": every ranked symbol, best first}
    params: dict[str, int] = field(default_factory=default_list_params)  # app-wide list settings at the pick

    def list_for(self, pick_count: int = PICK_COUNT, max_symbols: int = MAX_SYMBOLS) -> list[str]:
        if not self.rankings:
            return list(self.symbols)
        return replay_list(self.rankings, pick_count, max_symbols)

    def picked_for(self, pick_count: int = PICK_COUNT) -> list[str]:
        if not self.rankings:
            return list(self.picked[:pick_count])
        return list(self.rankings[0].get("symbols", [])[:pick_count])

    def stream_symbols(self, pick_count: int = PICK_COUNT) -> list[str]:
        # The pick is fixed all day, so streaming it never forces a websocket reconnect.
        if not self.rankings:
            return list(self.symbols[:pick_count])
        return self.picked_for(pick_count)

    def recheck_seconds(self) -> int:
        return int(self.params.get("recheck_seconds") or RECHECK_SECONDS)


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


def pick_time(session: date, market_tz: tzinfo, minutes_after_open: int = PICK_AFTER_OPEN_MINUTES) -> datetime:
    return datetime.combine(session, MARKET_OPEN_ET, tzinfo=market_tz) + timedelta(minutes=minutes_after_open)


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


def pick_due(
    universe: DailyUniverse | None,
    now_et: datetime,
    is_open: bool,
    minutes_after_open: int = PICK_AFTER_OPEN_MINUTES,
) -> bool:
    market_tz = now_et.tzinfo or now_et.astimezone().tzinfo
    if not is_open or now_et < pick_time(now_et.date(), market_tz, minutes_after_open):
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
    return (now_et - last_check).total_seconds() >= universe.recheck_seconds()


def rank_entry(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": row["rank"],
        "rvol": round(float(row["rvol"]), 4),
        "today_volume": float(row["today_volume"]),
        "avg_volume": round(float(row["avg_volume"]), 2),
        "sessions": int(row["sessions"]),
    }


def new_universe(
    ranked: list[dict[str, Any]],
    now_et: datetime,
    feed: str,
    params: dict[str, int] | None = None,
) -> DailyUniverse:
    picked = [row["symbol"] for row in ranked[:PICK_COUNT]]
    stamp = now_et.isoformat(timespec="seconds")
    return DailyUniverse(
        session_date=now_et.date().isoformat(),
        feed=feed,
        picked_at=stamp,
        last_check_at=stamp,
        symbols=list(picked),
        picked=list(picked),
        ranks={row["symbol"]: rank_entry(row) for row in ranked},
        rankings=[{"at": stamp, "symbols": [row["symbol"] for row in ranked]}],
        params=dict(params or default_list_params()),
    )


def merge_additions(universe: DailyUniverse, ranked: list[dict[str, Any]], now_et: datetime) -> list[str]:
    """Record this check's ranking; returns the symbols it adds to the default-size list.

    Each list keeps its picked-then-added order, so the streamed pick is stable all day: rank
    shuffles never force a websocket reconnect. Additions are scanned through REST bars.
    """
    stamp = now_et.isoformat(timespec="seconds")
    if not universe.rankings:
        universe.rankings = legacy_rankings(universe.picked, universe.added, universe.picked_at)
    universe.rankings.append({"at": stamp, "symbols": [row["symbol"] for row in ranked]})
    before = set(universe.symbols)
    universe.symbols = universe.list_for()
    universe.picked = universe.picked_for()
    added = [symbol for symbol in universe.symbols if symbol not in before]
    universe.added.extend({"symbol": symbol, "at": stamp} for symbol in added)
    for row in ranked:
        universe.ranks[row["symbol"]] = rank_entry(row)
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
            params=default_list_params() | {
                str(key): int(value) for key, value in (raw.get("params") or {}).items() if str(key) in default_list_params()
            },
        )
        if "rankings" in raw:
            universe.rankings = [
                {"at": str(item.get("at") or ""), "symbols": [str(symbol).upper() for symbol in item.get("symbols") or []]}
                for item in raw.get("rankings") or []
                if isinstance(item, dict)
            ]
        else:
            universe.rankings = legacy_rankings(universe.picked, universe.added, universe.picked_at)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return universe if universe.symbols else None
