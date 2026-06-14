from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader"
DAY_TAPE_DIR = APP_DATA_DIR / "day-tape"
DAY_TAPE_LOCK = threading.RLock()
DEFAULT_RETENTION_DAYS = 14
SENSITIVE_KEYS = {
    "account_id",
    "account_number",
    "api_key",
    "authorization",
    "headers",
    "order_id",
    "password",
    "secret",
    "secret_key",
    "token",
}

ACCOUNT_FIELDS = (
    "cash",
    "buying_power",
    "equity",
    "last_equity",
    "multiplier",
    "daytrade_count",
    "pattern_day_trader",
    "trading_blocked",
    "transfers_blocked",
    "account_blocked",
)
POSITION_FIELDS = (
    "symbol",
    "asset_class",
    "qty",
    "side",
    "avg_entry_price",
    "market_value",
    "cost_basis",
    "current_price",
    "lastday_price",
    "change_today",
    "unrealized_pl",
    "unrealized_plpc",
    "unrealized_intraday_pl",
    "unrealized_intraday_plpc",
)
ORDER_FIELDS = (
    "symbol",
    "asset_class",
    "side",
    "type",
    "status",
    "order_class",
    "time_in_force",
    "qty",
    "filled_qty",
    "notional",
    "limit_price",
    "stop_price",
    "trail_price",
    "trail_percent",
    "hwm",
    "submitted_at",
    "filled_at",
    "canceled_at",
    "expired_at",
    "failed_at",
    "replaced_at",
    "updated_at",
    "client_order_id",
)
QUOTE_FIELDS = (
    "symbol",
    "bid_price",
    "bid_size",
    "bid_exchange",
    "ask_price",
    "ask_size",
    "ask_exchange",
    "timestamp",
    "conditions",
    "tape",
)
TRADE_FIELDS = (
    "symbol",
    "price",
    "size",
    "timestamp",
    "exchange",
    "conditions",
    "tape",
)
STATUS_FIELDS = (
    "symbol",
    "status_code",
    "status_message",
    "reason_code",
    "reason_message",
    "timestamp",
)
TOP_VOLUME_ROW_FIELDS = (
    "rank",
    "rank_raw",
    "symbol",
    "total_volume",
    "total_volume_raw",
    "daily_volume",
    "daily_volume_raw",
    "trade_count",
    "trade_count_raw",
    "buy_volume",
    "buy_volume_raw",
    "sell_volume",
    "sell_volume_raw",
    "unclassified_volume",
    "unclassified_volume_raw",
    "stream_volume",
    "stream_volume_raw",
    "last_trade_side",
    "last_price",
    "last_price_raw",
    "minute_volume",
    "minute_volume_raw",
    "last_update",
    "trading_status",
    "halted",
    "halted_raw",
    "halt_reason",
)
ORDER_INTENT_FIELDS = (
    "time",
    "symbol",
    "side",
    "qty",
    "role",
    "status",
    "client_order_id",
    "reason",
)

_SEEN_BAR_KEYS: set[str] = set()
_LAST_PRUNE_DAY: date | None = None


def day_tape_enabled() -> bool:
    return os.environ.get("ALPACA_TRADER_DISABLE_DAY_TAPE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }


def retention_days() -> int:
    raw = os.environ.get("ALPACA_TRADER_DAY_TAPE_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def day_tape_file_path(day: date | None = None) -> Path:
    target = day or datetime.now().date()
    return DAY_TAPE_DIR / f"tape-{target.strftime('%Y%m%d')}.jsonl"


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def append_day_tape_event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "time_display": datetime.now().strftime("%H:%M:%S"),
        "kind": kind,
        "payload": clean_payload(payload),
    }
    if not day_tape_enabled():
        return event
    try:
        with DAY_TAPE_LOCK:
            DAY_TAPE_DIR.mkdir(parents=True, exist_ok=True)
            prune_old_day_tapes_locked()
            with day_tape_file_path().open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, default=json_default, separators=(",", ":")) + "\n")
    except Exception as exc:
        event["write_error"] = str(exc)
    return event


def prune_old_day_tapes_locked() -> None:
    global _LAST_PRUNE_DAY
    today = datetime.now().date()
    if _LAST_PRUNE_DAY == today:
        return
    _LAST_PRUNE_DAY = today
    cutoff = today - timedelta(days=max(0, retention_days() - 1))
    for path in DAY_TAPE_DIR.glob("tape-*.jsonl"):
        try:
            stamp = path.stem.replace("tape-", "")
            file_day = datetime.strptime(stamp, "%Y%m%d").date()
        except ValueError:
            continue
        if file_day < cutoff:
            try:
                path.unlink()
            except OSError:
                pass


