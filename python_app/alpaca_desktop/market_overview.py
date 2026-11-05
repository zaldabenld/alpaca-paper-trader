"""Dashboard market overview: index ETF charts, a top-movers ticker tape, and news headlines.

Alpaca's free data has no true index quotes, so the index box charts the ETFs that track them.
Movers come from the most-active rows the dashboard already loads (no extra API calls); the
index ETFs are left out of the tape because they have their own box. This module is pure logic;
the TraderManager owns fetching and caching.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timezone, tzinfo
from typing import Any

INDEX_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("DIA", "Dow 30"),
    ("IWM", "Russell 2000"),
)
INDEX_SYMBOL_SET = {symbol for symbol, _ in INDEX_SYMBOLS}
CHART_BAR_MINUTES = 5
MOVER_COUNT = 10
NEWS_LIMIT = 12
NEWS_SYMBOL_LIMIT = 40
SESSION_OPEN_ET = dtime(9, 30)
SESSION_CLOSE_ET = dtime(16, 0)


def field(item: Any, name: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # drop NaN


def percent_change(price: float | None, previous: float | None) -> float | None:
    if price is None or previous is None or previous <= 0:
        return None
    return (price / previous - 1) * 100


def as_utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def snapshot_session_date(snapshot: Any, market_tz: tzinfo) -> date | None:
    """The session the snapshot's daily bar belongs to (bars are stamped at midnight US/Eastern)."""
    stamp = as_utc(field(field(snapshot, "daily_bar"), "timestamp"))
    return stamp.astimezone(market_tz).date() if stamp else None


def session_window(session: date, market_tz: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(session, SESSION_OPEN_ET, tzinfo=market_tz)
    end = datetime.combine(session, SESSION_CLOSE_ET, tzinfo=market_tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def snapshot_price(snapshot: Any) -> float | None:
    price = number(field(field(snapshot, "latest_trade"), "price"))
    if price is None or price <= 0:
        price = number(field(field(snapshot, "daily_bar"), "close"))
    return price if price and price > 0 else None


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def index_cards(
    snapshots: dict[str, Any], bars: dict[str, list[Any]], session: date | None, market_tz: tzinfo
) -> list[dict[str, Any]]:
    window = session_window(session, market_tz) if session else None
    cards = []
    for symbol, name in INDEX_SYMBOLS:
        snapshot = snapshots.get(symbol)
        price = snapshot_price(snapshot)
        previous = number(field(field(snapshot, "previous_daily_bar"), "close"))
        change = price - previous if price is not None and previous else None
        points = []
        for bar in bars.get(symbol, []):
            stamp = as_utc(field(bar, "timestamp"))
            close = number(field(bar, "close"))
            if stamp and close:
                points.append({"t": iso_z(stamp), "c": close})
        cards.append(
            {
                "symbol": symbol,
                "name": name,
                "price": price,
                "previous_close": previous,
                "change": change,
                "change_pct": percent_change(price, previous),
                "session_date": session.isoformat() if session else "",
                "session_start": iso_z(window[0]) if window else "",
                "session_end": iso_z(window[1]) if window else "",
                "points": points,
            }
        )
    return cards


def top_movers(rows: list[dict[str, Any]], count: int = MOVER_COUNT) -> dict[str, list[dict[str, Any]]]:
    priced = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        pct = number(row.get("change_pct_raw"))
        price = number(row.get("last_price_raw"))
        if not symbol or symbol in INDEX_SYMBOL_SET or pct is None or not price:
            continue
        priced.append({"symbol": symbol, "price": price, "change_pct": pct})
    gainers = sorted((item for item in priced if item["change_pct"] > 0), key=lambda item: -item["change_pct"])
    losers = sorted((item for item in priced if item["change_pct"] < 0), key=lambda item: item["change_pct"])
    return {"gainers": gainers[:count], "losers": losers[:count]}


def news_symbols(held: list[str], watched: list[str]) -> list[str]:
    ordered = [symbol for symbol, _ in INDEX_SYMBOLS] + list(held) + list(watched)
    clean = []
    for symbol in ordered:
        value = str(symbol or "").strip().upper()
        # Skip placeholders like 046CVR015: tickers start with a letter.
        if value and value[0].isalpha() and value not in clean:
            clean.append(value)
    return clean[:NEWS_SYMBOL_LIMIT]


def news_items(news_set: Any, limit: int = NEWS_LIMIT) -> list[dict[str, Any]]:
    data = field(news_set, "data")
    articles = (data.get("news") if isinstance(data, dict) else None) or (news_set if isinstance(news_set, list) else [])
    items = []
    for article in articles[:limit]:
        headline = str(field(article, "headline") or "").strip()
        if not headline:
            continue
        created = as_utc(field(article, "created_at"))
        items.append(
            {
                "id": str(field(article, "id") or headline),
                "headline": headline,
                "source": str(field(article, "source") or ""),
                "url": str(field(article, "url") or ""),
                "symbols": [str(symbol).upper() for symbol in (field(article, "symbols") or [])][:6],
                "created_at": iso_z(created) if created else "",
            }
        )
    return items