def clean_payload(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): clean_payload(item)
            for key, item in value.items()
            if str(key).strip().lower() not in SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [clean_payload(item) for item in value]
    return value


def model_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return dict(getattr(value, "__dict__", {}))


def pick_fields(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        field: clean_payload(source.get(field))
        for field in fields
        if field in source and source.get(field) not in (None, "")
    }


def compact_account_snapshot(account: dict[str, Any]) -> dict[str, Any]:
    return pick_fields(account, ACCOUNT_FIELDS)


def compact_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pick_fields(item, POSITION_FIELDS) for item in positions]


def compact_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pick_fields(item, ORDER_FIELDS) for item in orders]


def compact_quote_payload(quote: Any, feed: str = "", source: str = "") -> dict[str, Any]:
    raw = model_payload(quote)
    payload = pick_fields(raw, QUOTE_FIELDS)
    payload["symbol"] = str(payload.get("symbol", "")).upper()
    payload["feed"] = feed
    payload["source"] = source
    return payload


def compact_trade_payload(trade: Any, feed: str = "", source: str = "") -> dict[str, Any]:
    raw = model_payload(trade)
    payload = pick_fields(raw, TRADE_FIELDS)
    payload["symbol"] = str(payload.get("symbol", "")).upper()
    payload["feed"] = feed
    payload["source"] = source
    return payload


def compact_status_payload(status: Any, feed: str = "", source: str = "", detail: str = "") -> dict[str, Any]:
    raw = model_payload(status)
    payload = pick_fields(raw, STATUS_FIELDS)
    payload["symbol"] = str(payload.get("symbol", "")).upper()
    payload["feed"] = feed
    payload["source"] = source
    if detail:
        payload["detail"] = detail
    return payload


def compact_top_volume_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pick_fields(item, TOP_VOLUME_ROW_FIELDS) for item in rows]


def compact_order_intent(event: dict[str, Any]) -> dict[str, Any]:
    return pick_fields(event, ORDER_INTENT_FIELDS)


def compact_bar_payload(bar: Any, feed: str = "", source: str = "", daily: bool = False) -> dict[str, Any]:
    raw = model_payload(bar)
    return {
        "symbol": str(raw.get("symbol", "")).upper(),
        "timestamp": clean_payload(raw.get("timestamp")),
        "open": clean_payload(raw.get("open")),
        "high": clean_payload(raw.get("high")),
        "low": clean_payload(raw.get("low")),
        "close": clean_payload(raw.get("close")),
        "volume": clean_payload(raw.get("volume")),
        "trade_count": clean_payload(raw.get("trade_count")),
        "vwap": clean_payload(raw.get("vwap")),
        "feed": feed,
        "source": source,
        "daily": daily,
    }


def append_market_bar_once(bar: Any, feed: str = "", source: str = "", daily: bool = False) -> bool:
    payload = compact_bar_payload(bar, feed=feed, source=source, daily=daily)
    symbol = str(payload.get("symbol") or "").upper()
    timestamp = str(payload.get("timestamp") or "")
    if not symbol or not timestamp:
        return False
    key = f"{symbol}|{timestamp}|{payload.get('daily')}|{feed}"
    with DAY_TAPE_LOCK:
        if key in _SEEN_BAR_KEYS:
            return False
        _SEEN_BAR_KEYS.add(key)
        if len(_SEEN_BAR_KEYS) > 200_000:
            _SEEN_BAR_KEYS.clear()
            _SEEN_BAR_KEYS.add(key)
    append_day_tape_event("market_bar", payload)
    return True


def append_market_quote(quote: Any, feed: str = "", source: str = "") -> bool:
    payload = compact_quote_payload(quote, feed=feed, source=source)
    if not payload.get("symbol"):
        return False
    append_day_tape_event("market_quote", payload)
    return True


def append_market_trade(trade: Any, feed: str = "", source: str = "") -> bool:
    payload = compact_trade_payload(trade, feed=feed, source=source)
    if not payload.get("symbol"):
        return False
    append_day_tape_event("market_trade", payload)
    return True


def append_market_status(status: Any, feed: str = "", source: str = "", detail: str = "") -> bool:
    payload = compact_status_payload(status, feed=feed, source=source, detail=detail)
    if not payload.get("symbol"):
        return False
    append_day_tape_event("market_status", payload)
    return True
