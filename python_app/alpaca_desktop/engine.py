from __future__ import annotations

import dataclasses
import json
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alpaca.common.enums import Sort
from alpaca.common.exceptions import APIError
from alpaca.data.enums import Adjustment, DataFeed, MostActivesBy
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import (
    MostActivesRequest,
    NewsRequest,
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockSnapshotRequest,
    StockTradesRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetCalendarRequest,
    GetPortfolioHistoryRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
)
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from .backtester import (
    EngineBacktesterBoundary,
    LiveAccountStateBoundary,
    LiveClockBoundary,
    LiveMarketDataBoundary,
    LiveOrderExecutionBoundary,
    LiveReplayBoundary,
    LiveStrategyBoundary,
)
from .day_tape import (
    DAY_TAPE_DIR,
    append_day_tape_event,
    append_market_bar_once,
    append_market_quote,
    append_market_status,
    append_market_trade,
    clean_payload as clean_day_tape_value,
    compact_account_snapshot,
    compact_order_intent,
    compact_orders,
    compact_positions,
    compact_top_volume_rows,
    day_tape_file_path,
)
from .alerts import NOTIFIER
from .heartbeat import TradingHaltedError, trading_halted
from .runtime_diagnostics import (
    AccountRefreshError,
    CachePersistenceError,
    MarketDataError,
    OrderExecutionError,
    ReplayPersistenceError,
    StreamControlError,
    clear_runtime_diagnostics,
    record_runtime_diagnostic,
    runtime_diagnostics_snapshot,
)
from .storage import APP_DIR, write_private_json
from .strategy import StrategyState, clean_symbols, decimal_value, money, number, order_quantity
from .strategy import _bar_local_time, _latest_session_points
from . import allocation as allocation_logic
from . import inplay as inplay_logic
from . import movers as movers_logic
from . import app_settings
from . import market_overview
from . import symbol_info as symbol_info_logic
from . import universe as rvol_universe


CONFIG_VERSION = 2  # 2: "momentum" and "movers" became profiles of the scored style
MOST_ACTIVES_MAX = 100  # Alpaca screener maximum for `top`
DAILY_LIST_MAX = 100


def configured_top_symbol_count() -> int:
    # How many of Alpaca's most-active stocks to scan; ALPACA_TRADER_TOP_SYMBOLS overrides.
    try:
        count = int(os.environ.get("ALPACA_TRADER_TOP_SYMBOLS", str(MOST_ACTIVES_MAX)))
    except ValueError:
        count = MOST_ACTIVES_MAX
    return max(1, min(MOST_ACTIVES_MAX, count))


DASHBOARD_TOP_LIMIT = configured_top_symbol_count()
STOCK_SNAPSHOT_BATCH_SIZE = 100
STOCK_SNAPSHOT_SINGLE_RETRY_LIMIT = 30
TOP_VOLUME_CACHE_SECONDS = 60
PORTFOLIO_HISTORY_CACHE_SECONDS = 15
TOP_VOLUME_FORCE_COOLDOWN_SECONDS = 30
TOP_VOLUME_SOURCE = "alpaca_most_actives_volume"
LOOKUP_CACHE_SECONDS = 60
BUILT_IN_PROFILE_KEYS = ("conservative", "neutral", "aggressive")
REPLAY_EVENT_LIMIT = 400
# Minute bars change once a minute and streamed symbols get live bars, so a 15 s cache keeps a
# 100-symbol REST scan well under the free plan's 200 data requests per minute.
HISTORICAL_BARS_CACHE_SECONDS = 15
DAY_TAPE_SCAN_INTERVAL_SECONDS = 60
HISTORICAL_BARS_PER_SYMBOL = 500
HISTORICAL_BARS_REQUEST_LIMIT = 10000
MARKET_STREAM_SYMBOL_LIMIT = app_settings.DEFAULT_MARKET_STREAM_SYMBOL_LIMIT
INVALID_SYMBOL_PATTERN = re.compile(r"invalid symbol:\s*([A-Za-z0-9.\-/]+)")
# Symbols the market-data API rejects (e.g. CVR rights like 046CVR015 left in a paper
# account by a corporate action). One of them fails a whole multi-symbol request, so
# they are dropped from data requests and stream subscriptions for the process lifetime.
INVALID_MARKET_DATA_SYMBOLS: set[str] = set()
INVALID_MARKET_DATA_SYMBOLS_LOCK = threading.Lock()
try:
    MARKET_TIMEZONE: tzinfo = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:  # Windows without tzdata; EST is close enough for a day key
    MARKET_TIMEZONE = timezone(timedelta(hours=-5))
MARKET_STREAM_CONNECTION_LIMIT_RETRY_SECONDS = 120
MIN_EXIT_PRICE_OFFSET = Decimal("0.01")
PRICE_INCREMENT = Decimal("0.01")
SUB_DOLLAR_PRICE_INCREMENT = Decimal("0.0001")
MIN_ENTRY_NOTIONAL = Decimal("1.00")
INPLAY_DEFAULT_FLATTEN_MINUTES = 10
INPLAY_FALLBACK_STOP_PERCENT = Decimal("5")
TRADE_SIZE_MODES = {"percent", "notional", "exposure_slot"}
MAX_ENTRY_REFERENCE_PREMIUM_PERCENT = Decimal("2.0")
TRADE_HISTORY_DISPLAY_ROWS = 100
DAY_FILLS_PAGE_SIZE = 500
DAY_FILLS_MAX_PAGES = 10
DAY_FILLS_RETRY_SECONDS = 60
ASSET_CHECK_CACHE_SECONDS = 6 * 60 * 60
ORDER_FLOW_MIN_CLASSIFIED_VOLUME = Decimal("1000")
ORDER_SUBMIT_HOLD_SECONDS = 2 * 60
ORDER_REJECT_HOLD_SECONDS = 30 * 60
PROTECTIVE_ORDER_REJECT_HOLD_SECONDS = 5 * 60
STOP_LOSS_EXIT_REJECT_HOLD_SECONDS = 60  # a rejected stop-loss sell retries quickly, not after 30 min
NON_FRACTIONABLE_HOLD_SECONDS = 6 * 60 * 60
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader"
DAILY_UNIVERSE_PATH = APP_DATA_DIR / "daily-universe.json"
DAILY_UNIVERSE_RETRY_SECONDS = 60
MARKET_OVERVIEW_CACHE_SECONDS = 60
REPLAY_DIR = APP_DATA_DIR / "replay"
REPLAY_LOCK = threading.RLock()
DASHBOARD_CACHE_PATH = APP_DATA_DIR / "dashboard-cache.json"
DASHBOARD_CACHE_LOCK = threading.RLock()
DASHBOARD_CACHE_FIELDS = (
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
)

HALT_KEYWORDS = (
    "halt",
    "suspend",
    "suspension",
    "pause",
    "luld",
    "limit up",
    "limit down",
    "volatility",
    "news pending",
    "order imbalance",
    "mwcb",
)
RESUME_KEYWORDS = ("resume", "resumed", "resumption")

INVERSE_ETF_SYMBOLS = {
    "DOG",
    "PSQ",
    "QID",
    "REK",
    "RWM",
    "SBB",
    "SDD",
    "SDS",
    "SH",
    "SPDN",
    "SPXU",
    "SQQQ",
    "TBF",
    "TBT",
    "TZA",
    "YANG",
    "SOXS",
    "SARK",
}

MARKET_PROXY_SYMBOLS = ("SPY", "QQQ")
TOP_VOLUME_INVERSE_ETF_SYMBOLS = ("SQQQ", "SPXU", "SDS", "SH", "TZA")

LEVERAGED_OR_VOLATILITY_ETP_SYMBOLS = {
    "BOIL",
    "BULZ",
    "FNGU",
    "FNGD",
    "LABD",
    "LABU",
    "MSTU",
    "MSTX",
    "MSTZ",
    "NVD",
    "NVDL",
    "NVDS",
    "SOXL",
    "SOXS",
    "SPXL",
    "SPXS",
    "TECL",
    "TECS",
    "TQQQ",
    "TSLL",
    "TSLS",
    "TZA",
    "UDOW",
    "UPRO",
    "UVIX",
    "UVXY",
    "VIXY",
    "YINN",
    "YANG",
}

ENTRY_PROFILE_LIMITS: dict[str, dict[str, Decimal]] = {
    "conservative": {
        "min_price": Decimal("5"),
        "min_recent_momentum": Decimal("0.08"),
        "min_long_momentum": Decimal("0.12"),
        "min_session_change": Decimal("0.05"),
        "min_vwap_distance": Decimal("0.05"),
        "max_vwap_extension": Decimal("2.25"),
        "max_session_extension": Decimal("6.0"),
        "max_session_pullback": Decimal("0.75"),
        "max_recent_pullback": Decimal("0.50"),
        "late_momentum_floor": Decimal("0"),
    },
    "neutral": {
        "min_price": Decimal("3"),
        "min_recent_momentum": Decimal("0.08"),
        "min_long_momentum": Decimal("0.12"),
        "min_session_change": Decimal("0.05"),
        "min_vwap_distance": Decimal("0.05"),
        "max_vwap_extension": Decimal("2.25"),
        "max_session_extension": Decimal("8.0"),
        "max_session_pullback": Decimal("0.75"),
        "max_recent_pullback": Decimal("0.50"),
        "late_momentum_floor": Decimal("0"),
    },
    "aggressive": {
        "min_price": Decimal("2"),
        "min_recent_momentum": Decimal("0.08"),
        "min_long_momentum": Decimal("0.12"),
        "min_session_change": Decimal("0.05"),
        "min_vwap_distance": Decimal("0.05"),
        "max_vwap_extension": Decimal("2.25"),
        "max_session_extension": Decimal("10.0"),
        "max_session_pullback": Decimal("0.75"),
        "max_recent_pullback": Decimal("0.50"),
        "late_momentum_floor": Decimal("0"),
    },
}


PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "conservative": {
        "profile": "conservative",
        "symbols": ["SPY", "QQQ"],
        "use_top_volume_symbols": True,
        "feed": "iex",
        "poll_seconds": 5,
        "dry_run": True,
        "market_hours_only": True,
        "use_market_stream": True,
        "use_bracket_orders": True,
        "trade_size_mode": "percent",
        "max_trade_notional": "0",
        "max_trade_percent": "4.0",
        "max_position_notional": "20",
        "max_position_percent": "4.0",
        "daily_loss_limit": "0",
        "daily_loss_limit_percent": "0",
        "risk_per_trade_percent": "0",
        "max_total_exposure_percent": "12",
        "max_open_positions": 2,
        "short_period": 9,
        "long_period": 21,
        "rsi_period": 14,
        "buy_rsi_min": "42",
        "buy_rsi_max": "65",
        "sell_rsi": "70",
        "min_entry_score": "20",
        "momentum_period": 6,
        "min_momentum_percent": "0.15",
        "min_recent_momentum_percent": "0.08",
        "min_long_momentum_percent": "0.12",
        "min_session_change_percent": "0.05",
        "min_vwap_distance_percent": "0.05",
        "max_vwap_distance_percent": "2.25",
        "max_session_pullback_percent": "0.75",
        "max_recent_pullback_percent": "0.50",
        "late_momentum_floor_percent": "0",
        "min_session_pullback_percent": "0",
        "max_entry_rsi": "0",
        "max_entries_per_symbol_per_day": 0,
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
        "inverse_trend_hold": False,
        "inverse_trend_exit_percent": "0",
        "inverse_trend_stop_percent": "3",
        "inverse_trend_lock_at_percent": "3",
        "inverse_trend_trail_percent": "2",
        "inverse_trend_max_entries": 2,
        "universe_mode": "most_active",
        "entry_mode": "scored",
        "orb_minutes": 15,
        "orb_max_breakout_percent": "1.0",
        "volume_period": 20,
        "volume_multiplier": "1.0",
        "min_avg_volume": "0",
        "take_profit_percent": "2.5",
        "profit_trail_start_percent": "0",
        "profit_trail_drop_percent": "0",
        "stop_loss_percent": "1.25",
        "stop_loss_grace_minutes": 0,
        "exit_time_in_force": "day",
        "cooldown_minutes": 0,
        "entry_open_guard_minutes": 15,
        "entry_close_guard_minutes": 15,
    },
    "neutral": {
        "profile": "neutral",
        "symbols": ["SPY", "QQQ"],
        "use_top_volume_symbols": True,
        "feed": "iex",
        "poll_seconds": 5,
        "dry_run": True,
        "market_hours_only": True,
        "use_market_stream": True,
        "use_bracket_orders": True,
        "trade_size_mode": "percent",
        "max_trade_notional": "0",
        "max_trade_percent": "7.0",
        "max_position_notional": "35",
        "max_position_percent": "7.0",
        "daily_loss_limit": "0",
        "daily_loss_limit_percent": "0",
        "risk_per_trade_percent": "0",
        "max_total_exposure_percent": "25",
        "max_open_positions": 3,
        "short_period": 9,
        "long_period": 21,
        "rsi_period": 14,
        "buy_rsi_min": "42",
        "buy_rsi_max": "65",
        "sell_rsi": "72",
        "min_entry_score": "20",
        "momentum_period": 6,
        "min_momentum_percent": "0.15",
        "min_recent_momentum_percent": "0.08",
        "min_long_momentum_percent": "0.12",
        "min_session_change_percent": "0.05",
        "min_vwap_distance_percent": "0.05",
        "max_vwap_distance_percent": "2.25",
        "max_session_pullback_percent": "0.75",
        "max_recent_pullback_percent": "0.50",
        "late_momentum_floor_percent": "0",
        "min_session_pullback_percent": "0",
        "max_entry_rsi": "0",
        "max_entries_per_symbol_per_day": 0,
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
        "inverse_trend_hold": False,
        "inverse_trend_exit_percent": "0",
        "inverse_trend_stop_percent": "3",
        "inverse_trend_lock_at_percent": "3",
        "inverse_trend_trail_percent": "2",
        "inverse_trend_max_entries": 2,
        "universe_mode": "most_active",
        "entry_mode": "scored",
        "orb_minutes": 15,
        "orb_max_breakout_percent": "1.0",
        "volume_period": 20,
        "volume_multiplier": "1.0",
        "min_avg_volume": "0",
        "take_profit_percent": "2.5",
        "profit_trail_start_percent": "0",
        "profit_trail_drop_percent": "0",
        "stop_loss_percent": "1.25",
        "stop_loss_grace_minutes": 0,
        "exit_time_in_force": "day",
        "cooldown_minutes": 0,
        "entry_open_guard_minutes": 15,
        "entry_close_guard_minutes": 15,
    },
    "aggressive": {
        "profile": "aggressive",
        "symbols": ["SPY", "QQQ", "IWM"],
        "use_top_volume_symbols": True,
        "feed": "iex",
        "poll_seconds": 5,
        "dry_run": True,
        "market_hours_only": True,
        "use_market_stream": True,
        "use_bracket_orders": True,
        "trade_size_mode": "percent",
        "max_trade_notional": "0",
        "max_trade_percent": "10.0",
        "max_position_notional": "50",
        "max_position_percent": "10.0",
        "daily_loss_limit": "0",
        "daily_loss_limit_percent": "0",
        "risk_per_trade_percent": "0",
        "max_total_exposure_percent": "50",
        "max_open_positions": 5,
        "short_period": 9,
        "long_period": 21,
        "rsi_period": 14,
        "buy_rsi_min": "42",
        "buy_rsi_max": "65",
        "sell_rsi": "72",
        "min_entry_score": "20",
        "momentum_period": 6,
        "min_momentum_percent": "0.15",
        "min_recent_momentum_percent": "0.08",
        "min_long_momentum_percent": "0.12",
        "min_session_change_percent": "0.05",
        "min_vwap_distance_percent": "0.05",
        "max_vwap_distance_percent": "2.25",
        "max_session_pullback_percent": "0.75",
        "max_recent_pullback_percent": "0.50",
        "late_momentum_floor_percent": "0",
        "min_session_pullback_percent": "0",
        "max_entry_rsi": "0",
        "max_entries_per_symbol_per_day": 0,
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
        "inverse_trend_hold": False,
        "inverse_trend_exit_percent": "0",
        "inverse_trend_stop_percent": "3",
        "inverse_trend_lock_at_percent": "3",
        "inverse_trend_trail_percent": "2",
        "inverse_trend_max_entries": 2,
        "universe_mode": "most_active",
        "entry_mode": "scored",
        "orb_minutes": 15,
        "orb_max_breakout_percent": "1.0",
        "volume_period": 20,
        "volume_multiplier": "1.0",
        "min_avg_volume": "0",
        "take_profit_percent": "2.5",
        "profit_trail_start_percent": "0",
        "profit_trail_drop_percent": "0",
        "stop_loss_percent": "1.25",
        "stop_loss_grace_minutes": 0,
        "exit_time_in_force": "day",
        "cooldown_minutes": 0,
        "entry_open_guard_minutes": 15,
        "entry_close_guard_minutes": 15,
    },
}


# "scored": one buy path for every scored style; the profile's settings decide which readings earn
# points and which yes/no checks run. "weighted": the same readings with no yes/no checks at all.
# The other three are different mechanics, not scores.
ENTRY_MODES = {"scored", "weighted", "orb", "allocation", "inplay"}
MOVER_WEIGHT_DEFAULTS = {
    "mover_weight_volume": "45",
    "mover_weight_half_hour_move": "15",
    "mover_weight_vwap": "15",
    "mover_weight_five_min_move": "10",
    "mover_weight_range": "10",
    "mover_weight_session": "5",
    "mover_weight_rsi": "0",
    "mover_weight_spread": "40",
}
MOVER_WEIGHT_KEYS = tuple(MOVER_WEIGHT_DEFAULTS)
DIRECTION_CHECK_KEYS = ("require_up_on_session", "require_above_vwap", "require_not_falling")
OLD_SCORE_WEIGHT_KEYS = (
    "score_weight_rsi",
    "score_weight_relative_volume",
    "score_weight_momentum",
    "score_weight_recent_momentum",
    "score_weight_long_momentum",
    "score_weight_session_change",
    "score_weight_vwap",
    "score_weight_smi",
    "score_weight_volatility",
    "score_weight_liquidity_bonus",
    "score_weight_flow",
    "score_weight_pullback_penalty",
    "score_weight_overbought_penalty",
    "score_weight_volatility_penalty",
    "score_weight_session_extension_penalty",
    "score_weight_vwap_extension_penalty",
    "score_weight_session_pullback_penalty",
    "score_weight_recent_pullback_penalty",
    "score_weight_smi_overheat_penalty",
)
REENTRY_RULES = {"floor", "climb"}
# Accounts in these modes do not put their held positions at the front of the shared price stream.
STREAM_LEFTOVER_ENTRY_MODES = {"allocation", "inplay"}


def clean_symbol_list(value: Any) -> list[str]:
    """Upper-case, de-duplicated symbols from a list or a comma/space separated string."""
    if isinstance(value, str):
        items = re.sub(r"\s+", ",", value).split(",")
    elif value is None:
        items = []
    else:
        items = list(value)
    result: list[str] = []
    for item in items:
        symbol = str(item).strip().upper()
        if symbol and symbol not in result:
            result.append(symbol)
    return result


PROFILE_STRATEGY_KEYS = {
    "short_period",
    "long_period",
    "rsi_period",
    "buy_rsi_min",
    "buy_rsi_max",
    "sell_rsi",
    "min_entry_score",
    "momentum_period",
    "min_momentum_percent",
    "min_recent_momentum_percent",
    "min_long_momentum_percent",
    "min_session_change_percent",
    "min_vwap_distance_percent",
    "max_vwap_distance_percent",
    "max_session_pullback_percent",
    "max_recent_pullback_percent",
    "late_momentum_floor_percent",
    "min_session_pullback_percent",
    "max_entry_rsi",
    "max_entries_per_symbol_per_day",
    "require_rising_price",
    "smi_period",
    "min_smi",
    "atr_period",
    "min_buy_volume_ratio",
    "reentry_score_boost",
    "inverse_etf_mode",
    "inverse_trend_hold",
    "inverse_trend_exit_percent",
    "inverse_trend_stop_percent",
    "inverse_trend_lock_at_percent",
    "inverse_trend_trail_percent",
    "inverse_trend_max_entries",
    "universe_mode",
    "entry_mode",
    "orb_minutes",
    "orb_max_breakout_percent",
    "allocation_risk_on_symbols",
    "allocation_risk_off_symbols",
    "allocation_signal_symbol",
    "allocation_sma_days",
    "allocation_check",
    "allocation_trade_minutes_before_close",
    "allocation_invest_percent",
    "allocation_rebalance_drift_percent",
    "inplay_range_minutes",
    "inplay_min_relative_volume",
    "inplay_min_atr_percent",
    "inplay_min_dollar_volume_millions",
    "inplay_max_picks",
    "inplay_max_chase_percent",
    "inplay_stop",
    "mover_weight_volume",
    "mover_weight_half_hour_move",
    "mover_weight_vwap",
    "mover_weight_five_min_move",
    "mover_weight_range",
    "mover_weight_session",
    "mover_weight_rsi",
    "mover_volume_full_at",
    "mover_weight_spread",
    "mover_volume_current",
    "use_trend_checks",
    "require_up_on_session",
    "require_above_vwap",
    "require_not_falling",
    "reentry_rule",
    "volume_period",
    "volume_multiplier",
    "min_avg_volume",
    "take_profit_percent",
    "breakeven_at_percent",
    "profit_trail_start_percent",
    "profit_trail_drop_percent",
    "stop_loss_percent",
    "stop_loss_grace_minutes",
    "cooldown_minutes",
    "entry_open_guard_minutes",
    "entry_close_guard_minutes",
    "score_weight_rsi",
    "score_weight_relative_volume",
    "score_weight_momentum",
    "score_weight_recent_momentum",
    "score_weight_long_momentum",
    "score_weight_session_change",
    "score_weight_vwap",
    "score_weight_smi",
    "score_weight_volatility",
    "score_weight_liquidity_bonus",
    "score_weight_flow",
    "score_weight_pullback_penalty",
    "score_weight_overbought_penalty",
    "score_weight_volatility_penalty",
    "score_weight_session_extension_penalty",
    "score_weight_vwap_extension_penalty",
    "score_weight_session_pullback_penalty",
    "score_weight_recent_pullback_penalty",
    "score_weight_smi_overheat_penalty",
    "most_active_count",
    "daily_pick_count",
    "daily_max_symbols",
    "inverse_etf_symbols",
    "extension_atr_reference_percent",
}


class AppConfig(BaseModel):
    profile: str = "neutral"
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    use_top_volume_symbols: bool = True
    feed: str = "iex"
    poll_seconds: int = 5
    dry_run: bool = True
    market_hours_only: bool = True
    use_market_stream: bool = True
    use_bracket_orders: bool = True
    trade_size_mode: str = "percent"
    trade_size_migration: str = ""
    max_trade_notional: Decimal = Decimal("0")
    max_trade_percent: Decimal = Decimal("7.0")
    max_position_notional: Decimal = Decimal("35")
    max_position_percent: Decimal = Decimal("7.0")
    daily_loss_limit: Decimal = Decimal("0")
    daily_loss_limit_percent: Decimal = Decimal("0")
    risk_per_trade_percent: Decimal = Decimal("0")
    max_total_exposure_percent: Decimal = Decimal("25")
    max_open_positions: int = 3
    short_period: int = 9
    long_period: int = 21
    rsi_period: int = 14
    buy_rsi_min: Decimal = Decimal("42")
    buy_rsi_max: Decimal = Decimal("65")
    sell_rsi: Decimal = Decimal("72")
    min_entry_score: Decimal = Decimal("20")
    momentum_period: int = 6
    min_momentum_percent: Decimal = Decimal("0.15")
    min_recent_momentum_percent: Decimal = Decimal("0.08")
    min_long_momentum_percent: Decimal = Decimal("0.12")
    min_session_change_percent: Decimal = Decimal("0.05")
    min_vwap_distance_percent: Decimal = Decimal("0.05")
    max_vwap_distance_percent: Decimal = Decimal("2.25")
    max_session_pullback_percent: Decimal = Decimal("0.75")
    max_recent_pullback_percent: Decimal = Decimal("0.50")
    late_momentum_floor_percent: Decimal = Decimal("0")
    # Optional entry gates for strategy experiments; 0 leaves each one off.
    min_session_pullback_percent: Decimal = Decimal("0")
    max_entry_rsi: Decimal = Decimal("0")
    # Scale the VWAP and session extension caps by each symbol's own 1-min ATR%: a stock at this ATR%
    # gets the flat caps, one twice as volatile gets twice the room. 0 keeps the flat percent caps.
    extension_atr_reference_percent: Decimal = Decimal("0")
    # Entry style. "scored": one buy path whose settings decide what it does (see the trend checks,
    # direction checks, old-style score weights and mover weights below); the old "momentum" and
    # "movers" styles are profiles of it. "weighted": the mover readings with no yes/no checks at
    # all. "orb": opening-range breakout, buy once per symbol per day when price clears the first
    # orb_minutes' high while above VWAP, at most orb_max_breakout_percent past it (0 = no cap).
    # Exits stay the take-profit/stop settings.
    entry_mode: str = "scored"
    # Scored style: run the old-style yes/no checks (RSI range, trend, momentum floors, VWAP band,
    # pullback limits, rising price, SMI, volume, order flow) before scoring.
    use_trend_checks: bool = True
    # Scored style: the three checks that define "going up" for a mover. Each one is a flat no when
    # on. The weighted style has none of them: the same readings count for and against the score.
    require_up_on_session: bool = False
    require_above_vwap: bool = False
    require_not_falling: bool = False
    # After a losing exit. "floor": the next buy needs the exit's score plus reentry_score_boost,
    # once. "climb": every losing exit that day adds reentry_score_boost to min_entry_score, and a
    # sale at a gain adds it once until the stock trades above the high it was sold from.
    reentry_rule: str = "floor"
    orb_minutes: int = 15
    orb_max_breakout_percent: Decimal = Decimal("1.0")
    # entry_mode "allocation": buy and hold with a trend switch. Hold the risk-on set in equal
    # weights while the signal symbol is above its allocation_sma_days simple moving average, else
    # the risk-off set. The regime is re-decided once a week ("weekly": the last session of the
    # week) or every session ("daily"), in the last allocation_trade_minutes_before_close minutes
    # before the close. A holding is only rebalanced on a switch or once its weight is off target by
    # more than allocation_rebalance_drift_percent points. No stops, take-profit or flatten apply;
    # the switch is the exit. The momentum and ORB entry checks do not run for this mode.
    allocation_risk_on_symbols: list[str] = Field(default_factory=lambda: ["QQQ", "SPY"])
    allocation_risk_off_symbols: list[str] = Field(default_factory=lambda: ["IEF", "GLD"])
    allocation_signal_symbol: str = "QQQ"
    allocation_sma_days: int = 200
    allocation_check: str = "weekly"
    allocation_trade_minutes_before_close: int = 20
    allocation_invest_percent: Decimal = Decimal("98")
    allocation_rebalance_drift_percent: Decimal = Decimal("10")
    # entry_mode "inplay": day trade the stocks in play. inplay_range_minutes after the open, once
    # consolidated data for the range is available (it is 15 minutes delayed on the free plan), the
    # liquid symbols are ranked by how much more volume traded in their opening range than in the
    # same minutes on recent days. The top inplay_max_picks with a green range, at least
    # inplay_min_relative_volume times their usual range volume, a 14-day daily range of at least
    # inplay_min_atr_percent and a 20-day average of inplay_min_dollar_volume_millions traded a day
    # are watched. Each is bought once when it trades above its range high, no more than
    # inplay_max_chase_percent past it, with a stop at the range middle ("range_mid") or low
    # ("range_low"). The close guard ends new buys and flatten_before_close sells the rest.
    inplay_range_minutes: int = 15
    inplay_min_relative_volume: Decimal = Decimal("2.5")
    inplay_min_atr_percent: Decimal = Decimal("3")
    inplay_min_dollar_volume_millions: Decimal = Decimal("20")
    inplay_max_picks: int = 10
    inplay_max_chase_percent: Decimal = Decimal("1")
    inplay_stop: str = "range_mid"
    # Mover readings (scored and weighted styles): each earns points toward min_entry_score, and 0
    # leaves a reading out. Volume is today's total so far against the stock's own usual total by
    # this time of day (consolidated data, read about 16 minutes late), worth full points at
    # mover_volume_full_at times usual. RSI is a weight, never a ceiling. A movers profile sets
    # these (45/15/15/10/10/5) and turns the old-style score weights and trend checks off. Exits
    # are the account's own Stop Loss %, Take Profit %, Break-even and Profit Trail settings.
    mover_weight_volume: Decimal = Decimal("0")
    mover_weight_half_hour_move: Decimal = Decimal("0")
    mover_weight_vwap: Decimal = Decimal("0")
    mover_weight_five_min_move: Decimal = Decimal("0")
    mover_weight_range: Decimal = Decimal("0")
    mover_weight_session: Decimal = Decimal("0")
    mover_weight_rsi: Decimal = Decimal("0")
    mover_volume_full_at: Decimal = Decimal("5")
    # Points taken off the movers score for the bid/ask spread: all of them when the spread is as
    # wide as the stop distance, in proportion below that (0 = off). Every round trip pays the spread.
    mover_weight_spread: Decimal = Decimal("0")
    # Volume points use the lower of today's volume so far and the last half hour's, each against
    # the stock's usual, so one block print does not hold full volume points all day.
    mover_volume_current: bool = True
    max_entries_per_symbol_per_day: int = 0
    # Buy only while the price is still rising: the last completed 1-min bar closed at or above the
    # bar before it, and the latest streamed trade (when fresh) is not below that earlier close.
    require_rising_price: bool = True
    # Entry pacing per account: at most this many new buys per scan, and no new buy within this
    # many seconds of the last one (0 = off). Spreads the burst that fires the moment a guard lifts.
    # Spacing is a timed lock on the entry path, so it stays off unless the user turns it on.
    max_entries_per_scan: int = 0
    entry_spacing_seconds: int = 0
    flatten_on_daily_loss: bool = False
    # Sell every position this many minutes before the close (0 = off; for pure day trading).
    flatten_before_close_minutes: int = 0
    # Desktop notifications (Linux notify-send): fills/stop-outs, and problems (rejections, errors, loss limit).
    alert_trades: bool = True
    alert_problems: bool = True
    # Saved configs without this key predate one-time migrations and are migrated once on load.
    config_version: int = CONFIG_VERSION
    smi_period: int = 10
    min_smi: Decimal = Decimal("40")
    atr_period: int = 14
    min_buy_volume_ratio: Decimal = Decimal("0.50")
    reentry_score_boost: Decimal = Decimal("10")
    inverse_etf_mode: str = "allow"
    # Inverse ETF trend hold. On a falling market the inverse funds climb steadily: RSI sits above
    # the entry window and a tight stop is shaken out by ordinary noise (a 1.25% stop on a 3x fund
    # is a 0.4% wiggle in the index). With this on, an inverse ETF is bought when it is above its
    # session VWAP in an uptrend and up on the session, and held until it closes
    # inverse_trend_exit_percent under VWAP or falls inverse_trend_stop_percent from entry. The
    # profile's take-profit, breakeven and tight trailing stop do not apply. Once the fund has been up
    # inverse_trend_lock_at_percent the profit is locked: the stop trails inverse_trend_trail_percent
    # below the peak and never under entry (either at 0 = no lock). Being above VWAP is the downturn
    # signal: there is no separate market detector, and nothing else is blocked. Sizing is unchanged.
    inverse_trend_hold: bool = False
    inverse_trend_exit_percent: Decimal = Decimal("0")
    inverse_trend_stop_percent: Decimal = Decimal("3")
    inverse_trend_lock_at_percent: Decimal = Decimal("3")
    inverse_trend_trail_percent: Decimal = Decimal("2")
    inverse_trend_max_entries: int = 2
    universe_mode: str = "most_active"
    most_active_count: int = MOST_ACTIVES_MAX
    daily_pick_count: int = rvol_universe.PICK_COUNT
    daily_max_symbols: int = rvol_universe.MAX_SYMBOLS
    inverse_etf_symbols: list[str] = Field(default_factory=lambda: list(TOP_VOLUME_INVERSE_ETF_SYMBOLS))
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.0")
    min_avg_volume: Decimal = Decimal("0")
    take_profit_percent: Decimal = Decimal("2.5")
    # Exit management for held positions (0 = off). Once a position has gained breakeven_at_percent
    # its stop moves up to the entry price; once it has gained profit_trail_start_percent the stop
    # trails profit_trail_drop_percent below the peak, in 0.25% steps, and is never lowered.
    breakeven_at_percent: Decimal = Decimal("0")
    profit_trail_start_percent: Decimal = Decimal("0")
    profit_trail_drop_percent: Decimal = Decimal("0")
    stop_loss_percent: Decimal = Decimal("1.25")
    stop_loss_grace_minutes: int = 0
    exit_time_in_force: str = "day"
    cooldown_minutes: int = 0
    entry_open_guard_minutes: int = 15
    entry_close_guard_minutes: int = 15
    score_weight_rsi: Decimal = Decimal("5")
    score_weight_relative_volume: Decimal = Decimal("13")
    score_weight_momentum: Decimal = Decimal("14")
    score_weight_recent_momentum: Decimal = Decimal("8")
    score_weight_long_momentum: Decimal = Decimal("14")
    score_weight_session_change: Decimal = Decimal("16")
    score_weight_vwap: Decimal = Decimal("14")
    score_weight_smi: Decimal = Decimal("7")
    score_weight_volatility: Decimal = Decimal("0")
    score_weight_liquidity_bonus: Decimal = Decimal("1.5")
    score_weight_flow: Decimal = Decimal("3")
    score_weight_pullback_penalty: Decimal = Decimal("0")
    score_weight_overbought_penalty: Decimal = Decimal("0")
    score_weight_volatility_penalty: Decimal = Decimal("4")
    score_weight_session_extension_penalty: Decimal = Decimal("4")
    score_weight_vwap_extension_penalty: Decimal = Decimal("10")
    score_weight_session_pullback_penalty: Decimal = Decimal("9")
    score_weight_recent_pullback_penalty: Decimal = Decimal("6")
    score_weight_smi_overheat_penalty: Decimal = Decimal("4")

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        return sanitize_profile_key(value) or "neutral"

    @field_validator("symbols", mode="before")
    @classmethod
    def validate_symbols(cls, value: Any) -> list[str]:
        symbols = clean_symbols(value)
        if not symbols:
            raise ValueError("Enter at least one valid symbol.")
        return symbols

    @field_validator("feed")
    @classmethod
    def validate_feed(cls, value: str) -> str:
        feed = value.strip().lower()
        allowed = {item.value for item in DataFeed}
        if feed not in allowed:
            raise ValueError(f"Feed must be one of: {', '.join(sorted(allowed))}.")
        return feed

    @field_validator("poll_seconds")
    @classmethod
    def validate_poll_seconds(cls, value: int) -> int:
        return max(5, int(value))

    @field_validator("short_period", "long_period", "rsi_period", "volume_period", "momentum_period", "smi_period", "atr_period")
    @classmethod
    def validate_period(cls, value: int) -> int:
        return max(1, int(value))

    @field_validator("max_open_positions")
    @classmethod
    def validate_positions(cls, value: int) -> int:
        return max(1, int(value))

    @field_validator(
        "cooldown_minutes",
        "entry_open_guard_minutes",
        "entry_close_guard_minutes",
        "stop_loss_grace_minutes",
        "max_entries_per_symbol_per_day",
        "flatten_before_close_minutes",
    )
    @classmethod
    def validate_cooldown(cls, value: int) -> int:
        return max(0, int(value))

    @field_validator(
        "max_trade_notional",
        "max_trade_percent",
        "max_position_notional",
        "max_position_percent",
        "daily_loss_limit",
        "daily_loss_limit_percent",
        "risk_per_trade_percent",
        "max_total_exposure_percent",
        "min_entry_score",
        "min_momentum_percent",
        "min_recent_momentum_percent",
        "min_long_momentum_percent",
        "min_session_change_percent",
        "min_vwap_distance_percent",
        "max_vwap_distance_percent",
        "max_session_pullback_percent",
        "max_recent_pullback_percent",
        "late_momentum_floor_percent",
        "min_session_pullback_percent",
        "max_entry_rsi",
        "min_buy_volume_ratio",
        "reentry_score_boost",
        "inverse_trend_exit_percent",
        "inverse_trend_stop_percent",
        "inverse_trend_lock_at_percent",
        "inverse_trend_trail_percent",
        "take_profit_percent",
        "breakeven_at_percent",
        "profit_trail_start_percent",
        "profit_trail_drop_percent",
        "stop_loss_percent",
        "score_weight_rsi",
        "score_weight_relative_volume",
        "score_weight_momentum",
        "score_weight_recent_momentum",
        "score_weight_long_momentum",
        "score_weight_session_change",
        "score_weight_vwap",
        "score_weight_smi",
        "score_weight_volatility",
        "score_weight_liquidity_bonus",
        "score_weight_flow",
        "score_weight_pullback_penalty",
        "score_weight_overbought_penalty",
        "score_weight_volatility_penalty",
        "score_weight_session_extension_penalty",
        "score_weight_vwap_extension_penalty",
        "score_weight_session_pullback_penalty",
        "score_weight_recent_pullback_penalty",
        "score_weight_smi_overheat_penalty",
    )
    @classmethod
    def validate_nonnegative_decimal(cls, value: Decimal) -> Decimal:
        return max(Decimal("0"), decimal_value(value))

    @field_validator("min_smi")
    @classmethod
    def validate_smi(cls, value: Decimal) -> Decimal:
        return max(Decimal("-100"), min(Decimal("100"), decimal_value(value)))

    @field_validator("inverse_etf_mode", mode="before")
    @classmethod
    def validate_inverse_etf_mode(cls, value: str) -> str:
        mode = str(value or "allow").strip().lower()
        if mode not in {"exclude", "allow", "inverse_only"}:
            raise ValueError("Inverse ETF mode must be exclude, allow, or inverse_only.")
        return mode

    @field_validator("universe_mode", mode="before")
    @classmethod
    def validate_universe_mode(cls, value: str) -> str:
        mode = str(value or "most_active").strip().lower()
        if mode not in {"most_active", "daily_rvol"}:
            raise ValueError("Stock list must be most_active or daily_rvol.")
        return mode

    @field_validator("inverse_etf_symbols", mode="before")
    @classmethod
    def validate_inverse_etf_symbols(cls, value):
        if isinstance(value, str):
            items = re.sub(r"\s+", ",", value).split(",")
        elif value is None:
            items = []
        else:
            items = list(value)
        result: list[str] = []
        for item in items:
            symbol = str(item).strip().upper()
            if symbol and symbol not in result:
                result.append(symbol)
        if not result:
            raise ValueError("Inverse ETF set needs at least one symbol.")
        bad = [s for s in result if s not in INVERSE_ETF_SYMBOLS]
        if bad:
            raise ValueError(f"Not a known inverse ETF: {', '.join(bad)}. The inverse set only takes known inverse ETFs.")
        return result

    @model_validator(mode="before")
    @classmethod
    def read_legacy_entry_mode(cls, data: Any) -> Any:
        """Settings saved before the scored styles were merged say entry_mode "momentum" or "movers".

        Each is the scored style with the other family switched off, which is exactly how it behaved:
        a movers account never ran the trend checks or the old-style score, and a momentum account
        never used the mover readings. Whatever those unused settings held is set to off here, so the
        account trades as it did. Runs once; the result says "scored".
        """
        if not isinstance(data, dict):
            return data
        mode = str(data.get("entry_mode") or "").strip().lower()
        try:
            saved_version = int(data["config_version"]) if "config_version" in data else None
        except (TypeError, ValueError):
            saved_version = None
        if mode in {"movers", "momentum"} or (saved_version is not None and saved_version < 2):
            data = dict(data)
            if saved_version is not None:
                data["config_version"] = max(saved_version, 2)  # stays unset for an unversioned file
        if mode in {"orb", "allocation", "inplay"} and saved_version is not None and saved_version < 2:
            # Saved before the merge: the mover weights it carries were the old defaults and did
            # nothing in these styles. Left in place they would switch the mover readings on the
            # day the account is moved to the scored style.
            for key in MOVER_WEIGHT_KEYS:
                data[key] = "0"
        if mode == "movers":
            data["entry_mode"] = "scored"
            for key, value in MOVER_WEIGHT_DEFAULTS.items():
                data.setdefault(key, value)
            for key in OLD_SCORE_WEIGHT_KEYS:
                data[key] = "0"
            data["use_trend_checks"] = False
            for key in DIRECTION_CHECK_KEYS:
                data[key] = True
            data["reentry_rule"] = "climb"
        elif mode == "momentum" or (not mode and saved_version is not None and saved_version < 2):
            data["entry_mode"] = "scored"
            for key in MOVER_WEIGHT_KEYS:
                data[key] = "0"
            data["use_trend_checks"] = True
            for key in DIRECTION_CHECK_KEYS:
                data[key] = False
            data["reentry_rule"] = "floor"
        elif mode == "weighted":
            data = dict(data)
            for key, value in MOVER_WEIGHT_DEFAULTS.items():
                data.setdefault(key, value)
        return data

    @field_validator("entry_mode", mode="before")
    @classmethod
    def validate_entry_mode(cls, value: str) -> str:
        mode = str(value or "scored").strip().lower()
        if mode not in ENTRY_MODES:
            raise ValueError("Entry mode must be one of: " + ", ".join(sorted(ENTRY_MODES)) + ".")
        return mode

    @field_validator("reentry_rule", mode="before")
    @classmethod
    def validate_reentry_rule(cls, value: str) -> str:
        rule = str(value or "floor").strip().lower()
        if rule not in REENTRY_RULES:
            raise ValueError("Re-entry rule must be one of: " + ", ".join(sorted(REENTRY_RULES)) + ".")
        return rule

    @field_validator("allocation_risk_on_symbols", "allocation_risk_off_symbols", mode="before")
    @classmethod
    def validate_allocation_symbols(cls, value):
        result = clean_symbol_list(value)
        if not result:
            raise ValueError("Each allocation set needs at least one symbol.")
        if len(result) > 10:
            raise ValueError("An allocation set takes at most 10 symbols.")
        return result

    @field_validator("allocation_signal_symbol", mode="before")
    @classmethod
    def validate_allocation_signal_symbol(cls, value: str) -> str:
        symbols = clean_symbol_list(value)
        if len(symbols) != 1:
            raise ValueError("The allocation signal is one symbol.")
        return symbols[0]

    @field_validator("inplay_stop", mode="before")
    @classmethod
    def validate_inplay_stop(cls, value: str) -> str:
        stop = str(value or "range_mid").strip().lower()
        if stop not in {"range_mid", "range_low"}:
            raise ValueError("In-play stop must be range_mid or range_low.")
        return stop

    @field_validator("allocation_check", mode="before")
    @classmethod
    def validate_allocation_check(cls, value: str) -> str:
        check = str(value or "weekly").strip().lower()
        if check not in {"weekly", "daily"}:
            raise ValueError("Allocation check must be weekly or daily.")
        return check

    @field_validator("trade_size_mode", mode="before")
    @classmethod
    def validate_trade_size_mode(cls, value: str) -> str:
        mode = str(value or "percent").strip().lower()
        aliases = {
            "dollar": "notional",
            "dollars": "notional",
            "fixed": "notional",
            "amount": "notional",
            "exposure": "exposure_slot",
            "slot": "exposure_slot",
        }
        mode = aliases.get(mode, mode)
        if mode not in TRADE_SIZE_MODES:
            raise ValueError("Trade size mode must be percent, notional, or exposure_slot.")
        return mode

    @field_validator("exit_time_in_force")
    @classmethod
    def validate_exit_time_in_force(cls, value: str) -> str:
        tif = str(value or "gtc").strip().lower()
        if tif not in {"day", "gtc"}:
            raise ValueError("Exit time in force must be day or gtc.")
        return tif

    def model_post_init(self, __context: Any) -> None:
        fields_set = set(getattr(self, "model_fields_set", set()))
        allow_legacy_trade_size_migration = bool((__context or {}).get("allow_legacy_trade_size_migration"))
        profile_limits = ENTRY_PROFILE_LIMITS.get(self.profile, ENTRY_PROFILE_LIMITS["neutral"])
        if "min_recent_momentum_percent" not in fields_set:
            self.min_recent_momentum_percent = profile_limits["min_recent_momentum"]
        if "min_long_momentum_percent" not in fields_set:
            self.min_long_momentum_percent = profile_limits["min_long_momentum"]
        if "min_session_change_percent" not in fields_set:
            self.min_session_change_percent = profile_limits["min_session_change"]
        if "min_vwap_distance_percent" not in fields_set:
            self.min_vwap_distance_percent = profile_limits["min_vwap_distance"]
        if "max_vwap_distance_percent" not in fields_set:
            self.max_vwap_distance_percent = profile_limits["max_vwap_extension"]
        if "max_session_pullback_percent" not in fields_set:
            self.max_session_pullback_percent = profile_limits["max_session_pullback"]
        if "max_recent_pullback_percent" not in fields_set:
            self.max_recent_pullback_percent = profile_limits["max_recent_pullback"]
        if "late_momentum_floor_percent" not in fields_set:
            self.late_momentum_floor_percent = profile_limits["late_momentum_floor"]
        if self.long_period <= self.short_period:
            raise ValueError("Long SMA must be greater than short SMA.")
        rsi_values = (self.buy_rsi_min, self.buy_rsi_max, self.sell_rsi)
        if any(value < 0 or value > 100 for value in rsi_values):
            raise ValueError("RSI thresholds must be between 0 and 100.")
        if self.buy_rsi_min >= self.buy_rsi_max:
            raise ValueError("Buy RSI min must be below buy RSI max.")
        self.min_entry_score = min(self.min_entry_score, Decimal("100"))
        self.max_entry_rsi = min(self.max_entry_rsi, Decimal("100"))
        self.extension_atr_reference_percent = min(max(self.extension_atr_reference_percent, Decimal("0")), Decimal("5"))
        self.most_active_count = min(max(int(self.most_active_count), 1), MOST_ACTIVES_MAX)
        self.daily_pick_count = min(max(int(self.daily_pick_count), 1), DAILY_LIST_MAX)
        self.daily_max_symbols = min(max(int(self.daily_max_symbols), self.daily_pick_count), DAILY_LIST_MAX)
        self.orb_minutes = min(max(int(self.orb_minutes), 5), 60)
        self.max_entries_per_scan = min(max(int(self.max_entries_per_scan), 0), 50)
        self.entry_spacing_seconds = min(max(int(self.entry_spacing_seconds), 0), 600)
        if self.min_session_pullback_percent > 0 and self.max_session_pullback_percent > 0:
            # A pullback floor above the cap would block every entry.
            self.min_session_pullback_percent = min(self.min_session_pullback_percent, self.max_session_pullback_percent)
        self.orb_max_breakout_percent = min(max(self.orb_max_breakout_percent, Decimal("0")), Decimal("10"))
        self.allocation_sma_days = min(max(int(self.allocation_sma_days), 20), 400)
        self.inplay_range_minutes = min(max(int(self.inplay_range_minutes) // 5 * 5, 5), 30)
        for name in (
            "mover_weight_volume", "mover_weight_half_hour_move", "mover_weight_vwap", "mover_weight_five_min_move",
            "mover_weight_range", "mover_weight_session", "mover_weight_rsi", "mover_weight_spread",
        ):
            setattr(self, name, min(max(getattr(self, name), Decimal("0")), Decimal("100")))
        self.mover_volume_full_at = min(max(self.mover_volume_full_at, Decimal("1.5")), Decimal("50"))
        self.inplay_min_relative_volume = min(max(self.inplay_min_relative_volume, Decimal("0")), Decimal("50"))
        self.inplay_min_atr_percent = min(max(self.inplay_min_atr_percent, Decimal("0")), Decimal("50"))
        self.inplay_min_dollar_volume_millions = min(max(self.inplay_min_dollar_volume_millions, Decimal("0")), Decimal("100000"))
        self.inplay_max_picks = min(max(int(self.inplay_max_picks), 1), 50)
        self.inplay_max_chase_percent = min(max(self.inplay_max_chase_percent, Decimal("0")), Decimal("10"))
        self.allocation_trade_minutes_before_close = min(max(int(self.allocation_trade_minutes_before_close), 5), 60)
        self.allocation_invest_percent = min(max(self.allocation_invest_percent, Decimal("50")), Decimal("100"))
        self.allocation_rebalance_drift_percent = min(max(self.allocation_rebalance_drift_percent, Decimal("1")), Decimal("50"))
        overlap = set(self.allocation_risk_on_symbols) & set(self.allocation_risk_off_symbols)
        if overlap:
            raise ValueError(f"A symbol cannot be in both allocation sets: {', '.join(sorted(overlap))}.")
        self.inverse_trend_exit_percent = min(self.inverse_trend_exit_percent, Decimal("5"))
        self.inverse_trend_stop_percent = min(max(self.inverse_trend_stop_percent, Decimal("0.5")), Decimal("20"))
        self.inverse_trend_lock_at_percent = min(self.inverse_trend_lock_at_percent, Decimal("50"))
        self.inverse_trend_trail_percent = min(self.inverse_trend_trail_percent, Decimal("20"))
        self.inverse_trend_max_entries = min(max(int(self.inverse_trend_max_entries), 0), 10)
        self.min_buy_volume_ratio = min(self.min_buy_volume_ratio, Decimal("1"))
        if self.volume_multiplier < 0:
            raise ValueError("Volume multiplier cannot be negative.")
        if self.min_avg_volume < 0:
            raise ValueError("Minimum average volume cannot be negative.")
        self.max_position_notional = Decimal("0")
        self.max_position_percent = Decimal("0")
        self.daily_loss_limit_percent = min(self.daily_loss_limit_percent, Decimal("100"))
        if self.flatten_before_close_minutes:
            self.flatten_before_close_minutes = max(2, min(390, self.flatten_before_close_minutes))
        self.risk_per_trade_percent = Decimal("0")
        self.profit_trail_drop_percent = min(self.profit_trail_drop_percent, Decimal("50"))
        if self.profit_trail_start_percent > 0 and self.profit_trail_drop_percent <= 0:
            self.profit_trail_start_percent = Decimal("0")  # a trail needs a drop distance
        self.stop_loss_grace_minutes = 0
        self.cooldown_minutes = 0
        self.exit_time_in_force = "day"
        self.normalize_trade_size(fields_set, allow_legacy_trade_size_migration)

    def normalize_trade_size(self, fields_set: set[str], allow_legacy_migration: bool) -> None:
        mode_explicit = "trade_size_mode" in fields_set
        notional_explicit = "max_trade_notional" in fields_set
        percent_explicit = "max_trade_percent" in fields_set
        notional_positive = self.max_trade_notional > 0
        percent_positive = self.max_trade_percent > 0
        self.trade_size_migration = ""

        if mode_explicit:
            if self.trade_size_mode == "percent":
                if self.max_trade_notional > 0 and notional_explicit:
                    raise ValueError("Percent trade sizing cannot include max_trade_notional.")
                if self.max_trade_percent <= 0:
                    raise ValueError("Percent trade sizing requires max_trade_percent above zero.")
                self.max_trade_notional = Decimal("0")
            elif self.trade_size_mode == "notional":
                if self.max_trade_percent > 0 and percent_explicit:
                    raise ValueError("Dollar trade sizing cannot include max_trade_percent.")
                if self.max_trade_notional <= 0:
                    raise ValueError("Dollar trade sizing requires max_trade_notional above zero.")
                self.max_trade_percent = Decimal("0")
            else:
                if (
                    (self.max_trade_notional > 0 and notional_explicit)
                    or (self.max_trade_percent > 0 and percent_explicit)
                ):
                    raise ValueError("Exposure-slot trade sizing cannot include percent or dollar trade caps.")
                self.max_trade_notional = Decimal("0")
                self.max_trade_percent = Decimal("0")
            return

        if notional_positive and percent_positive and notional_explicit and not percent_explicit:
            self.trade_size_mode = "notional"
            self.max_trade_percent = Decimal("0")
            self.trade_size_migration = "inferred_notional_from_legacy_dollar_cap"
        elif notional_positive and percent_positive and percent_explicit and not notional_explicit:
            self.trade_size_mode = "percent"
            self.max_trade_notional = Decimal("0")
            self.trade_size_migration = "inferred_percent_from_legacy_percent_cap"
        elif notional_positive and percent_positive:
            if not allow_legacy_migration:
                raise ValueError(
                    "Specify trade_size_mode and only one active trade cap; "
                    "max_trade_notional and max_trade_percent cannot both be above zero."
                )
            self.trade_size_mode = "percent"
            self.max_trade_notional = Decimal("0")
            self.trade_size_migration = "migrated_legacy_conflicting_caps_to_percent"
        elif notional_positive:
            self.trade_size_mode = "notional"
            self.max_trade_percent = Decimal("0")
            if notional_explicit:
                self.trade_size_migration = "inferred_notional_from_legacy_dollar_cap"
        elif percent_positive:
            self.trade_size_mode = "percent"
            self.max_trade_notional = Decimal("0")
            if percent_explicit and not mode_explicit:
                self.trade_size_migration = "inferred_percent_from_legacy_percent_cap"
        else:
            self.trade_size_mode = "exposure_slot"
            self.max_trade_notional = Decimal("0")
            self.max_trade_percent = Decimal("0")
            self.trade_size_migration = "inferred_exposure_slot_from_empty_trade_caps"


def _fill_preset_strategy_defaults() -> None:
    # Built-in presets name only the keys they tune; every other strategy key takes the AppConfig default,
    # so picking a built-in style resets it and an untouched preset never reads as edited.
    defaults = AppConfig().model_dump(mode="json")
    for preset in PROFILE_PRESETS.values():
        for key in PROFILE_STRATEGY_KEYS:
            preset.setdefault(key, defaults[key])


_fill_preset_strategy_defaults()


TRADE_SIZE_KEYS = frozenset({"trade_size_mode", "max_trade_notional", "max_trade_percent"})


class AccountPayload(BaseModel):
    account_id: str | None = None
    name: str = "Paper Account"
    api_key: str = ""
    secret_key: str = ""
    remember: bool = True
    auto_connect: bool = True
    auto_start_trading: bool = False
    config: AppConfig
    # Which config keys the client actually sent (None when built in code from a full AppConfig).
    _sent_config_keys: frozenset[str] | None = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def remember_sent_config_keys(cls, data: Any, handler: Any) -> "AccountPayload":
        payload = handler(data)
        raw_config = data.get("config") if isinstance(data, dict) else None
        if isinstance(raw_config, dict):
            sent = {str(key) for key in raw_config}
            # A client that still names a style the old way ("movers", "momentum") is asking for
            # everything that name stood for, so those settings count as sent. Otherwise the merge
            # with the account's current settings would keep half of the other style.
            mode = str(raw_config.get("entry_mode") or "").strip().lower()
            if mode in {"movers", "momentum"}:
                sent |= {"entry_mode", "use_trend_checks", "reentry_rule", *DIRECTION_CHECK_KEYS, *MOVER_WEIGHT_KEYS}
            if mode == "movers":
                sent |= set(OLD_SCORE_WEIGHT_KEYS)
            payload._sent_config_keys = frozenset(sent)
        return payload


class AccountSettings(BaseModel):
    account_id: str
    name: str
    api_key: str = ""
    secret_key: str = ""
    remember: bool = True
    auto_connect: bool = True
    auto_start_trading: bool = False
    config: AppConfig
    settings_load_error: str = ""


LEGACY_CONSERVATIVE_SIGNAL_DEFAULTS: dict[str, Any] = {
    "short_period": 14,
    "long_period": 35,
    "buy_rsi_min": Decimal("45"),
    "buy_rsi_max": Decimal("60"),
    "min_entry_score": Decimal("45"),
    "momentum_period": 10,
    "min_momentum_percent": Decimal("0.15"),
    "min_smi": Decimal("15"),
    "min_buy_volume_ratio": Decimal("0.52"),
    "volume_multiplier": Decimal("1.15"),
    "entry_close_guard_minutes": 30,
}

RETUNED_CONSERVATIVE_SIGNAL_DEFAULTS: dict[str, Any] = {
    "short_period": 9,
    "long_period": 21,
    "buy_rsi_min": Decimal("42"),
    "buy_rsi_max": Decimal("65"),
    "min_entry_score": Decimal("20"),
    "momentum_period": 6,
    "min_momentum_percent": Decimal("0.15"),
    "min_recent_momentum_percent": Decimal("0.08"),
    "min_long_momentum_percent": Decimal("0.12"),
    "min_session_change_percent": Decimal("0.05"),
    "min_vwap_distance_percent": Decimal("0.05"),
    "max_vwap_distance_percent": Decimal("2.25"),
    "max_session_pullback_percent": Decimal("0.75"),
    "max_recent_pullback_percent": Decimal("0.50"),
    "late_momentum_floor_percent": Decimal("0"),
    "min_smi": Decimal("40"),
    "min_buy_volume_ratio": Decimal("0.50"),
    "reentry_score_boost": Decimal("10"),
    "inverse_etf_mode": "allow",
    "volume_multiplier": Decimal("1.0"),
    "take_profit_percent": Decimal("2.5"),
    "stop_loss_percent": Decimal("1.25"),
    "entry_open_guard_minutes": 15,
    "entry_close_guard_minutes": 15,
}

OLD_DEFAULT_SCORE_WEIGHTS: dict[str, Decimal] = {
    "score_weight_rsi": Decimal("12"),
    "score_weight_relative_volume": Decimal("12"),
    "score_weight_momentum": Decimal("20"),
    "score_weight_recent_momentum": Decimal("8"),
    "score_weight_long_momentum": Decimal("15"),
    "score_weight_session_change": Decimal("12"),
    "score_weight_vwap": Decimal("8"),
    "score_weight_smi": Decimal("8"),
    "score_weight_volatility": Decimal("3"),
    "score_weight_liquidity_bonus": Decimal("2.5"),
    "score_weight_flow": Decimal("5"),
    "score_weight_pullback_penalty": Decimal("12"),
    "score_weight_overbought_penalty": Decimal("6"),
}

PROMOTED_H2_SCORE_WEIGHTS: dict[str, Decimal] = {
    "score_weight_rsi": Decimal("5"),
    "score_weight_relative_volume": Decimal("13"),
    "score_weight_momentum": Decimal("14"),
    "score_weight_recent_momentum": Decimal("8"),
    "score_weight_long_momentum": Decimal("14"),
    "score_weight_session_change": Decimal("16"),
    "score_weight_vwap": Decimal("14"),
    "score_weight_smi": Decimal("7"),
    "score_weight_volatility": Decimal("0"),
    "score_weight_liquidity_bonus": Decimal("1.5"),
    "score_weight_flow": Decimal("3"),
    "score_weight_pullback_penalty": Decimal("0"),
    "score_weight_overbought_penalty": Decimal("0"),
    "score_weight_volatility_penalty": Decimal("4"),
    "score_weight_session_extension_penalty": Decimal("4"),
    "score_weight_vwap_extension_penalty": Decimal("10"),
    "score_weight_session_pullback_penalty": Decimal("9"),
    "score_weight_recent_pullback_penalty": Decimal("6"),
    "score_weight_smi_overheat_penalty": Decimal("4"),
}

PROMOTED_H2_SIGNAL_DEFAULTS: dict[str, Decimal] = {
    "late_momentum_floor_percent": Decimal("0"),
}

STRICT_H2_SIGNAL_DEFAULTS: dict[str, Decimal] = {
    "buy_rsi_min": Decimal("42"),
    "buy_rsi_max": Decimal("68"),
    "min_entry_score": Decimal("44"),
    "min_momentum_percent": Decimal("0.08"),
    "min_recent_momentum_percent": Decimal("0.05"),
    "min_long_momentum_percent": Decimal("0.05"),
    "min_session_change_percent": Decimal("1.35"),
    "min_vwap_distance_percent": Decimal("0.05"),
    "max_vwap_distance_percent": Decimal("2.25"),
    "max_session_pullback_percent": Decimal("0.9"),
    "max_recent_pullback_percent": Decimal("0.55"),
    "min_smi": Decimal("40"),
    "volume_multiplier": Decimal("1.5"),
    "reentry_score_boost": Decimal("12"),
    "take_profit_percent": Decimal("2.5"),
    "stop_loss_percent": Decimal("1.25"),
}

RISKBOX_SIGNAL_DEFAULTS: dict[str, Decimal] = {
    "buy_rsi_min": Decimal("42"),
    "buy_rsi_max": Decimal("65"),
    "min_entry_score": Decimal("20"),
    "min_momentum_percent": Decimal("0.15"),
    "min_recent_momentum_percent": Decimal("0.08"),
    "min_long_momentum_percent": Decimal("0.12"),
    "min_session_change_percent": Decimal("0.05"),
    "min_vwap_distance_percent": Decimal("0.05"),
    "max_vwap_distance_percent": Decimal("2.25"),
    "max_session_pullback_percent": Decimal("0.75"),
    "max_recent_pullback_percent": Decimal("0.50"),
    "late_momentum_floor_percent": Decimal("0"),
    "min_smi": Decimal("40"),
    "volume_multiplier": Decimal("1.0"),
    "reentry_score_boost": Decimal("10"),
    "take_profit_percent": Decimal("2.5"),
    "stop_loss_percent": Decimal("1.25"),
}

PREVIOUS_RISKBOX_SIGNAL_DEFAULTS: dict[str, Decimal] = RISKBOX_SIGNAL_DEFAULTS | {
    "min_entry_score": Decimal("30"),
}


def sanitize_profile_key(value: str) -> str:
    raw = str(value or "").strip().lower().replace(" ", "-")
    return "".join(ch for ch in raw if ch.isalnum() or ch in "-_")


def config_value_matches(value: Any, expected: Any) -> bool:
    if isinstance(expected, Decimal):
        return decimal_value(value) == expected
    return value == expected


def retune_legacy_conservative_config(config: AppConfig) -> AppConfig:
    if config.profile != "conservative":
        return config
    updates: dict[str, Any] = {}
    for key, retuned_value in RETUNED_CONSERVATIVE_SIGNAL_DEFAULTS.items():
        legacy_value = LEGACY_CONSERVATIVE_SIGNAL_DEFAULTS.get(key)
        if config_value_matches(getattr(config, key), legacy_value):
            updates[key] = retuned_value
    if not updates:
        return config
    try:
        return AppConfig(**(config.model_dump(mode="json") | updates))
    except (TypeError, ValueError) as exc:
        record_runtime_diagnostic(
            "config",
            "Conservative profile retune failed; keeping original config",
            exc,
            source="engine",
        )
        return config


def retune_promoted_h2_config(config: AppConfig) -> AppConfig:
    has_old_score_weights = all(
        config_value_matches(getattr(config, key), value) for key, value in OLD_DEFAULT_SCORE_WEIGHTS.items()
    )
    has_promoted_score_weights = all(
        config_value_matches(getattr(config, key), value) for key, value in PROMOTED_H2_SCORE_WEIGHTS.items()
    )
    if not (has_old_score_weights or has_promoted_score_weights):
        return config
    updates: dict[str, Decimal] = {}
    if has_old_score_weights:
        updates.update(PROMOTED_H2_SCORE_WEIGHTS)
    if config_value_matches(config.late_momentum_floor_percent, Decimal("0.50")):
        updates.update(PROMOTED_H2_SIGNAL_DEFAULTS)
    if not updates:
        return config
    try:
        return AppConfig(**(config.model_dump(mode="json") | updates))
    except (TypeError, ValueError) as exc:
        record_runtime_diagnostic(
            "config",
            "Promoted H2 score retune failed; keeping original config",
            exc,
            source="engine",
        )
        return config


def retune_riskbox_strategy_config(config: AppConfig) -> AppConfig:
    has_strict_h2_signals = all(
        config_value_matches(getattr(config, key), value) for key, value in STRICT_H2_SIGNAL_DEFAULTS.items()
    )
    has_previous_riskbox_signals = all(
        config_value_matches(getattr(config, key), value) for key, value in PREVIOUS_RISKBOX_SIGNAL_DEFAULTS.items()
    )
    if not (has_strict_h2_signals or has_previous_riskbox_signals):
        return config
    try:
        return AppConfig(**(config.model_dump(mode="json") | RISKBOX_SIGNAL_DEFAULTS))
    except (TypeError, ValueError) as exc:
        record_runtime_diagnostic(
            "config",
            "Riskbox strategy retune failed; keeping original config",
            exc,
            source="engine",
        )
        return config


def retune_strategy_config(config: AppConfig) -> AppConfig:
    return retune_riskbox_strategy_config(retune_promoted_h2_config(retune_legacy_conservative_config(config)))


def migrate_saved_config(config: AppConfig) -> tuple[AppConfig, list[str]]:
    """Apply the legacy default retunes once to a config saved before CONFIG_VERSION.

    Previously the retunes ran on every load and save, silently undoing a user's edit whenever
    it happened to match an old default set. Now they run only for unversioned saved configs,
    and every changed value is reported.
    """
    if "config_version" in config.model_fields_set:
        return config, []
    migrated = retune_strategy_config(config)
    before = config.model_dump(mode="json")
    after = migrated.model_dump(mode="json")
    changes = [
        f"{key} {before.get(key)} -> {value}"
        for key, value in after.items()
        if key != "config_version" and before.get(key) != value
    ]
    return migrated.model_copy(update={"config_version": CONFIG_VERSION}), changes


def config_from_profile(
    profile: str,
    current: dict[str, Any] | None = None,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> AppConfig:
    profile_key = sanitize_profile_key(profile) or "neutral"
    catalog = profiles or PROFILE_PRESETS
    if profile_key not in catalog and current:
        return AppConfig(**(current | {"profile": profile_key}))
    preset = dict(catalog.get(profile_key, catalog.get("neutral", PROFILE_PRESETS["neutral"])))
    if current:
        base = dict(current)
        for key in PROFILE_STRATEGY_KEYS:
            if key in preset:
                base[key] = preset[key]
        base["profile"] = profile_key
        return AppConfig(**base)
    base = dict(preset)
    base["profile"] = profile_key
    return AppConfig(**base)


def model_dict(model: Any) -> dict[str, Any]:
    if model is None:
        return {}
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if hasattr(model, "dict"):
        return model.dict()
    if isinstance(model, dict):
        return model
    return dict(getattr(model, "__dict__", {}))


def whole_number(value: Any) -> str:
    if value is None or value == "":
        return "-"
    amount = decimal_value(value)
    return f"{int(amount):,}"


def whole_number_value(value: Any) -> int:
    return int(decimal_value(value))


def money_or_dash(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return money(value)


def signed_percent(current: Any, previous: Any) -> str:
    current_value = decimal_value(current)
    previous_value = decimal_value(previous)
    if previous_value == 0:
        return "-"
    change = ((current_value - previous_value) / previous_value) * Decimal("100")
    return f"{change:+.2f}%"


def percent_from_ratio(value: Any) -> str:
    ratio = decimal_value(value)
    return f"{ratio * Decimal('100'):+.2f}%" if ratio != 0 else "0.00%"


def signed_percent_value(value: Decimal | None) -> str:
    if value is None:
        return "-"
    if value == 0:
        return "0.00%"
    places = 4 if abs(value) < Decimal("0.01") else 2
    return f"{value:+.{places}f}%"


def metric_decimal(value: Any) -> Decimal:
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
        return decimal_value(cleaned)
    return decimal_value(value)


def optional_metric_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return metric_decimal(value)


def latest_metric_decimal(values: Any) -> Decimal | None:
    if not isinstance(values, list):
        return None
    for value in reversed(values):
        parsed = optional_metric_decimal(value)
        if parsed is not None:
            return parsed
    return None


def stream_data_feed(feed: str) -> DataFeed:
    return DataFeed.SIP if str(feed).strip().lower() == DataFeed.SIP.value else DataFeed.IEX


def format_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "astimezone"):
        return value.astimezone().strftime("%b %d, %I:%M:%S %p %Z")
    return str(value)


def replay_file_path() -> Path:
    return REPLAY_DIR / f"events-{datetime.now().strftime('%Y%m%d')}.jsonl"


def replay_json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def append_replay_event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = {
        "time": datetime.now(timezone.utc).isoformat(),
        "time_display": datetime.now().strftime("%H:%M:%S"),
        "kind": kind,
        "payload": payload,
    }
    try:
        with REPLAY_LOCK:
            REPLAY_DIR.mkdir(parents=True, exist_ok=True)
            with replay_file_path().open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, default=replay_json_default, separators=(",", ":")) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        event["write_error"] = str(exc)
        record_runtime_diagnostic(
            "replay",
            "Replay event write failed",
            ReplayPersistenceError(str(exc) or exc.__class__.__name__),
            source="engine",
        )
    return event


def dashboard_cache_day() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_dashboard_cache_rows() -> dict[str, dict[str, Any]]:
    try:
        with DASHBOARD_CACHE_LOCK:
            if not DASHBOARD_CACHE_PATH.exists():
                return {}
            payload = json.loads(DASHBOARD_CACHE_PATH.read_text(encoding="utf-8"))
        if payload.get("date") != dashboard_cache_day():
            return {}
        rows = payload.get("rows") or {}
        if not isinstance(rows, dict):
            return {}
        return {
            str(symbol).upper(): dict(row)
            for symbol, row in rows.items()
            if symbol and isinstance(row, dict)
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        record_runtime_diagnostic(
            "dashboard_cache",
            "Dashboard cache load failed; using empty cache",
            CachePersistenceError(str(exc) or exc.__class__.__name__),
            source="engine",
        )
        return {}


def save_dashboard_cache_rows(rows: list[dict[str, Any]]) -> None:
    payload_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        payload_rows[symbol] = {
            field: row.get(field)
            for field in DASHBOARD_CACHE_FIELDS
            if field in row
        }
    payload = {
        "date": dashboard_cache_day(),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "rows": payload_rows,
    }
    try:
        with DASHBOARD_CACHE_LOCK:
            APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
            temp_path = DASHBOARD_CACHE_PATH.with_suffix(".tmp")
            temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temp_path.replace(DASHBOARD_CACHE_PATH)
    except (OSError, TypeError, ValueError) as exc:
        record_runtime_diagnostic(
            "dashboard_cache",
            "Dashboard cache save failed",
            CachePersistenceError(str(exc) or exc.__class__.__name__),
            source="engine",
        )


def compact_bar_payload(bar: Any, daily: bool = False) -> dict[str, Any]:
    raw = model_dict(bar)
    return {
        "symbol": str(raw.get("symbol", "")).upper(),
        "daily": daily,
        "close": raw.get("close"),
        "high": raw.get("high"),
        "low": raw.get("low"),
        "volume": raw.get("volume"),
        "timestamp": format_timestamp(raw.get("timestamp")),
    }


def market_stream_error_status(code: str, text: str, symbol_limit: int) -> tuple[str, str]:
    """(status, detail) for an error message from the market-data websocket."""
    detail = f"{text} ({code})" if code else text
    # 405: the subscription would exceed the data plan's symbol limit; Alpaca keeps the previous
    # subscription, so this needs the app-wide stream limit lowered rather than a reconnect.
    if code == "405" or "symbol limit" in text.lower():
        return (
            "Symbol limit",
            f"Alpaca refused the subscription: {symbol_limit} streamed symbols is more than this data plan allows "
            f"({detail}). Lower Streamed symbols under Settings > App-wide.",
        )
    return "Stream error", detail


def is_connection_limit_error(message: str) -> bool:
    return "connection limit exceeded" in str(message or "").lower()


def is_already_stopped_stream_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "nonetype" in message and "is_running" in message


def is_placeholder_position(position: dict[str, Any]) -> bool:
    # Corporate-action leftovers such as CVR rights (046CVR015) have no market price, cannot be sold,
    # and hold no exposure, so they must not use up a max-open-positions slot or be traded. Alpaca
    # reports their price as 0 or as missing; a missing price only counts for a CUSIP-style symbol
    # (one with a digit), since a real ticker's price can be missing for a moment after a fill.
    price = position.get("current_price")
    if price is None or str(price).strip() == "":
        return any(ch.isdigit() for ch in str(position.get("symbol") or ""))
    return decimal_value(price, Decimal("-1")) == 0


def is_pending_cancel_error(exc: Exception) -> bool:
    # Alpaca 422 (code 42210000) when a cancel is sent for an order whose earlier cancel is still in flight.
    return "pending cancel" in str(exc or "").lower()


def crossed_sell_stop_market_price(exc: OrderExecutionError, stop_price: Decimal) -> Decimal | None:
    """Alpaca's market reference when it rejected a sell stop that had already been reached."""
    try:
        payload = json.loads(str(exc))
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("code") != 42210000
        or payload.get("message") != "stop price must be less than current price"
    ):
        return None
    market_price = decimal_value(payload.get("market_price"))
    if market_price.is_finite() and Decimal("0") < market_price <= stop_price:
        return market_price
    return None


def credential_text(value: Any) -> str:
    return str(value or "").strip()


def has_credential_whitespace(value: str) -> bool:
    return any(ch.isspace() for ch in value)


def looks_like_paper_api_key(value: Any) -> bool:
    clean = credential_text(value)
    return (
        len(clean) == 26
        and clean.startswith("PK")
        and not has_credential_whitespace(clean)
    )


def looks_like_secret_key(value: Any) -> bool:
    clean = credential_text(value)
    return (
        len(clean) >= 32
        and not has_credential_whitespace(clean)
    )


def credential_validation_error(api_key: Any, secret_key: Any, require_pair: bool = True) -> str:
    api = credential_text(api_key)
    secret = credential_text(secret_key)
    if require_pair and (not api or not secret):
        return "Enter Alpaca paper API key and secret key."
    if api and not looks_like_paper_api_key(api):
        return "API key field does not look like an Alpaca paper API key. It should start with PK and be 26 characters."
    if secret and not looks_like_secret_key(secret):
        return "Secret key field does not look like an Alpaca secret key."
    if api and secret and api == secret:
        return "API key and secret key are identical; the API key field appears to contain the secret."
    return ""


def is_non_fractionable_error(message: str) -> bool:
    clean = str(message or "").lower()
    return "not fractionable" in clean or "fractionable" in clean


def historical_bars_limit(symbol_count: int, required_bars: int, cap: int = HISTORICAL_BARS_REQUEST_LIMIT) -> int:
    per_symbol = max(HISTORICAL_BARS_PER_SYMBOL, required_bars + 20)
    return min(cap, max(1000, per_symbol * max(1, symbol_count)))


def historical_bars_per_symbol(required_bars: int) -> int:
    return max(HISTORICAL_BARS_PER_SYMBOL, required_bars + 20)


def required_strategy_bars(config: AppConfig) -> int:
    return max(
        config.long_period,
        config.rsi_period + 1,
        config.volume_period + 1,
        config.momentum_period + 1,
        config.smi_period + 2,
        config.atr_period + 1,
    )


def chunked_symbols_for_bar_limit(symbols: list[str], per_symbol_limit: int) -> list[list[str]]:
    clean = [str(symbol).upper() for symbol in symbols if str(symbol).strip()]
    if not clean:
        return []
    batch_size = max(1, HISTORICAL_BARS_REQUEST_LIMIT // max(1, per_symbol_limit))
    return [clean[index : index + batch_size] for index in range(0, len(clean), batch_size)]


def historical_bars_start(now: datetime, per_symbol_limit: int) -> datetime:
    # Alpaca's request limit is a total across all symbols, and multi-symbol pages are
    # ordered by symbol. Bounding the window to per_symbol_limit minutes caps each symbol
    # at per_symbol_limit one-minute bars, so the total limit can never cut off the
    # alphabetically later symbols (which would leave them trading on morning prices).
    return now - timedelta(minutes=max(0, per_symbol_limit - 1))


def fetch_stock_bars_chunked(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    required_bars: int,
    feed: str,
    now: datetime | None = None,
) -> dict[str, list[Any]]:
    per_symbol_limit = historical_bars_per_symbol(required_bars)
    current = now or datetime.now(timezone.utc)
    data: dict[str, list[Any]] = {str(symbol).upper(): [] for symbol in symbols}
    requestable = without_invalid_market_data_symbols(sorted(set(symbols)))
    for batch in chunked_symbols_for_bar_limit(requestable, per_symbol_limit):
        while batch:
            limit = historical_bars_limit(len(batch), required_bars)
            window_bars = min(per_symbol_limit, limit // len(batch))
            try:
                bars = data_client.get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=batch,
                        timeframe=TimeFrame.Minute,
                        start=historical_bars_start(current, window_bars),
                        limit=limit,
                        feed=DataFeed(feed),
                        adjustment=Adjustment.RAW,
                        sort=Sort.ASC,
                    )
                )
            except Exception as exc:
                rejected = rejected_market_data_symbol(exc, batch)
                if not rejected:
                    raise
                batch = [symbol for symbol in batch if symbol != rejected]
                continue
            for symbol, symbol_bars in bars.data.items():
                data[str(symbol).upper()] = list(symbol_bars)[-per_symbol_limit:]
            break
    return data


def fetch_daily_bars_chunked(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    feed: str,
    now: datetime | None = None,
    lookback_days: int = rvol_universe.DAILY_BARS_LOOKBACK_DAYS,
) -> dict[str, list[Any]]:
    """Split-adjusted daily bars for the relative-volume average; drops symbols the API rejects."""
    current = now or datetime.now(timezone.utc)
    data: dict[str, list[Any]] = {str(symbol).upper(): [] for symbol in symbols}
    requestable = without_invalid_market_data_symbols(sorted(set(data)))
    for index in range(0, len(requestable), STOCK_SNAPSHOT_BATCH_SIZE):
        batch = requestable[index : index + STOCK_SNAPSHOT_BATCH_SIZE]
        while batch:
            try:
                bars = data_client.get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=batch,
                        timeframe=TimeFrame.Day,
                        start=current - timedelta(days=lookback_days),
                        limit=HISTORICAL_BARS_REQUEST_LIMIT,
                        feed=DataFeed(feed),
                        adjustment=Adjustment.SPLIT,
                        sort=Sort.ASC,
                    )
                )
            except Exception as exc:
                rejected = rejected_market_data_symbol(exc, batch)
                if not rejected:
                    raise
                batch = [symbol for symbol in batch if symbol != rejected]
                continue
            for symbol, symbol_bars in bars.data.items():
                data[str(symbol).upper()] = list(symbol_bars)
            break
    return data


def daily_bar_session_date(timestamp: Any) -> str:
    session = rvol_universe.bar_session_date(timestamp, MARKET_TIMEZONE)
    return session.isoformat() if session else ""


def pending_daily_universe_meta(session_date: str = "", pick_time: str = "") -> dict[str, Any]:
    return {
        "status": "pending",
        "session_date": session_date,
        "pick_time": pick_time,
        "picked_at": "",
        "picked_count": 0,
        "added_count": 0,
    }


def et_clock_label(moment: datetime) -> str:
    return moment.strftime("%I:%M %p ET").lstrip("0")


def without_invalid_market_data_symbols(symbols: list[str]) -> list[str]:
    with INVALID_MARKET_DATA_SYMBOLS_LOCK:
        invalid = set(INVALID_MARKET_DATA_SYMBOLS)
    return [symbol for symbol in symbols if str(symbol).strip().upper() not in invalid]


def rejected_market_data_symbol(error: Exception, batch: list[str]) -> str:
    """Return the batch symbol the API rejected as invalid and remember it, or ""."""
    match = INVALID_SYMBOL_PATTERN.search(str(error))
    symbol = match.group(1).upper() if match else ""
    if symbol not in {str(item).upper() for item in batch}:
        return ""
    with INVALID_MARKET_DATA_SYMBOLS_LOCK:
        first_seen = symbol not in INVALID_MARKET_DATA_SYMBOLS
        INVALID_MARKET_DATA_SYMBOLS.add(symbol)
    if first_seen:
        record_runtime_diagnostic(
            "market_data",
            f"Skipping {symbol}: Alpaca market data does not recognize it (e.g. a CVR or rights position)",
            MarketDataError(str(error) or error.__class__.__name__),
            severity="info",
            source="engine",
        )
    return symbol


def fetch_stock_snapshots_chunked(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    feed: str,
) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    clean_symbols_list = without_invalid_market_data_symbols(sorted(set(clean_symbols(symbols))))
    for index in range(0, len(clean_symbols_list), STOCK_SNAPSHOT_BATCH_SIZE):
        batch = clean_symbols_list[index : index + STOCK_SNAPSHOT_BATCH_SIZE]
        while batch:
            try:
                response = data_client.get_stock_snapshot(
                    StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed(feed))
                )
            except Exception as exc:
                rejected = rejected_market_data_symbol(exc, batch)
                if rejected:
                    batch = [symbol for symbol in batch if symbol != rejected]
                    continue
                if len(batch) > STOCK_SNAPSHOT_SINGLE_RETRY_LIMIT:
                    # One request per symbol for a 100-symbol batch would blow through the free
                    # plan's 200 calls/min; skip this round and let the next refresh try again.
                    record_runtime_diagnostic(
                        "market_data",
                        f"Batch snapshot request failed for {len(batch)} symbols; will retry next refresh",
                        MarketDataError(str(exc) or exc.__class__.__name__),
                        source="engine",
                    )
                    break
                record_runtime_diagnostic(
                    "market_data",
                    "Batch snapshot request failed; retrying individual symbols",
                    MarketDataError(str(exc) or exc.__class__.__name__),
                    source="engine",
                )
                symbol_failures = 0
                for symbol in batch:
                    try:
                        response = data_client.get_stock_snapshot(
                            StockSnapshotRequest(symbol_or_symbols=symbol, feed=DataFeed(feed))
                        )
                    except Exception as symbol_exc:
                        if symbol_failures < 3:
                            record_runtime_diagnostic(
                                "market_data",
                                f"Snapshot request failed for {symbol}",
                                MarketDataError(str(symbol_exc) or symbol_exc.__class__.__name__),
                                source="engine",
                            )
                        symbol_failures += 1
                        continue
                    if isinstance(response, dict):
                        snapshot = response.get(symbol)
                        if snapshot is not None:
                            snapshots[str(symbol).upper()] = snapshot
                break
            if isinstance(response, dict):
                for symbol, snapshot in response.items():
                    snapshots[str(symbol).upper()] = snapshot
            break
    return snapshots


def fetch_most_active_symbols(screener_client: ScreenerClient, limit: int = DASHBOARD_TOP_LIMIT) -> list[dict[str, Any]]:
    response = screener_client.get_most_actives(
        MostActivesRequest(top=int(limit), by=MostActivesBy.VOLUME)
    )
    raw_rows = getattr(response, "most_actives", None)
    if raw_rows is None and isinstance(response, dict):
        raw_rows = response.get("most_actives") or response.get("mostActives") or []

    rows: list[dict[str, Any]] = []
    for item in raw_rows or []:
        raw = model_dict(item)
        symbol = str(raw.get("symbol") or "").strip().upper()
        volume_raw = whole_number_value(raw.get("volume"))
        if not symbol or volume_raw <= 0:
            continue
        rows.append(
            {
                "symbol": symbol,
                "daily_volume_raw": volume_raw,
                "trade_count_raw": whole_number_value(raw.get("trade_count")),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def merged_symbols(*groups: Any) -> list[str]:
    symbols: list[str] = []
    for group in groups:
        if not group:
            continue
        for item in group:
            symbol = str(item or "").strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def clamp_decimal(value: Decimal, low: Decimal = Decimal("0"), high: Decimal = Decimal("1")) -> Decimal:
    return max(low, min(high, value))


def percent_change(value: Decimal, basis: Decimal) -> Decimal:
    if basis <= 0:
        return Decimal("0")
    return ((value - basis) / basis * Decimal("100")).quantize(Decimal("0.01"))


def cash_percent_of_equity(cash: Any, equity: Any) -> Decimal:
    """Cash as a percent of equity: how much of the account is liquid. 0 when equity is not positive."""
    equity_value = decimal_value(equity)
    if equity_value <= 0:
        return Decimal("0")
    return (decimal_value(cash) / equity_value * Decimal("100")).quantize(Decimal("0.1"))


def uses_mover_readings(config: AppConfig) -> bool:
    """The buy decision reads the mover readings: always in the weighted style, and in the scored
    style whenever a mover weight is above zero or one of the direction checks is on."""
    if config.entry_mode == "weighted":
        return True
    if config.entry_mode != "scored":
        return False
    return any(getattr(config, key) > 0 for key in MOVER_WEIGHT_KEYS) or any(
        getattr(config, key) for key in DIRECTION_CHECK_KEYS
    )


def uses_old_score(config: AppConfig) -> bool:
    return config.entry_mode == "scored" and any(getattr(config, key) != 0 for key in OLD_SCORE_WEIGHT_KEYS)


def uses_climbing_reentry(config: AppConfig) -> bool:
    return config.entry_mode == "weighted" or (config.entry_mode == "scored" and config.reentry_rule == "climb")


def uses_reentry_floor(config: AppConfig) -> bool:
    return config.entry_mode == "orb" or (config.entry_mode == "scored" and config.reentry_rule == "floor")


def direction_checks(config: AppConfig) -> tuple[bool, bool, bool]:
    """(up on the session, above VWAP, not falling): which of the three yes/no checks run."""
    if config.entry_mode != "scored":
        return False, False, False
    return bool(config.require_up_on_session), bool(config.require_above_vwap), bool(config.require_not_falling)


def entry_profile_limits(config: AppConfig) -> dict[str, Decimal]:
    limits = dict(ENTRY_PROFILE_LIMITS.get(config.profile, ENTRY_PROFILE_LIMITS["neutral"]))
    limits["min_recent_momentum"] = config.min_recent_momentum_percent
    limits["min_long_momentum"] = config.min_long_momentum_percent
    limits["min_session_change"] = config.min_session_change_percent
    limits["min_vwap_distance"] = config.min_vwap_distance_percent
    if config.max_vwap_distance_percent > 0:
        limits["max_vwap_extension"] = max(config.max_vwap_distance_percent, limits["min_vwap_distance"])
    if config.max_session_pullback_percent > 0:
        limits["max_session_pullback"] = config.max_session_pullback_percent
    if config.max_recent_pullback_percent > 0:
        limits["max_recent_pullback"] = config.max_recent_pullback_percent
    limits["late_momentum_floor"] = config.late_momentum_floor_percent
    return limits


def atr_scaled_cap(cap: Decimal, snapshot: Any, config: AppConfig) -> Decimal:
    reference = config.extension_atr_reference_percent
    atr = getattr(snapshot, "atr_percent", None)
    if reference <= 0 or atr is None or atr <= 0:
        return cap
    return cap * atr / reference


def floor_hold_reason(label: str, value: Decimal, floor: Decimal) -> str:
    if value < 0 or floor <= 0:
        return f"Hold ({label} {value:+.2f}%)"
    return f"Hold ({label} {value:+.2f}% < {floor:.2f}%)"


def below_entry_floor(value: Decimal | None, floor: Decimal) -> bool:
    if value is None:
        return True
    if floor <= 0:
        return value <= 0
    return value < floor


class TraderEngine:
    def __init__(self, account_id: str, name: str = "Paper Account") -> None:
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        self.account_id = account_id
        self.name = name
        self.config = AppConfig()
        self.api_key = ""
        self.secret_key = ""
        self.remember = False
        self.auto_connect = True
        self.auto_start_trading = False
        self.connected = False
        self.trading_enabled = False
        self.status = "Not connected"
        self.account: dict[str, Any] = {}
        self.positions: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.protection_rows: list[dict[str, Any]] = []
        self.trade_history: list[dict[str, Any]] = []
        self.order_intents: list[dict[str, Any]] = []
        self.replay_recorder: Any | None = None
        self.strategy_rows: list[dict[str, Any]] = []
        self.logs: list[dict[str, str]] = []
        self.market_clock = self.default_market_clock()
        self.strategy_state = StrategyState()
        self.trading_client: TradingClient | None = None
        self.data_client: StockHistoricalDataClient | None = None
        self.screener_client: ScreenerClient | None = None
        self.news_client: NewsClient | None = None
        self.trade_stream: Any | None = None
        self.top_volume_rows: list[dict[str, Any]] = []
        # (symbol, session date) -> split-adjusted previous close, or None when there is no earlier bar
        self.previous_close_cache: dict[tuple[str, str], float | None] = {}
        self.top_volume_symbols: list[str] = []
        self.top_volume_last_fetch_at = 0.0
        self.top_volume_updated = ""
        self.top_volume_error = ""
        # Daily relative-volume list, owned by TraderManager and pushed here (universe_mode=daily_rvol).
        self.daily_universe_symbols: list[str] = []
        self.daily_universe_meta: dict[str, Any] = pending_daily_universe_meta()
        self.last_day_tape_scan_bucket = -1
        self.last_day_tape_scan_signature: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
        self.latest_trading_statuses: dict[str, dict[str, Any]] = {}
        self.latest_quotes: dict[str, dict[str, Any]] = {}
        self.halted_symbols: dict[str, dict[str, Any]] = {}
        self.lookup_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.asset_tradeability_cache: dict[str, tuple[float, str]] = {}
        self.reentry_score_floors: dict[str, Decimal] = {}
        self.entries_today_by_symbol: dict[str, int] = {}
        self.entries_today_date: Any = None
        self.daily_loss_breach_session = ""
        self.daily_loss_detail = ""
        self.config_migration_notes: list[str] = []
        self.dry_run_flatten_logged_session = ""
        self.alerted_fill_ids: set[str] | None = None  # None until the first refresh seeds existing fills
        self.consecutive_refresh_failures = 0
        self.processed_reentry_exit_ids: set[str] = set()
        self.reentry_reset_at: datetime | None = None
        # Climbing re-entry rule: today's losing round trips per symbol, keyed by the buy that opened each.
        self.reentry_losses_today: dict[str, set[str]] = {}
        self.reentry_losses_date: Any = None
        self.reentry_open_buys: dict[str, tuple[str, Decimal]] = {}  # symbol -> (buy id, fill price)
        # Climbing re-entry rule: a stock sold at a gain needs a higher score until it trades above this price.
        self.reentry_new_highs: dict[str, tuple[str, Decimal]] = {}  # symbol -> (sell id, price to beat)
        self.reentry_released_sells: set[str] = set()
        # Today's filled orders by id, kept all day. The regular read is only the newest 100 closed
        # orders, which is about two hours of a busy day.
        self.day_fills: dict[str, dict[str, Any]] = {}
        self.day_fills_date: Any = None
        self.day_fills_loaded = False
        self.day_fills_retry_at = 0.0
        self.day_fills_warned = False
        self.open_order_ids: set[str] = set()  # open at the last refresh
        self.entry_lock_dates: dict[str, str] = {}
        self.entry_times: dict[str, datetime] = {}
        self.exit_lock_dates: dict[str, str] = {}
        self.position_peak_prices: dict[str, Decimal] = {}
        self.order_submit_holds: dict[tuple[str, str], datetime] = {}
        self.order_reject_holds: dict[tuple[str, str], datetime] = {}
        self.protective_order_reject_holds: dict[tuple[str, str], datetime] = {}
        self.last_scan_log_at = 0.0
        self.last_entry_submitted_at = 0.0
        self.latest_stream_trades: dict[str, tuple[Decimal, datetime]] = {}
        self.dashboard_cache_last_save = 0.0
        self.daily_pl_history_cache: tuple[float, str, dict[str, Any]] | None = None
        self.last_refresh = ""
        self.last_error = ""
        self.settings_load_error = ""
        # Hold mode (entry_mode "allocation"): cached inputs and today's decided regime.
        self.allocation_closes_cache: dict[tuple[str, str, int], list[Decimal]] = {}
        self.allocation_sessions_cache: tuple[str, list[date]] | None = None
        self.allocation_retry_at = 0.0
        self.allocation_latch: tuple[str, str] | None = None
        self.allocation_view: dict[str, Any] = {}
        self.allocation_dry_run_session = ""
        # Day-trade mode (entry_mode "inplay"): today's picks and the data behind them. The data is
        # fetched on a worker thread so a slow pull never holds up the shared refresh loop.
        self.inplay_picks: dict[str, inplay_logic.Pick] = {}
        self.inplay_picks_session = ""
        self.inplay_history: tuple[str, dict[str, list[Decimal]], dict[str, inplay_logic.DailyStats]] | None = None
        self.inplay_rejected: dict[str, int] = {}
        self.inplay_checked = 0
        self.inplay_worker: threading.Thread | None = None
        self.inplay_retry_at = 0.0
        self.inplay_failures = 0
        self.inplay_view: dict[str, Any] = {}
        # Mover readings: each symbol's usual volume by time of day and today's
        # relative volume, loaded on a worker thread from consolidated data.
        self.mover_session = ""
        self.mover_profiles: dict[str, list[float] | None] = {}
        self.mover_stats: dict[str, inplay_logic.DailyStats] = {}
        self.mover_volume: dict[str, Decimal] = {}
        self.mover_volume_recent: dict[str, Decimal] = {}  # the last half hour against its usual
        self.mover_quotes: dict[str, tuple[Decimal, Decimal, float]] = {}  # symbol -> (bid, ask, read at)
        self.mover_volume_slot: int | None = None
        self.mover_volume_at = 0.0
        self.mover_scores: dict[str, movers_logic.Score] = {}
        self.mover_worker: threading.Thread | None = None
        self.mover_retry_at = 0.0
        self.mover_failures = 0
        self.mover_view: dict[str, Any] = {}
        self.restore_trade_guards_from_replay()

    def configure_saved(self, settings: AccountSettings) -> None:
        api_key = credential_text(settings.api_key)
        secret_key = credential_text(settings.secret_key)
        validation_error = credential_validation_error(api_key, secret_key) if api_key or secret_key else ""
        with self.lock:
            self.name = settings.name.strip() or "Paper Account"
            self.config, migration_notes = migrate_saved_config(settings.config)
            self.config_migration_notes = migration_notes
            self.settings_load_error = settings.settings_load_error
            self.api_key = api_key if not validation_error else ""
            self.secret_key = secret_key if looks_like_secret_key(secret_key) else ""
            self.remember = settings.remember
            self.auto_connect = settings.auto_connect
            self.auto_start_trading = settings.auto_start_trading
            self.daily_pl_history_cache = None
            if self.settings_load_error:
                self.last_error = self.settings_load_error
                self.status = "Settings load error"
                self.log("error", self.settings_load_error)
            if validation_error:
                self.last_error = f"Saved credentials invalid: {validation_error}"
                self.status = "Saved credentials invalid"
                self.log("error", self.last_error)

    def payload_config(self, payload: AccountPayload) -> AppConfig:
        """The payload's config, keeping this account's current value for every key the client left out.

        A page or script that does not know a setting must not reset it to the default just by saving
        the settings it does know. Only keys that were actually sent can change. The payload has
        already been validated on its own, so a partial payload still has to be a valid config.
        """
        sent = payload._sent_config_keys
        if sent is None:
            return payload.config
        if sent & TRADE_SIZE_KEYS:
            # Mode and the two size caps only make sense together: take all three as sent and normalized.
            sent = sent | TRADE_SIZE_KEYS
        with self.lock:
            current = self.config
            unsent = [key for key in AppConfig.model_fields if key not in sent]
            if not unsent:
                return payload.config
            merged = payload.config.model_dump()
            merged.update({key: getattr(current, key) for key in unsent})
            if merged.get("entry_mode") == "weighted" and all(Decimal(str(merged[key])) == 0 for key in MOVER_WEIGHT_KEYS):
                # Moved to the weighted style with every mover weight at 0 (the account never used
                # them): it could never buy. Start it on the standard mover weights.
                merged.update(MOVER_WEIGHT_DEFAULTS)
            return AppConfig.model_validate(merged)

    def configure_payload(self, payload: AccountPayload) -> None:
        api_key = credential_text(payload.api_key)
        secret_key = credential_text(payload.secret_key)
        validation_error = credential_validation_error(api_key, secret_key, require_pair=False)
        if validation_error:
            raise RuntimeError(validation_error)
        with self.lock:
            self.name = payload.name.strip() or "Paper Account"
            self.config = self.payload_config(payload)
            self.settings_load_error = ""
            if api_key:
                self.api_key = api_key
            if secret_key:
                self.secret_key = secret_key
            self.remember = payload.remember
            self.auto_connect = payload.auto_connect
            self.auto_start_trading = payload.auto_start_trading
            self.daily_pl_history_cache = None

    def payload_credentials(self, payload: AccountPayload) -> tuple[str, str]:
        with self.lock:
            api_key = credential_text(payload.api_key) or self.api_key
            secret_key = credential_text(payload.secret_key) or self.secret_key
        validation_error = credential_validation_error(api_key, secret_key)
        if validation_error:
            raise RuntimeError(validation_error)
        return api_key, secret_key

    def trading_symbols(self) -> list[str]:
        with self.lock:
            config = self.config
            if config.inverse_etf_mode == "inverse_only":
                base_symbols = []
            elif config.use_top_volume_symbols and config.universe_mode == "daily_rvol":
                # Empty until the daily pick: only the inverse set (and held positions) are scanned.
                base_symbols = list(self.daily_universe_symbols)
            elif config.use_top_volume_symbols and self.top_volume_symbols:
                base_symbols = list(self.top_volume_symbols[:min(config.most_active_count, DASHBOARD_TOP_LIMIT)])
            else:
                base_symbols = list(config.symbols)
        return merged_symbols(base_symbols, self.active_inverse_symbols())

    def active_inverse_symbols(self) -> list[str]:
        # The bounded inverse set is always scanned in top-volume allow mode, so a down day cannot
        # hide it just because Alpaca's most-active list skipped it. Each one still has to pass
        # the same entry checks as any other symbol; this only guarantees it is looked at.
        with self.lock:
            mode = self.config.inverse_etf_mode
            use_top_volume = self.config.use_top_volume_symbols
            inverse_symbols = self.config.inverse_etf_symbols
        if mode == "inverse_only" or (mode == "allow" and use_top_volume):
            return list(inverse_symbols)
        return []

    def market_proxy_analysis_symbols(self) -> list[str]:
        with self.lock:
            use_top_volume = self.config.use_top_volume_symbols
            mode = self.config.inverse_etf_mode
        if not use_top_volume and mode != "inverse_only":
            return []
        return list(MARKET_PROXY_SYMBOLS)

    def position_symbols_for_market_data(self) -> list[str]:
        with self.lock:
            return [
                str(item.get("symbol") or "").strip().upper()
                for item in self.positions
                if str(item.get("symbol") or "").strip() and decimal_value(item.get("qty_raw") or item.get("qty")) > 0
            ]

    def mode_entry_symbols(self) -> list[str]:
        """The symbols the entry loop considers: today's picks in day-trade mode, else the scan list."""
        if self.config.entry_mode == "inplay":
            with self.lock:
                return [pick.symbol for pick in sorted(self.inplay_picks.values(), key=lambda pick: pick.rank)]
        return self.trading_symbols()

    def scan_symbols(self, position_symbols: Any = None) -> list[str]:
        config = self.config
        if config.entry_mode == "inplay":
            return without_invalid_market_data_symbols(
                merged_symbols(
                    self.mode_entry_symbols(),
                    position_symbols or self.position_symbols_for_market_data(),
                    self.market_proxy_analysis_symbols(),
                )
            )
        if config.entry_mode == "allocation":
            # Hold mode only needs its two sets, its signal and whatever is held.
            return without_invalid_market_data_symbols(
                merged_symbols(
                    [config.allocation_signal_symbol],
                    list(config.allocation_risk_on_symbols) + list(config.allocation_risk_off_symbols),
                    position_symbols or self.position_symbols_for_market_data(),
                )
            )
        return without_invalid_market_data_symbols(
            merged_symbols(
                self.trading_symbols(),
                position_symbols or self.position_symbols_for_market_data(),
                self.market_proxy_analysis_symbols(),
            )
        )

    def clear_entry_score(self, symbol: str) -> None:
        self.strategy_state.entry_score.pop(symbol.strip().upper(), None)

    def set_entry_score(self, symbol: str, score: Decimal | None) -> None:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return
        if score is None:
            self.strategy_state.entry_score.pop(clean_symbol, None)
        else:
            self.strategy_state.entry_score[clean_symbol] = score

    def connect_saved(self) -> None:
        with self.lock:
            payload = AccountPayload(
                account_id=self.account_id,
                name=self.name,
                api_key="",
                secret_key="",
                remember=self.remember,
                auto_connect=self.auto_connect,
                auto_start_trading=self.auto_start_trading,
                config=self.config,
            )
        self.connect(payload)

    def log(self, level: str, message: str) -> None:
        with self.lock:
            self.logs.append(
                {
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message,
                }
            )
            self.logs = self.logs[-400:]

    def backtester_boundary(self) -> EngineBacktesterBoundary:
        return EngineBacktesterBoundary(
            account_state=LiveAccountStateBoundary(self),
            market_data=LiveMarketDataBoundary(self, fetch_stock_bars_chunked),
            orders=LiveOrderExecutionBoundary(self),
            replay=LiveReplayBoundary(self, append_replay_event),
            clock=LiveClockBoundary(),
            strategy=LiveStrategyBoundary(self),
        )

    def record_runtime_exception(
        self,
        area: str,
        message: str,
        error: BaseException,
        *,
        severity: str = "warning",
        log_level: str = "warn",
        set_last_error: bool = False,
    ) -> str:
        diagnostic = record_runtime_diagnostic(
            area,
            message,
            error,
            severity=severity,
            source="engine",
        )
        detail = str(diagnostic.get("detail") or "").strip()
        text = f"{message}: {detail}" if detail else message
        self.log(log_level, text)
        if set_last_error:
            with self.lock:
                self.last_error = text
                self.status = text
        return text

    def submit_order_request(self, order: Any) -> Any:
        if trading_halted():
            raise TradingHaltedError("n8n watchdog is blocking order changes")
        try:
            return self.backtester_boundary().orders.submit_order(order)
        except OrderExecutionError as exc:
            record_runtime_diagnostic(
                "order_execution",
                "Live order submission failed",
                exc,
                severity="error",
                source="engine",
            )
            raise

    def cancel_order_request(self, order_id: str) -> None:
        if trading_halted():
            raise TradingHaltedError("n8n watchdog is blocking order changes")
        try:
            self.backtester_boundary().orders.cancel_order_by_id(order_id)
        except OrderExecutionError as exc:
            if is_pending_cancel_error(exc):
                return  # an earlier cancel is still being processed; that is the outcome we asked for
            record_runtime_diagnostic(
                "order_execution",
                "Live order cancellation failed",
                exc,
                severity="warning",
                source="engine",
            )
            raise

    def connect(self, payload: AccountPayload) -> None:
        api_key, secret_key = self.payload_credentials(payload)
        with self.lock:
            self.stop_streams_locked()
            self.close_api_clients_locked()
            self.name = payload.name.strip() or "Paper Account"
            self.config = self.payload_config(payload)
            self.api_key = api_key
            self.secret_key = secret_key
            self.remember = payload.remember
            self.auto_connect = payload.auto_connect
            self.auto_start_trading = payload.auto_start_trading
            self.trading_client = TradingClient(self.api_key, self.secret_key, paper=True)
            self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
            self.screener_client = ScreenerClient(self.api_key, self.secret_key)
            self.news_client = NewsClient(self.api_key, self.secret_key)
            self.top_volume_rows = []
            self.top_volume_symbols = []
            self.top_volume_last_fetch_at = 0.0
            self.top_volume_updated = ""
            self.top_volume_error = ""
            self.latest_trading_statuses = {}
            self.latest_quotes = {}
            self.halted_symbols = {}
            self.lookup_cache = {}
            self.asset_tradeability_cache = {}
            self.reentry_score_floors = {}
            self.processed_reentry_exit_ids = set()
            self.reentry_reset_at = None
            self.reentry_losses_today = {}
            self.reentry_losses_date = None
            self.reentry_open_buys = {}
            self.reentry_new_highs = {}
            self.reentry_released_sells = set()
            self.day_fills = {}
            self.day_fills_date = None
            self.day_fills_loaded = False
            self.day_fills_retry_at = 0.0
            self.day_fills_warned = False
            self.open_order_ids = set()
            self.entries_today_by_symbol = {}
            self.entries_today_date = None

        account = self.trading_client.get_account()
        with self.lock:
            self.account = model_dict(account)
            self.connected = True
            self.status = "Connected to Alpaca paper API"
            self.last_error = ""
            self.strategy_state = StrategyState()
            self.trading_enabled = False
            self.alerted_fill_ids = None
            self.consecutive_refresh_failures = 0

        self.refresh_top_volume(force=True, restart_stream=False)
        self.refresh(run_strategy=False)
        self.log("success", f"{self.name}: connected to Alpaca paper API.")

    def stop_streams_locked(self) -> None:
        for stream in (self.trade_stream,):
            if stream is not None:
                stream.stop()
        self.trade_stream = None

    def close_api_clients_locked(self) -> None:
        for client in (self.trading_client, self.data_client, self.screener_client, self.news_client):
            session = getattr(client, "_session", None)
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    record_runtime_diagnostic(
                        "api_client",
                        "API client session close failed",
                        StreamControlError(str(exc) or exc.__class__.__name__),
                        source="engine",
                    )
        self.trading_client = None
        self.data_client = None
        self.screener_client = None
        self.news_client = None

    def disconnect(self) -> None:
        with self.lock:
            self.stop_streams_locked()
            self.close_api_clients_locked()
            self.trading_enabled = False
            self.connected = False
            self.status = "Disconnected"
            self.market_clock = self.default_market_clock()
            self.top_volume_error = "Connect an account to populate the dashboard."
            self.halted_symbols = {}
            self.daily_pl_history_cache = None

    def start_trading(self) -> None:
        with self.lock:
            if not self.connected:
                raise RuntimeError("Connect to Alpaca before starting auto trading.")
            self.trading_enabled = True
            mode = "dry-run" if self.config.dry_run else "paper-order"
            self.status = f"Auto trading running in {mode} mode"
        self.log("success", self.status)
        self.refresh(run_strategy=True)

    def stop_trading(self, reason: str = "Auto trading stopped.") -> None:
        with self.lock:
            self.trading_enabled = False
            self.status = reason
        self.log("warn", reason)

    def cancel_orders(self) -> None:
        client = self.require_trading_client()
        client.cancel_orders()
        self.log("warn", "Requested cancellation of all open paper orders.")
        self.refresh(run_strategy=False)

    def purge_account(self) -> None:
        if trading_halted():
            raise TradingHaltedError("n8n watchdog is blocking order changes")
        client = self.require_trading_client()
        with self.lock:
            self.trading_enabled = False
            self.status = "Purge submitted; auto trading stopped."
        self.log("warn", "Purge requested: cancelling open orders, liquidating positions, and resetting strategy state.")

        try:
            client.cancel_orders()
            self.wait_for_open_order_cancellations(client)
        except Exception as exc:
            self.log("warn", f"Purge could not cancel all open orders before liquidation: {exc}")

        positions = [model_dict(item) for item in client.get_all_positions()]
        submitted = 0
        errors = 0
        for position in positions:
            symbol = str(position.get("symbol") or "").strip().upper()
            qty = abs(decimal_value(position.get("qty")))
            if not symbol or qty <= 0:
                continue
            side = OrderSide.BUY if str(position.get("side") or "").lower() == "short" else OrderSide.SELL
            client_order_id = f"apt-purge-{symbol.lower()}-{int(time.time() * 1000)}"
            reason = "purge reset; fractional market liquidation; history preserved"
            order = MarketOrderRequest(
                symbol=symbol,
                qty=float(qty),
                side=side,
                type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            )
            try:
                submitted_order = self.submit_order_request(order)
            except OrderExecutionError as exc:
                errors += 1
                self.record_order_intent(
                    symbol,
                    side,
                    qty,
                    "Purge Liquidation",
                    "error",
                    f"{reason}; {exc}",
                    client_order_id,
                )
                self.log("error", f"Purge liquidation rejected for {symbol}: {exc}")
                continue
            submitted += 1
            self.record_order_intent(
                symbol,
                side,
                qty,
                "Purge Liquidation",
                "submitted",
                reason,
                client_order_id,
                str(getattr(submitted_order, "id", "")),
            )

        self.reset_strategy_runtime_state()
        with self.lock:
            if submitted and errors:
                self.status = f"Purge submitted {submitted} liquidation orders; {errors} failed. Auto trading stopped."
            elif submitted:
                self.status = f"Purge submitted {submitted} liquidation orders. Auto trading stopped."
            elif errors:
                self.status = f"Purge attempted; {errors} liquidation orders failed. Auto trading stopped."
            else:
                self.status = "Purge complete; no positions to liquidate. Auto trading stopped."
        self.log("warn", self.status)
        self.refresh(run_strategy=False)

    def wait_for_open_order_cancellations(self, client: TradingClient, timeout_seconds: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            open_orders = client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=50, nested=True, direction=Sort.DESC)
            )
            if not self.flatten_orders([model_dict(item) for item in open_orders]):
                return
            time.sleep(0.5)

    def reset_strategy_runtime_state(self) -> None:
        with self.lock:
            self.strategy_state = StrategyState()
            self.entry_lock_dates = {}
            self.entry_times = {}
            self.exit_lock_dates = {}
            self.position_peak_prices = {}
            self.order_submit_holds = {}
            self.order_reject_holds = {}
            self.protective_order_reject_holds = {}
            self.asset_tradeability_cache = {}
            self.reentry_score_floors = {}
            self.processed_reentry_exit_ids = set()
            self.reentry_reset_at = datetime.now(timezone.utc)
            self.reentry_losses_today = {}
            self.reentry_losses_date = None
            self.reentry_open_buys = {}
            self.reentry_new_highs = {}
            self.reentry_released_sells = set()
            self.last_scan_log_at = 0.0
            self.last_entry_submitted_at = 0.0

    def require_trading_client(self) -> TradingClient:
        if self.trading_client is None:
            raise RuntimeError("Not connected to Alpaca.")
        return self.trading_client

    def require_data_client(self) -> StockHistoricalDataClient:
        if self.data_client is None:
            raise RuntimeError("Not connected to Alpaca.")
        return self.data_client

    def require_screener_client(self) -> ScreenerClient:
        if self.screener_client is None:
            raise RuntimeError("Not connected to Alpaca.")
        return self.screener_client

    def unavailable_daily_pl_payload(self, session_date: str, error: str = "") -> dict[str, Any]:
        return {
            "daily_pl": "Unavailable",
            "daily_pl_raw": "",
            "daily_pl_display": "Unavailable",
            "daily_pl_pct_raw": "",
            "daily_pl_pct_display": "Unavailable",
            "daily_pl_account_basis_raw": "",
            "daily_pl_account_basis_display": "Unavailable",
            "daily_pl_session_date": session_date,
            "daily_pl_source": "unavailable",
            "daily_pl_source_error": error,
        }

    def portfolio_history_request(self, session_date: str) -> GetPortfolioHistoryRequest:
        request_fields: dict[str, Any] = {
            "period": "1D",
            "timeframe": "1Min",
            "pnl_reset": "per_day",
            "extended_hours": True,
        }
        try:
            request_fields["date_end"] = date.fromisoformat(session_date)
        except (TypeError, ValueError):
            pass
        return GetPortfolioHistoryRequest(**request_fields)

    def portfolio_history_daily_pl_payload(self, client: TradingClient, session_date: str) -> dict[str, Any]:
        with self.lock:
            cached = self.daily_pl_history_cache
        now = time.monotonic()
        if (
            cached is not None
            and cached[1] == session_date
            and now - cached[0] <= PORTFOLIO_HISTORY_CACHE_SECONDS
        ):
            return dict(cached[2])

        try:
            history = client.get_portfolio_history(self.portfolio_history_request(session_date))
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            record_runtime_diagnostic(
                "account_refresh",
                "Alpaca portfolio history Daily P/L failed",
                AccountRefreshError(message),
                source="engine",
            )
            return self.unavailable_daily_pl_payload(session_date, f"Alpaca portfolio history unavailable: {message[:180]}")

        history_dict = model_dict(history)
        daily_pl = latest_metric_decimal(history_dict.get("profit_loss"))
        pct_ratio = latest_metric_decimal(history_dict.get("profit_loss_pct"))
        basis = optional_metric_decimal(history_dict.get("base_value"))
        latest_equity = latest_metric_decimal(history_dict.get("equity"))
        if basis is None and latest_equity is not None and daily_pl is not None:
            basis = latest_equity - daily_pl

        if daily_pl is None or basis is None or basis <= 0:
            payload = self.unavailable_daily_pl_payload(session_date, "Alpaca portfolio history did not return usable P/L.")
            with self.lock:
                self.daily_pl_history_cache = (now, session_date, dict(payload))
            return payload

        daily_pct = pct_ratio * Decimal("100") if pct_ratio is not None else Decimal("0")
        if daily_pct == 0 and daily_pl != 0:
            daily_pct = daily_pl / basis * Decimal("100")

        payload = {
            "daily_pl": money(daily_pl),
            "daily_pl_raw": str(daily_pl.quantize(Decimal("0.000001"))),
            "daily_pl_display": money(daily_pl),
            "daily_pl_pct_raw": str(daily_pct.quantize(Decimal("0.000001"))),
            "daily_pl_pct_display": signed_percent_value(daily_pct),
            "daily_pl_account_basis_raw": str(basis.quantize(Decimal("0.000001"))),
            "daily_pl_account_basis_display": money(basis),
            "daily_pl_session_date": session_date,
            "daily_pl_source": "alpaca_portfolio_history",
            "daily_pl_source_error": "",
        }
        with self.lock:
            self.daily_pl_history_cache = (now, session_date, dict(payload))
        return payload

    def refresh(self, run_strategy: bool | None = None, shared_bars: dict[str, list[Any]] | None = None) -> None:
        if not self.refresh_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                if not self.connected:
                    return
                config = self.config
                entry_symbols = self.mode_entry_symbols()
                should_trade = self.trading_enabled if run_strategy is None else bool(run_strategy)

            client = self.require_trading_client()
            account = client.get_account()
            clock = client.get_clock()
            positions = client.get_all_positions()
            orders = client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=50, nested=True, direction=Sort.DESC)
            )
            closed_orders = client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100, nested=True, direction=Sort.DESC)
            )

            account_dict = model_dict(account)
            position_dicts = [model_dict(item) for item in positions]
            order_dicts = [model_dict(item) for item in orders]
            closed_order_dicts = [model_dict(item) for item in closed_orders]
            position_symbols = {
                str(item.get("symbol", "")).upper()
                for item in position_dicts
                if abs(decimal_value(item.get("qty"))) > Decimal("0")
            }
            symbols = self.scan_symbols(position_symbols)

            if shared_bars is None:
                data_client = self.require_data_client()
                required_bars = required_strategy_bars(config)
                bars_data = fetch_stock_bars_chunked(data_client, symbols, required_bars, config.feed)
            else:
                bars_data = {symbol: shared_bars.get(symbol, []) for symbol in symbols}
                # Only fetch symbols the shared request did not cover; a symbol that came back
                # empty (no IEX bars yet) would otherwise be re-requested by every account each loop.
                missing_symbols = [symbol for symbol in symbols if symbol not in shared_bars]
                if missing_symbols:
                    data_client = self.require_data_client()
                    required_bars = required_strategy_bars(config)
                    bars_data.update(
                        fetch_stock_bars_chunked(data_client, missing_symbols, required_bars, config.feed)
                    )

            self.record_day_tape_bars(bars_data, "historical_refresh")
            for symbol, symbol_bars in bars_data.items():
                for bar in symbol_bars:
                    self.strategy_state.add_bar(
                        symbol,
                        getattr(bar, "close", None),
                        getattr(bar, "timestamp", None),
                        getattr(bar, "volume", None),
                        getattr(bar, "high", None),
                        getattr(bar, "low", None),
                    )
            entry_symbols = self.mode_entry_symbols()

            market_clock = self.format_market_clock(clock)
            market_open = bool(market_clock["is_open"])
            session_date = str(market_clock.get("session_date") or datetime.now().astimezone().date().isoformat())
            # The newest 100 closed orders plus every fill seen earlier in the session: the day's
            # counts and the trade table are worked out from all of it, not the last two hours.
            history_orders = self.with_todays_fills(client, closed_order_dicts, session_date, order_dicts)
            self.sync_loss_reentry_floors_from_closed_orders(history_orders)
            self.sync_entries_today_from_orders(history_orders + order_dicts)
            # Hold mode trades its own target portfolio: no stops, no flatten, no loss stop, and the
            # momentum/ORB entry loop does not run (see run_allocation_pass).
            allocation_mode = config.entry_mode == "allocation"
            # Stops and exits for real positions are managed whenever the account is connected,
            # not only while auto trading is on; Stop Trading only stops new entries.
            manage_exits = bool(config.use_bracket_orders and not config.dry_run and not allocation_mode)
            loss_breached = False if allocation_mode else self.evaluate_daily_loss_limit(config, account_dict, session_date)
            status_message = ""
            watchdog_blocked = trading_halted()
            if watchdog_blocked:
                should_trade = False
                manage_exits = False
                status_message = "Order changes paused by n8n watchdog"
            elif should_trade and config.market_hours_only and not market_open:
                should_trade = False
                status_message = "Market closed; auto trading paused by setting"
            opening_guard_detail = "" if allocation_mode else self.entry_open_guard_message(clock, config)
            closing_guard_detail = "" if allocation_mode else self.entry_close_guard_message(clock, config)
            entry_guard_detail = opening_guard_detail or closing_guard_detail
            close_flatten_detail = "" if allocation_mode else self.close_flatten_message(clock, config)
            if loss_breached:
                entry_guard_detail = self.daily_loss_detail
            elif close_flatten_detail:
                entry_guard_detail = close_flatten_detail
            entries_allowed = not entry_guard_detail
            if should_trade and entry_guard_detail:
                status_message = f"New entries paused: {entry_guard_detail}"

            # Day-trade mode loads today's picks (from disk after a restart) before any stop is
            # checked, so a held pick is protected by its own range stop, not the fallback percent.
            inplay_status = ""
            if config.entry_mode == "inplay":
                inplay_status = self.inplay_pass(clock, market_open)
                entry_symbols = self.mode_entry_symbols()
            elif uses_mover_readings(config):
                inplay_status = self.movers_pass(clock, market_open)

            position_map = {str(item.get("symbol", "")).upper(): item for item in position_dicts}
            open_positions = [item for item in position_dicts if abs(decimal_value(item.get("qty"))) > Decimal("0")]
            flat_orders = self.flatten_orders(order_dicts)
            position_symbols = {str(item.get("symbol", "")).upper() for item in open_positions}
            if should_trade or manage_exits:
                self.cancel_orphan_protective_orders(flat_orders, position_symbols)
            self.prune_position_trackers(position_symbols)
            pending_entry_symbols = {
                str(order.get("symbol", "")).upper()
                for order in flat_orders
                if self.order_role(order, position_symbols) == "Pending Entry"
            }
            slot_symbols = {
                str(item.get("symbol", "")).upper() for item in open_positions if not is_placeholder_position(item)
            }
            potential_position_count = len(slot_symbols | pending_entry_symbols)
            total_exposure = sum(abs(decimal_value(item.get("market_value"))) for item in open_positions)
            available_buying_power = decimal_value(account_dict.get("buying_power"))

            rows = []
            stop_now = False
            flattened_symbols: set[str] = set()
            flatten_reason = ""
            if loss_breached and config.flatten_on_daily_loss:
                flatten_reason = "daily loss limit flatten"
            elif close_flatten_detail:
                flatten_reason = "flatten before close"
            if flatten_reason and market_open and not config.dry_run and not watchdog_blocked:
                flatten_events, flattened_symbols = self.flatten_all_positions(position_map, flat_orders, flatten_reason)
                for level, message in flatten_events:
                    self.log(level, message)
            elif flatten_reason and market_open and config.dry_run and position_map:
                if self.dry_run_flatten_logged_session != session_date:
                    self.dry_run_flatten_logged_session = session_date
                    self.log("info", f"Dry run: would sell {len(position_map)} position(s) ({flatten_reason}).")
            if not market_open and manage_exits and not should_trade:
                for symbol in sorted(position_symbols):
                    symbol_orders = [item for item in flat_orders if str(item.get("symbol", "")).upper() == symbol]
                    for level, message in self.ensure_offhours_stop(
                        symbol, position_map.get(symbol), symbol_orders, getattr(clock, "next_open", None)
                    ):
                        self.log(level, message)
            if not allocation_mode and (should_trade or (manage_exits and market_open)):
                for symbol in symbols:
                    if symbol not in position_symbols or symbol in flattened_symbols:
                        continue
                    symbol_orders = [item for item in flat_orders if str(item.get("symbol", "")).upper() == symbol]
                    risk_account = dict(account_dict)
                    risk_account["buying_power"] = str(available_buying_power)
                    events, stop_rule, _ = self.apply_strategy(
                        symbol,
                        risk_account,
                        position_map.get(symbol),
                        potential_position_count,
                        symbol_orders,
                        total_exposure,
                        entries_allowed,
                        entry_guard_detail,
                        opening_guard_detail,
                        allow_entries=False,
                    )
                    for level, message in events:
                        self.log(level, message)
                    stop_now = stop_now or stop_rule

            allocation_status = inplay_status
            if allocation_mode:
                allocation_status = self.run_allocation_pass(
                    client, clock, account_dict, open_positions, flat_orders, closed_order_dicts, should_trade, market_open
                )
            if should_trade and not allocation_mode:
                candidates = []
                for rank, symbol in enumerate(entry_symbols):
                    if symbol in position_symbols:
                        self.clear_entry_score(symbol)
                        continue
                    symbol_orders = [item for item in flat_orders if str(item.get("symbol", "")).upper() == symbol]
                    candidate = self.entry_candidate(
                        symbol,
                        rank,
                        account_dict,
                        position_map.get(symbol),
                        potential_position_count,
                        symbol_orders,
                        entries_allowed,
                    )
                    if candidate:
                        candidates.append(candidate)

                candidates.sort(key=lambda item: (-float(item["score"]), item["rank"], item["symbol"]))
                entries_this_scan = 0
                for candidate in candidates:
                    symbol = str(candidate["symbol"])
                    if symbol in position_symbols or symbol in pending_entry_symbols:
                        self.strategy_state.last_action[symbol] = "Hold (entry already reserved)"
                        continue
                    if config.max_open_positions > 0 and potential_position_count >= config.max_open_positions:
                        self.strategy_state.last_action[symbol] = "Hold (max positions)"
                        continue
                    spacing_hold = self.entry_spacing_hold_reason(config)
                    if spacing_hold:
                        self.strategy_state.last_action[symbol] = spacing_hold
                        continue
                    if config.max_entries_per_scan > 0 and entries_this_scan >= config.max_entries_per_scan:
                        self.strategy_state.last_action[symbol] = f"Hold (entry cap {config.max_entries_per_scan}/scan)"
                        continue
                    symbol_orders = [item for item in flat_orders if str(item.get("symbol", "")).upper() == symbol]
                    risk_account = dict(account_dict)
                    risk_account["buying_power"] = str(available_buying_power)
                    events, stop_rule, reservation = self.apply_strategy(
                        symbol,
                        risk_account,
                        position_map.get(symbol),
                        potential_position_count,
                        symbol_orders,
                        total_exposure,
                        entries_allowed,
                        entry_guard_detail,
                        opening_guard_detail,
                    )
                    for level, message in events:
                        self.log(level, message)
                    stop_now = stop_now or stop_rule
                    if reservation and reservation.get("side") == "buy":
                        entries_this_scan += 1
                        self.last_entry_submitted_at = time.monotonic()
                        reserved_symbol = str(reservation.get("symbol") or symbol).upper()
                        reserved_notional = decimal_value(reservation.get("notional"))
                        if reserved_symbol not in position_symbols and reserved_symbol not in pending_entry_symbols:
                            pending_entry_symbols.add(reserved_symbol)
                            potential_position_count += 1
                        total_exposure += reserved_notional
                        available_buying_power = max(Decimal("0"), available_buying_power - reserved_notional)

            for symbol in symbols:
                if should_trade and not allocation_mode and symbol not in position_symbols and symbol not in entry_symbols:
                    self.clear_entry_score(symbol)
                    if symbol in MARKET_PROXY_SYMBOLS and self.config.use_top_volume_symbols:
                        self.strategy_state.last_action[symbol] = "Hold (market proxy only)"
                rows.append(self.snapshot(symbol).as_dict())

            if should_trade and time.monotonic() - self.last_scan_log_at >= 60:
                self.last_scan_log_at = time.monotonic()
                self.log(
                    "info",
                    (
                        f"Scan heartbeat: {len(symbols)} symbols, "
                        f"{potential_position_count} positions/pending, "
                        f"{money(available_buying_power)} buying power."
                    ),
                )

            equity = decimal_value(account_dict.get("equity"))
            last_equity = decimal_value(account_dict.get("last_equity"))
            daily_pl_payload = self.portfolio_history_daily_pl_payload(client, session_date)
            all_trade_rows = self.trade_history_rows(history_orders, limit=None)
            trade_history_rows = all_trade_rows[:TRADE_HISTORY_DISPLAY_ROWS]
            self.alert_new_fills(closed_order_dicts)
            realized_account_basis = decimal_value(daily_pl_payload.get("daily_pl_account_basis_raw"))
            if realized_account_basis <= 0:
                realized_account_basis = last_equity if last_equity > 0 else equity
            # Summed over every fill of the day, not only the rows the table shows.
            realized_pl = self.daily_realized_pl_summary(all_trade_rows, realized_account_basis, session_date)

            with self.lock:
                self.account = account_dict | daily_pl_payload | {
                    "realized_pl": str(realized_pl["value"]),
                    "realized_pl_raw": str(realized_pl["value"]),
                    "realized_pl_display": money(realized_pl["value"]),
                    "realized_pl_pct": str(realized_pl["percent"]),
                    "realized_pl_pct_raw": str(realized_pl["percent"]),
                    "realized_pl_pct_display": signed_percent_value(realized_pl["percent"]),
                    "realized_pl_account_basis": str(realized_pl["account_basis"]),
                    "realized_pl_account_basis_display": money(realized_pl["account_basis"]),
                    "realized_pl_trade_cost_basis": str(realized_pl["trade_cost_basis"]),
                    "realized_pl_trade_cost_basis_display": money(realized_pl["trade_cost_basis"]),
                    "realized_pl_session_date": str(realized_pl["session_date"]),
                    "equity_display": money(equity),
                    "buying_power_display": money(account_dict.get("buying_power")),
                    "cash_display": money(account_dict.get("cash")),
                    "cash_percent_raw": str(cash_percent_of_equity(account_dict.get("cash"), equity)),
                    "cash_percent_display": f"{cash_percent_of_equity(account_dict.get('cash'), equity)}%",
                }
                self.positions = [self.format_position(item) for item in position_dicts]
                self.orders = [self.format_order(item, position_symbols) for item in flat_orders]
                self.protection_rows = self.protection_status_rows(open_positions, flat_orders)
                self.trade_history = trade_history_rows
                self.strategy_rows = rows
                self.market_clock = market_clock
                self.last_refresh = datetime.now().strftime("%I:%M:%S %p")
                self.last_error = ""
                if stop_now:
                    self.trading_enabled = False
                    self.status = "Auto trading stopped by risk rule"
                elif watchdog_blocked:
                    self.status = status_message
                elif loss_breached:
                    self.status = f"Daily loss limit hit: {self.daily_loss_detail}"
                elif close_flatten_detail:
                    self.status = f"Selling before the close: {close_flatten_detail}"
                elif status_message:
                    self.status = status_message
                elif allocation_status:
                    self.status = allocation_status
                elif self.trading_enabled and market_clock["is_open"]:
                    mode = "dry-run" if self.config.dry_run else "paper-order"
                    self.status = f"Auto trading running in {mode} mode"
            self.record_day_tape_scan(
                should_trade=should_trade,
                entries_allowed=entries_allowed,
                entry_guard_detail=entry_guard_detail,
                market_clock=market_clock,
                account=account_dict,
                positions=position_dicts,
                open_orders=flat_orders,
                closed_orders=closed_order_dicts,
                strategy_rows=rows,
            )
            clear_runtime_diagnostics(area="account_refresh", source="engine")
            self.consecutive_refresh_failures = 0
        except Exception as exc:
            self.record_runtime_exception(
                "account_refresh",
                "Account refresh failed",
                AccountRefreshError(str(exc) or exc.__class__.__name__),
                severity="error",
                log_level="error",
                set_last_error=True,
            )
            self.consecutive_refresh_failures += 1
            if self.consecutive_refresh_failures == 3:
                self.alert("problem", "Refresh failing", f"3 refreshes in a row failed: {exc}",
                           key="refresh-failing", ttl_seconds=900, urgency="critical")
        finally:
            self.refresh_lock.release()

    def split_adjusted_previous_closes(self, data_client: Any, snapshots: dict[str, Any], feed: str) -> dict[str, float]:
        """Previous-session closes on the same split basis as today's price, fetched once per symbol per session.

        A snapshot's previous_daily_bar is raw, so a split reads as a huge move (SOXX's 3:1 split
        on 2026-11-05 showed as -70.7%). Split-adjusted bars can also apply a split before it shows
        in trading (CDT's 1:20 reverse split read as -95.7% while it still traded near $0.04). So
        the raw and adjusted closes are both candidates, and the one nearer today's open wins: a
        real split leaves a 2x-or-more gap at the open, an ordinary overnight gap does not.
        """
        session_bars = {
            str(symbol).upper(): model_dict(getattr(snapshot, "daily_bar", None)) for symbol, snapshot in snapshots.items()
        }
        sessions = {symbol: daily_bar_session_date(bar.get("timestamp")) for symbol, bar in session_bars.items()}
        sessions = {symbol: session for symbol, session in sessions.items() if session}
        with self.lock:
            cache = dict(self.previous_close_cache)
        missing = [symbol for symbol, session in sessions.items() if (symbol, session) not in cache]
        if missing:
            try:
                bars = fetch_daily_bars_chunked(data_client, missing, feed)
            except Exception as exc:
                record_runtime_diagnostic(
                    "market_data",
                    "Split-adjusted daily bars failed; movers use raw previous closes",
                    MarketDataError(str(exc) or exc.__class__.__name__),
                    source="engine",
                )
                bars = None
            if bars is not None:
                for symbol in missing:
                    session = sessions[symbol]
                    earlier = [
                        bar for bar in bars.get(symbol, []) if daily_bar_session_date(getattr(bar, "timestamp", None)) < session
                    ]
                    adjusted = market_overview.number(getattr(earlier[-1], "close", None)) if earlier else None
                    raw = market_overview.number(model_dict(getattr(snapshots.get(symbol), "previous_daily_bar", None)).get("close"))
                    cache[(symbol, session)] = market_overview.nearer_previous_close(
                        market_overview.number(session_bars[symbol].get("open")), raw, adjusted
                    )
                oldest = min(sessions.values())
                with self.lock:
                    self.previous_close_cache = {key: value for key, value in cache.items() if key[1] >= oldest}
        return {
            symbol: close
            for symbol, session in sessions.items()
            if (close := cache.get((symbol, session))) is not None
        }

    def refresh_top_volume(self, force: bool = False, restart_stream: bool = True) -> None:
        with self.lock:
            if not self.connected:
                self.top_volume_error = "Connect an account to populate the dashboard."
                return
            now = time.monotonic()
            cache_seconds = TOP_VOLUME_FORCE_COOLDOWN_SECONDS if force else TOP_VOLUME_CACHE_SECONDS
            if self.top_volume_rows and now - self.top_volume_last_fetch_at < cache_seconds:
                return
            feed = self.config.feed
            data_client = self.data_client
            screener_client = self.screener_client
            existing_rows = {row.get("symbol"): row for row in self.top_volume_rows}
            cached_rows = load_dashboard_cache_rows()
            latest_statuses = dict(self.latest_trading_statuses)
            halted_symbols = dict(self.halted_symbols)

        if data_client is None or screener_client is None:
            with self.lock:
                self.top_volume_error = "Connect an account to populate the dashboard."
            return

        try:
            ranked = fetch_most_active_symbols(screener_client, DASHBOARD_TOP_LIMIT)
            snapshot_symbols = [str(item.get("symbol") or "").strip().upper() for item in ranked]
            snapshots = fetch_stock_snapshots_chunked(data_client, snapshot_symbols, feed)
            previous_closes = self.split_adjusted_previous_closes(data_client, snapshots, feed)
            updated_at = datetime.now().strftime("%b %d, %I:%M:%S %p")

            rows: list[dict[str, Any]] = []
            symbols: list[str] = []
            for index, item in enumerate(ranked[:DASHBOARD_TOP_LIMIT], start=1):
                symbol = str(item.get("symbol", "")).strip().upper()
                if not symbol:
                    continue
                symbols.append(symbol)
                previous = existing_rows.get(symbol) or cached_rows.get(symbol, {})
                status = latest_statuses.get(symbol, {})
                halted = symbol in halted_symbols
                daily_volume_raw = whole_number_value(item.get("daily_volume_raw"))
                trade_count_raw = whole_number_value(item.get("trade_count_raw"))
                snapshot = snapshots.get(symbol)
                daily_bar = model_dict(getattr(snapshot, "daily_bar", None))
                latest_trade = model_dict(getattr(snapshot, "latest_trade", None))
                last_price_raw = latest_trade.get("price") or daily_bar.get("close") or previous.get("last_price_raw", 0)
                previous_close_raw = previous_closes.get(symbol)
                if previous_close_raw is None:
                    previous_close_raw = model_dict(getattr(snapshot, "previous_daily_bar", None)).get("close")
                change_pct_raw = market_overview.percent_change(
                    market_overview.number(last_price_raw), market_overview.number(previous_close_raw)
                )
                rows.append(
                    {
                        "rank": index,
                        "rank_raw": index,
                        "symbol": symbol,
                        "total_volume": whole_number(daily_volume_raw),
                        "total_volume_raw": daily_volume_raw,
                        "daily_volume": whole_number(daily_volume_raw),
                        "daily_volume_raw": daily_volume_raw,
                        "trade_count": whole_number(trade_count_raw),
                        "trade_count_raw": trade_count_raw,
                        "feed_daily_volume_raw": whole_number_value(daily_bar.get("volume")),
                        "feed_daily_bar_date": daily_bar_session_date(daily_bar.get("timestamp")),
                        "buy_volume": previous.get("buy_volume", "0"),
                        "buy_volume_raw": previous.get("buy_volume_raw", 0),
                        "sell_volume": previous.get("sell_volume", "0"),
                        "sell_volume_raw": previous.get("sell_volume_raw", 0),
                        "unclassified_volume": previous.get("unclassified_volume", "0"),
                        "unclassified_volume_raw": previous.get("unclassified_volume_raw", 0),
                        "stream_volume": previous.get("stream_volume", "0"),
                        "stream_volume_raw": previous.get("stream_volume_raw", 0),
                        "last_trade_side": previous.get("last_trade_side", "-"),
                        "last_price": money_or_dash(last_price_raw),
                        "last_price_raw": last_price_raw,
                        "previous_close_raw": previous_close_raw,
                        "change_pct_raw": change_pct_raw,
                        "minute_volume": previous.get("minute_volume", "-"),
                        "minute_volume_raw": previous.get("minute_volume_raw", 0),
                        "last_update": previous.get("last_update", "-"),
                        "trading_status": self.trading_status_label(status),
                        "halted": halted,
                        "halted_raw": 1 if halted else 0,
                        "halt_reason": halted_symbols.get(symbol, {}).get("detail", ""),
                    }
                )

            if not rows:
                raise RuntimeError("No Alpaca most-active volume data returned.")

            with self.lock:
                old_symbols = list(self.top_volume_symbols)
                self.top_volume_rows = rows
                self.top_volume_symbols = symbols
                self.top_volume_last_fetch_at = time.monotonic()
                self.top_volume_updated = updated_at
                self.top_volume_error = ""
            self.persist_dashboard_cache(force=True)
            append_day_tape_event(
                "top_volume_snapshot",
                {
                    "source": TOP_VOLUME_SOURCE,
                    "feed": feed,
                    "force": force,
                    "updated_at": updated_at,
                    "symbols": symbols,
                    "rows": compact_top_volume_rows(rows),
                },
            )

            if restart_stream and symbols != old_symbols:
                self.log("info", "Top-volume symbols refreshed; shared market-data websocket will resubscribe.")

        except Exception as exc:
            with self.lock:
                self.top_volume_error = str(exc)
            append_day_tape_event(
                "top_volume_error",
                {"source": TOP_VOLUME_SOURCE, "feed": feed, "error": str(exc)},
            )
            self.log("error", f"Top-volume dashboard refresh failed: {exc}")

    def record_day_tape_bars(self, bars_data: dict[str, list[Any]], source: str) -> None:
        try:
            for symbol_bars in bars_data.values():
                for bar in symbol_bars:
                    append_market_bar_once(bar, feed=self.config.feed, source=source)
        except (OSError, TypeError, ValueError) as exc:
            self.record_runtime_exception(
                "day_tape",
                "Historical bar day-tape write failed",
                ReplayPersistenceError(str(exc) or exc.__class__.__name__),
            )

    def record_day_tape_scan(
        self,
        should_trade: bool,
        entries_allowed: bool,
        entry_guard_detail: str,
        market_clock: dict[str, Any],
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        open_orders: list[dict[str, Any]],
        closed_orders: list[dict[str, Any]],
        strategy_rows: list[dict[str, Any]],
    ) -> None:
        try:
            if not bool(market_clock.get("is_open")):
                return
            # Each scan record is large (every symbol's indicators plus orders), so keep one per
            # clock minute (bars are minutely, so the backtester still sees every bar) plus one
            # whenever positions or open orders change.
            minute_bucket = int(time.time() // DAY_TAPE_SCAN_INTERVAL_SECONDS)
            signature = (
                tuple(sorted(str(item.get("symbol") or "") for item in positions)),
                tuple(sorted(str(item.get("id") or item.get("client_order_id") or "") for item in open_orders)),
            )
            if minute_bucket == self.last_day_tape_scan_bucket and signature == self.last_day_tape_scan_signature:
                return
            self.last_day_tape_scan_bucket = minute_bucket
            self.last_day_tape_scan_signature = signature
            with self.lock:
                symbol_source = self.trading_symbol_source()
                top_volume_symbols = list(self.top_volume_symbols[:DASHBOARD_TOP_LIMIT])
                top_volume_rows = compact_top_volume_rows(self.top_volume_rows)
                top_volume_updated_at = self.top_volume_updated
            append_day_tape_event(
                "strategy_scan",
                {
                    "trading_enabled": self.trading_enabled,
                    "should_trade": should_trade,
                    "entries_allowed": entries_allowed,
                    "entry_guard_detail": entry_guard_detail,
                    "market_clock": clean_day_tape_value(market_clock),
                    "config": self.config.model_dump(mode="json"),
                    "symbol_source": symbol_source,
                    "top_volume_source": TOP_VOLUME_SOURCE if top_volume_symbols else "",
                    "top_volume_updated_at": top_volume_updated_at,
                    "top_volume_symbols": top_volume_symbols,
                    "top_volume_rows": top_volume_rows,
                    "account": compact_account_snapshot(account),
                    "positions": compact_positions(positions),
                    "open_orders": compact_orders(open_orders),
                    "closed_orders": compact_orders(closed_orders),
                    "strategy": clean_day_tape_value(strategy_rows),
                },
            )
        except (OSError, TypeError, ValueError) as exc:
            self.record_runtime_exception(
                "day_tape",
                "Strategy scan day-tape write failed",
                ReplayPersistenceError(str(exc) or exc.__class__.__name__),
            )

    def apply_shared_top_volume(
        self,
        rows: list[dict[str, Any]],
        symbols: list[str],
        updated: str,
        error: str = "",
    ) -> None:
        with self.lock:
            self.top_volume_rows = [dict(row) for row in rows]
            self.top_volume_symbols = list(symbols)
            self.top_volume_last_fetch_at = time.monotonic()
            self.top_volume_updated = updated
            self.top_volume_error = error

    def apply_daily_universe(self, symbols: list[str], meta: dict[str, Any]) -> None:
        with self.lock:
            self.daily_universe_symbols = list(symbols)
            self.daily_universe_meta = dict(meta)

    def ingest_market_bar(self, bar: Any, daily: bool = False) -> None:
        raw = model_dict(bar)
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return
        if not daily:
            scan_symbols = set(self.scan_symbols())
            if symbol in scan_symbols:
                self.strategy_state.add_bar(
                    symbol,
                    raw.get("close"),
                    raw.get("timestamp"),
                    raw.get("volume"),
                    raw.get("high"),
                    raw.get("low"),
                )
        self.update_dashboard_bar(bar, daily=daily)

    def update_dashboard_bar(self, bar: Any, daily: bool = False) -> None:
        raw = model_dict(bar)
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return
        close = raw.get("close")
        volume = raw.get("volume")
        timestamp = raw.get("timestamp")

        updated = False
        with self.lock:
            for row in self.top_volume_rows:
                if row.get("symbol") != symbol:
                    continue
                if close is not None:
                    row["last_price"] = money_or_dash(close)
                    row["last_price_raw"] = float(decimal_value(close))
                if daily:
                    raw_volume = whole_number_value(volume)
                    row["daily_volume"] = whole_number(raw_volume)
                    row["daily_volume_raw"] = raw_volume
                    row["total_volume"] = whole_number(raw_volume)
                    row["total_volume_raw"] = raw_volume
                else:
                    raw_volume = whole_number_value(volume)
                    row["minute_volume"] = whole_number(raw_volume)
                    row["minute_volume_raw"] = raw_volume
                row["last_update"] = format_timestamp(timestamp) or datetime.now().strftime("%I:%M:%S %p")
                updated = True
                break
        if updated:
            self.persist_dashboard_cache()

    def update_dashboard_quote(self, quote: Any) -> None:
        raw = model_dict(quote)
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return
        with self.lock:
            self.latest_quotes[symbol] = raw

    def update_dashboard_trade(self, trade: Any, count_volume: bool = True) -> None:
        raw = model_dict(trade)
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return
        price = decimal_value(raw.get("price"))
        size = whole_number_value(raw.get("size"))
        if price <= 0 or size <= 0:
            return

        updated = False
        with self.lock:
            if count_volume:  # live stream trades only; REST backfills can carry hours-old "latest" trades
                self.remember_stream_trade(symbol, price, raw.get("timestamp"))
            quote = self.latest_quotes.get(symbol, {})
            for row in self.top_volume_rows:
                if row.get("symbol") != symbol:
                    continue
                previous_price = decimal_value(row.get("last_price_raw"))
                side = self.classify_trade_side(price, quote, previous_price)
                if count_volume and side == "buy":
                    row["buy_volume_raw"] = int(row.get("buy_volume_raw", 0)) + size
                    row["last_trade_side"] = "Buy"
                elif count_volume and side == "sell":
                    row["sell_volume_raw"] = int(row.get("sell_volume_raw", 0)) + size
                    row["last_trade_side"] = "Sell"
                elif count_volume:
                    row["unclassified_volume_raw"] = int(row.get("unclassified_volume_raw", 0)) + size
                    row["last_trade_side"] = "Unclassified"
                else:
                    existing_side = str(row.get("last_trade_side") or "")
                    row["last_trade_side"] = existing_side if existing_side and existing_side != "-" else "REST"

                if count_volume:
                    row["stream_volume_raw"] = int(row.get("stream_volume_raw", 0)) + size
                row["buy_volume"] = whole_number(row.get("buy_volume_raw", 0))
                row["sell_volume"] = whole_number(row.get("sell_volume_raw", 0))
                row["unclassified_volume"] = whole_number(row.get("unclassified_volume_raw", 0))
                row["stream_volume"] = whole_number(row.get("stream_volume_raw", 0))
                row["last_price"] = money_or_dash(price)
                row["last_price_raw"] = float(price)
                row["last_update"] = format_timestamp(raw.get("timestamp")) or datetime.now().strftime("%I:%M:%S %p")
                updated = True
                break
        if updated:
            self.persist_dashboard_cache()

    def classify_trade_side(self, price: Decimal, quote: dict[str, Any], previous_price: Decimal | None = None) -> str:
        bid = decimal_value(quote.get("bid_price"))
        ask = decimal_value(quote.get("ask_price"))
        if ask > 0 and price >= ask:
            return "buy"
        if bid > 0 and price <= bid:
            return "sell"
        if bid > 0 and ask > 0:
            midpoint = (bid + ask) / Decimal("2")
            if price > midpoint:
                return "buy"
            if price < midpoint:
                return "sell"
        if previous_price and previous_price > 0:
            if price > previous_price:
                return "buy"
            if price < previous_price:
                return "sell"
        return "unknown"

    def persist_dashboard_cache(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.dashboard_cache_last_save < 5:
            return
        with self.lock:
            rows = [dict(row) for row in self.top_volume_rows]
            self.dashboard_cache_last_save = now
        save_dashboard_cache_rows(rows)

    def update_trading_status(self, status: Any) -> None:
        raw = model_dict(status)
        symbol = str(raw.get("symbol", "")).strip().upper()
        if not symbol:
            return

        detail = self.trading_status_label(raw)
        halted = self.is_halt_status(raw)
        event = {
            "symbol": symbol,
            "detail": detail,
            "status_code": str(raw.get("status_code", "")),
            "reason_code": str(raw.get("reason_code", "")),
            "timestamp": format_timestamp(raw.get("timestamp")),
        }

        with self.lock:
            self.latest_trading_statuses[symbol] = event
            if halted:
                self.halted_symbols[symbol] = event
            else:
                self.halted_symbols.pop(symbol, None)

            for row in self.top_volume_rows:
                if row.get("symbol") != symbol:
                    continue
                row["trading_status"] = detail
                row["halted"] = halted
                row["halted_raw"] = 1 if halted else 0
                row["halt_reason"] = detail if halted else ""
                break

        if halted:
            self.log("warn", f"{symbol} trading halt/status alert: {detail}")

    def lookup_symbol(self, symbol: str) -> dict[str, Any]:
        cleaned = clean_symbols([symbol])
        if not cleaned:
            raise RuntimeError("Enter a valid ticker symbol.")
        target = cleaned[0]

        with self.lock:
            if not self.connected:
                raise RuntimeError("Connect an account before looking up a ticker.")
            cached = self.lookup_cache.get(target)
            if cached and time.monotonic() - cached[0] < LOOKUP_CACHE_SECONDS:
                return cached[1]
            client = self.data_client
            feed = self.config.feed

        if client is None:
            raise RuntimeError("Connect an account before looking up a ticker.")

        snapshots = client.get_stock_snapshot(
            StockSnapshotRequest(symbol_or_symbols=target, feed=DataFeed(feed))
        )
        snapshot = snapshots.get(target) if isinstance(snapshots, dict) else None
        if snapshot is None:
            raise RuntimeError(f"No snapshot data returned for {target}.")

        payload = self.format_lookup_snapshot(target, snapshot, feed)
        with self.lock:
            self.lookup_cache[target] = (time.monotonic(), payload)
        append_day_tape_event("lookup_snapshot", clean_day_tape_value(payload))
        return payload

    def format_lookup_snapshot(self, symbol: str, snapshot: Any, feed: str) -> dict[str, Any]:
        latest_trade = self.format_trade(getattr(snapshot, "latest_trade", None))
        latest_quote = self.format_quote(getattr(snapshot, "latest_quote", None))
        minute_bar = self.format_bar(getattr(snapshot, "minute_bar", None))
        daily_bar = self.format_bar(getattr(snapshot, "daily_bar", None))
        previous_daily_bar = self.format_bar(getattr(snapshot, "previous_daily_bar", None))
        return {
            "symbol": symbol,
            "feed": feed,
            "fetched_at": datetime.now().strftime("%b %d, %I:%M:%S %p"),
            "latest_trade": latest_trade,
            "latest_quote": latest_quote,
            "minute_bar": minute_bar,
            "daily_bar": daily_bar,
            "previous_daily_bar": previous_daily_bar,
            "daily_change": signed_percent(daily_bar.get("close_raw"), previous_daily_bar.get("close_raw")),
        }

    def format_trade(self, trade: Any) -> dict[str, Any]:
        raw = model_dict(trade)
        return {
            "price": money_or_dash(raw.get("price")),
            "size": whole_number(raw.get("size")),
            "time": format_timestamp(raw.get("timestamp")),
            "exchange": str(raw.get("exchange") or ""),
        }

    def format_quote(self, quote: Any) -> dict[str, Any]:
        raw = model_dict(quote)
        bid = decimal_value(raw.get("bid_price"))
        ask = decimal_value(raw.get("ask_price"))
        spread = ask - bid if bid > 0 and ask > 0 else None
        return {
            "bid": money_or_dash(raw.get("bid_price")),
            "bid_size": whole_number(raw.get("bid_size")),
            "ask": money_or_dash(raw.get("ask_price")),
            "ask_size": whole_number(raw.get("ask_size")),
            "spread": money_or_dash(spread),
            "time": format_timestamp(raw.get("timestamp")),
        }

    def format_bar(self, bar: Any) -> dict[str, Any]:
        raw = model_dict(bar)
        return {
            "open": money_or_dash(raw.get("open")),
            "high": money_or_dash(raw.get("high")),
            "low": money_or_dash(raw.get("low")),
            "close": money_or_dash(raw.get("close")),
            "close_raw": raw.get("close"),
            "volume": whole_number(raw.get("volume")),
            "trades": whole_number(raw.get("trade_count")),
            "vwap": money_or_dash(raw.get("vwap")),
            "time": format_timestamp(raw.get("timestamp")),
        }

    def trading_status_label(self, status: dict[str, Any]) -> str:
        if not status:
            return "No halt signal"
        parts = [
            str(status.get("status_message") or status.get("detail") or "").strip(),
            str(status.get("reason_message") or "").strip(),
        ]
        label = " / ".join(part for part in parts if part)
        if label:
            return label
        codes = [str(status.get("status_code") or "").strip(), str(status.get("reason_code") or "").strip()]
        return " / ".join(code for code in codes if code) or "Status update"

    def is_halt_status(self, status: dict[str, Any]) -> bool:
        text = " ".join(
            str(status.get(key, ""))
            for key in ("status_code", "status_message", "reason_code", "reason_message", "detail")
        ).lower()
        if not text:
            return False
        if any(keyword in text for keyword in RESUME_KEYWORDS):
            return False
        return any(keyword in text for keyword in HALT_KEYWORDS)

    def halt_summary(self) -> dict[str, Any]:
        with self.lock:
            items = list(self.halted_symbols.values())
        return {
            "count": len(items),
            "status": "Halt detected" if items else "No active halts detected",
            "detail": "Subscribed dashboard symbols." if not items else "; ".join(
                f"{item.get('symbol')}: {item.get('detail')}" for item in items[:3]
            ),
            "items": items,
        }

    def dashboard_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "account_id": self.account_id,
                "account_name": self.name,
                "connected": self.connected,
                "status": self.status,
                "trading_enabled": self.trading_enabled,
                "last_refresh": self.last_refresh,
                "profile": self.config.profile,
                "market_clock": self.market_clock,
                "top_volume": list(self.top_volume_rows),
                "top_volume_source": TOP_VOLUME_SOURCE,
                "top_volume_updated": self.top_volume_updated,
                "top_volume_error": self.top_volume_error,
                "top_volume_cache_seconds": TOP_VOLUME_CACHE_SECONDS,
                "halt_summary": self.halt_summary(),
            }

    def default_market_clock(self) -> dict[str, Any]:
        return {
            "status": "Not connected",
            "is_open": False,
            "detail": "Connect an account to read Alpaca market hours.",
            "next_open": "",
            "next_close": "",
            "session_date": "",
        }

    def market_clock_session_date(self, clock: Any) -> str:
        timestamp = getattr(clock, "timestamp", None)
        now_local = timestamp.astimezone() if hasattr(timestamp, "astimezone") else datetime.now().astimezone()
        if bool(getattr(clock, "is_open", False)):
            return now_local.date().isoformat()
        next_open = getattr(clock, "next_open", None)
        if hasattr(next_open, "astimezone") and now_local < next_open.astimezone():
            candidate = next_open.astimezone().date() - timedelta(days=1)
            while candidate.weekday() >= 5:
                candidate -= timedelta(days=1)
            return candidate.isoformat()
        return now_local.date().isoformat()

    def format_market_clock(self, clock: Any) -> dict[str, Any]:
        is_open = bool(getattr(clock, "is_open", False))
        next_open = getattr(clock, "next_open", None)
        next_close = getattr(clock, "next_close", None)
        detail_time = next_close if is_open else next_open
        detail_label = "Next close" if is_open else "Next open"
        detail = f"{detail_label}: {self.format_clock_time(detail_time)}" if detail_time else "No upcoming session returned."
        return {
            "status": "Open" if is_open else "Closed",
            "is_open": is_open,
            "detail": detail,
            "next_open": self.format_clock_time(next_open),
            "next_close": self.format_clock_time(next_close),
            "session_date": self.market_clock_session_date(clock),
        }

    def format_clock_time(self, value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "astimezone"):
            return value.astimezone().strftime("%b %d, %I:%M %p %Z")
        return str(value)

    def clock_now(self, clock: Any, reference: Any) -> datetime:
        """The broker clock's timestamp when it is timezone-aware, else the local wall clock."""
        stamp = getattr(clock, "timestamp", None)
        if isinstance(stamp, datetime) and stamp.tzinfo is not None:
            return stamp
        tz = getattr(reference, "tzinfo", None)
        return datetime.now(tz) if tz else datetime.now()

    def entry_open_guard_message(self, clock: Any, config: AppConfig) -> str:
        guard_minutes = int(config.entry_open_guard_minutes or 0)
        if guard_minutes <= 0 or not bool(getattr(clock, "is_open", False)):
            return ""
        next_close = getattr(clock, "next_close", None)
        if not hasattr(next_close, "astimezone"):
            return ""
        # NYSE opens at 09:30 ET even on half days (13:00 close), so derive the open from the
        # close's ET date rather than "close minus 6.5 hours".
        close_et = next_close.astimezone(MARKET_TIMEZONE) if getattr(next_close, "tzinfo", None) else next_close
        session_open = close_et.replace(hour=9, minute=30, second=0, microsecond=0)
        now = self.clock_now(clock, next_close)
        seconds_open = (now - session_open).total_seconds()
        if seconds_open < 0 or seconds_open > guard_minutes * 60:
            return ""
        minutes_open = max(0, int(seconds_open // 60))
        return f"market opened {minutes_open} min ago; open guard is {guard_minutes} min"

    def entry_close_guard_message(self, clock: Any, config: AppConfig) -> str:
        guard_minutes = int(config.entry_close_guard_minutes or 0)
        if guard_minutes <= 0 or not bool(getattr(clock, "is_open", False)):
            return ""
        next_close = getattr(clock, "next_close", None)
        if not hasattr(next_close, "astimezone"):
            return ""
        now = self.clock_now(clock, next_close)
        seconds_left = (next_close - now).total_seconds()
        if seconds_left < 0 or seconds_left > guard_minutes * 60:
            return ""
        minutes_left = max(0, int((seconds_left + 59) // 60))
        return f"market closes in {minutes_left} min; entry guard is {guard_minutes} min"

    def close_flatten_message(self, clock: Any, config: AppConfig) -> str:
        minutes = int(config.flatten_before_close_minutes or 0)
        if config.entry_mode == "inplay" and minutes <= 0:
            minutes = INPLAY_DEFAULT_FLATTEN_MINUTES  # a day trade never stays overnight
        if minutes <= 0 or not bool(getattr(clock, "is_open", False)):
            return ""
        next_close = getattr(clock, "next_close", None)
        if not hasattr(next_close, "astimezone"):
            return ""
        seconds_left = (next_close - self.clock_now(clock, next_close)).total_seconds()
        if seconds_left < 0 or seconds_left > minutes * 60:
            return ""
        return f"market closes in {max(0, int((seconds_left + 59) // 60))} min; selling everything {minutes} min before the close"

    # ----- Day-trade mode (entry_mode "inplay") ------------------------------------------------

    INPLAY_RECENT_ACTIVES_PATH = APP_DIR / "inplay_recent_actives.json"
    INPLAY_PICKS_PATH = APP_DIR / "inplay_picks.json"
    INPLAY_RECENT_SESSIONS = 10
    INPLAY_SIP_DELAY_MINUTES = 16

    def inplay_ready_at(self, today: date, config: AppConfig) -> datetime:
        """When today's opening range can be read from consolidated data (range end + SIP delay)."""
        open_et = datetime.combine(today, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30)
        return open_et + timedelta(minutes=config.inplay_range_minutes + self.INPLAY_SIP_DELAY_MINUTES)

    def inplay_recent_actives(self) -> list[str]:
        try:
            payload = json.loads(self.INPLAY_RECENT_ACTIVES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        sessions = payload.get("sessions") if isinstance(payload, dict) else None
        symbols: list[str] = []
        for _, items in sorted((sessions or {}).items())[-self.INPLAY_RECENT_SESSIONS:]:
            symbols.extend(str(item).upper() for item in items or [])
        return clean_symbol_list(symbols)

    def remember_inplay_actives(self, today: date, symbols: list[str]) -> None:
        if not symbols:
            return
        try:
            payload = json.loads(self.INPLAY_RECENT_ACTIVES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        sessions = dict(payload.get("sessions") or {}) if isinstance(payload, dict) else {}
        sessions[today.isoformat()] = clean_symbol_list(symbols)
        keep = dict(sorted(sessions.items())[-self.INPLAY_RECENT_SESSIONS:])
        try:
            write_private_json(self.INPLAY_RECENT_ACTIVES_PATH, {"sessions": keep})
        except OSError as exc:
            self.log("warn", f"Day trade: could not save the recent most-active list: {exc}")

    def inplay_tape_actives(self, today: date) -> list[str]:
        """Most-active symbols from the recorded day tapes of recent sessions.

        The tapes record the most-active list about once a minute. A handful of points spread
        through each file are sampled (seek, then read forward to the next snapshot), so a session's
        list is covered without reading hundreds of megabytes. This fills the recent list on a fresh
        install and on days the app was not running.
        """
        symbols: list[str] = []
        try:
            tapes = sorted(path for path in DAY_TAPE_DIR.glob("tape-*.jsonl") if path.stem < f"tape-{today:%Y%m%d}")
        except OSError:
            return symbols
        for path in tapes[-self.INPLAY_RECENT_SESSIONS:]:
            try:
                size = path.stat().st_size
                with path.open("rb") as handle:
                    for step in range(12):
                        handle.seek(size * step // 12)
                        if step:
                            handle.readline()  # skip the partial line after the seek
                        read = 0
                        for raw in handle:
                            read += len(raw)
                            if read > 5_000_000:
                                break
                            if b'"top_volume_snapshot"' not in raw[:200]:
                                continue
                            try:
                                event = json.loads(raw)
                            except ValueError:
                                break
                            payload = event.get("payload") or {}
                            symbols.extend(str(item).upper() for item in payload.get("symbols", [])[:DASHBOARD_TOP_LIMIT])
                            break
            except OSError:
                continue
        return clean_symbol_list(symbols)

    def save_inplay_picks(self, today: date, picks: list[inplay_logic.Pick], checked: int, rejected: dict[str, int]) -> None:
        """Keep today's picks on disk so a restart reloads them instead of ranking again."""
        try:
            payload = json.loads(self.INPLAY_PICKS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload[self.account_id] = {
            "session": today.isoformat(),
            "checked": checked,
            "rejected": rejected,
            "picks": [
                {key: str(getattr(pick, key)) for key in ("symbol", "rank", "high", "low", "open", "close", "relative_volume", "atr_percent", "dollar_volume", "stop")}
                for pick in picks
            ],
        }
        try:
            write_private_json(self.INPLAY_PICKS_PATH, payload)
        except OSError as exc:
            self.log("warn", f"Day trade: could not save today's picks: {exc}")

    def load_inplay_picks(self, today: date) -> bool:
        try:
            payload = json.loads(self.INPLAY_PICKS_PATH.read_text(encoding="utf-8"))
            saved = payload.get(self.account_id) or {}
            if saved.get("session") != today.isoformat():
                return False
            picks = [
                inplay_logic.Pick(
                    symbol=str(item["symbol"]).upper(),
                    rank=int(item["rank"]),
                    **{key: Decimal(str(item[key])) for key in ("high", "low", "open", "close", "relative_volume", "atr_percent", "dollar_volume", "stop")},
                )
                for item in saved.get("picks", [])
            ]
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
            return False
        with self.lock:
            self.inplay_picks = {pick.symbol: pick for pick in picks}
            self.inplay_picks_session = today.isoformat()
            self.inplay_checked = int(saved.get("checked") or 0)
            self.inplay_rejected = dict(saved.get("rejected") or {})
        return True

    def inplay_universe(self, today: date | None = None) -> list[str]:
        with self.lock:
            actives = list(self.top_volume_symbols)
        recent = self.inplay_recent_actives()
        if today is not None:
            recent = recent + self.inplay_tape_actives(today)
        return without_invalid_market_data_symbols(
            clean_symbol_list(list(inplay_logic.CORE_SYMBOLS) + recent + actives)
        )

    def inplay_pass(self, clock: Any, market_open: bool) -> str:
        """Start the data worker when needed and describe where the day stands."""
        config = self.config
        today = self.allocation_today(clock)
        now = self.clock_now(clock, getattr(clock, "next_close", None))
        ready_at = self.inplay_ready_at(today, config)
        ready = market_open and now >= ready_at
        with self.lock:
            have_history = bool(self.inplay_history and self.inplay_history[0] == today.isoformat())
            have_picks = self.inplay_picks_session == today.isoformat()
            if not have_picks and self.inplay_picks_session and self.inplay_picks_session != today.isoformat():
                self.inplay_picks = {}
                self.inplay_picks_session = ""
        if not have_picks and self.load_inplay_picks(today):
            have_picks = True
        if market_open and (not have_history or (ready and not have_picks)):
            self.start_inplay_worker(today, ready)
        ready_text = ready_at.astimezone(MARKET_TIMEZONE).strftime("%I:%M %p ET").lstrip("0")
        with self.lock:
            picks = sorted(self.inplay_picks.values(), key=lambda pick: pick.rank)
            checked = self.inplay_checked
            rejected = dict(self.inplay_rejected)
        if have_picks or picks:
            if picks:
                listing = ", ".join(f"{pick.symbol} {pick.relative_volume:.1f}x" for pick in picks)
                text = f"Day trade: {len(picks)} in play ({listing})"
            else:
                text = f"Day trade: nothing in play today ({checked} checked)"
        elif market_open:
            text = f"Day trade: picks at {ready_text}, after the {config.inplay_range_minutes}-minute range"
        else:
            text = ""
        view = {
            "session": today.isoformat(),
            "ready_at": ready_text,
            "checked": checked,
            "rejected": rejected,
            "picks": [
                {
                    "symbol": pick.symbol,
                    "rank": pick.rank,
                    "range_high": str(pick.high),
                    "range_low": str(pick.low),
                    "stop": str(pick.stop),
                    "relative_volume": f"{pick.relative_volume:.2f}",
                    "atr_percent": f"{pick.atr_percent:.2f}",
                    "dollar_volume_millions": f"{pick.dollar_volume / Decimal('1000000'):.0f}",
                }
                for pick in picks
            ],
        }
        with self.lock:
            self.inplay_view = view
        return text

    def start_inplay_worker(self, today: date, ready: bool) -> None:
        with self.lock:
            if self.inplay_worker is not None and self.inplay_worker.is_alive():
                return
            if time.monotonic() < self.inplay_retry_at:
                return
            api_key, secret_key = self.api_key, self.secret_key
            if not api_key or not secret_key:
                return
            worker = threading.Thread(
                target=self.inplay_work, args=(today, ready, api_key, secret_key), daemon=True, name=f"inplay-{self.account_id[:6]}"
            )
            self.inplay_worker = worker
        worker.start()

    def inplay_work(self, today: date, ready: bool, api_key: str, secret_key: str) -> None:
        """Worker thread: load recent opening ranges and daily stats, then (once ready) rank today's picks."""
        try:
            data_client = StockHistoricalDataClient(api_key, secret_key)
            trading_client = TradingClient(api_key, secret_key, paper=True)
            config = self.config
            universe = self.inplay_universe(today)
            with self.lock:
                cached = self.inplay_history if self.inplay_history and self.inplay_history[0] == today.isoformat() else None
            history = dict(cached[1]) if cached else {}
            stats = dict(cached[2]) if cached else {}
            missing = [symbol for symbol in universe if symbol not in history]
            if missing:
                sessions = self.inplay_previous_sessions(trading_client, today)
                session_ranges = [
                    self.inplay_fetch_ranges(data_client, missing, session, config.inplay_range_minutes) for session in sessions
                ]
                daily = self.inplay_fetch_daily_stats(data_client, missing, today)
                # Only a complete load is kept: a symbol with a gap in its history would rank wrongly.
                for ranges in session_ranges:
                    for symbol in missing:
                        bar = ranges.get(symbol)
                        history.setdefault(symbol, []).append(bar.volume if bar else Decimal("0"))
                stats.update(daily)
                with self.lock:
                    self.inplay_history = (today.isoformat(), history, stats)
            if not ready:
                return
            ranges = self.inplay_fetch_ranges(data_client, universe, today, config.inplay_range_minutes)
            picks, rejected = inplay_logic.rank_picks(
                ranges,
                history,
                stats,
                min_relative_volume=config.inplay_min_relative_volume,
                min_atr_percent=config.inplay_min_atr_percent,
                min_dollar_volume=config.inplay_min_dollar_volume_millions * Decimal("1000000"),
                max_picks=config.inplay_max_picks,
                stop_mode=config.inplay_stop,
            )
            with self.lock:
                self.inplay_picks = {pick.symbol: pick for pick in picks}
                self.inplay_picks_session = today.isoformat()
                self.inplay_rejected = rejected
                self.inplay_checked = len(ranges)
                actives = list(self.top_volume_symbols)
            self.remember_inplay_actives(today, actives)
            self.save_inplay_picks(today, picks, len(ranges), rejected)
            with self.lock:
                self.inplay_failures = 0
            if picks:
                self.log("info", "Day trade picks: " + "; ".join(f"{pick.symbol} ({pick.describe()})" for pick in picks))
            else:
                self.log("info", f"Day trade: nothing in play today ({len(ranges)} checked).")
        except Exception as exc:
            with self.lock:
                self.inplay_failures += 1
                wait = min(600, 60 * 2 ** (self.inplay_failures - 1))
                self.inplay_retry_at = time.monotonic() + wait
            self.log("warn", f"Day trade data load failed; retrying in {wait // 60} min: {exc}")

    def inplay_previous_sessions(self, trading_client: Any, today: date) -> list[date]:
        calendar = trading_client.get_calendar(GetCalendarRequest(start=today - timedelta(days=40), end=today - timedelta(days=1)))
        sessions = []
        for item in calendar or []:
            value = getattr(item, "date", None)
            if isinstance(value, datetime):
                value = value.date()
            if isinstance(value, date) and value < today:
                sessions.append(value)
        return sorted(sessions)[-inplay_logic.HISTORY_SESSIONS:]

    def inplay_fetch_ranges(
        self, data_client: Any, symbols: list[str], session: date, minutes: int
    ) -> dict[str, inplay_logic.RangeBar]:
        """Each symbol's opening range on session, from consolidated 5-minute bars."""
        start = datetime.combine(session, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30)
        end = start + timedelta(minutes=minutes)
        result: dict[str, inplay_logic.RangeBar] = {}
        for index in range(0, len(symbols), 100):
            batch = symbols[index : index + 100]
            while batch:
                try:
                    bars = data_client.get_stock_bars(
                        StockBarsRequest(
                            symbol_or_symbols=batch,
                            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                            start=start,
                            end=end,
                            feed=DataFeed.SIP,
                            adjustment=Adjustment.RAW,
                            limit=HISTORICAL_BARS_REQUEST_LIMIT,
                            sort=Sort.ASC,
                        )
                    )
                except Exception as exc:
                    rejected = rejected_market_data_symbol(exc, batch)
                    if not rejected:
                        raise
                    batch = [symbol for symbol in batch if symbol != rejected]
                    continue
                for symbol, symbol_bars in (getattr(bars, "data", {}) or {}).items():
                    rows = [
                        (
                            decimal_value(getattr(bar, "open", None)),
                            decimal_value(getattr(bar, "high", None)),
                            decimal_value(getattr(bar, "low", None)),
                            decimal_value(getattr(bar, "close", None)),
                            decimal_value(getattr(bar, "volume", None)),
                        )
                        for bar in symbol_bars
                        if start <= getattr(bar, "timestamp", start).astimezone(MARKET_TIMEZONE) < end
                    ]
                    # Only a full range counts: a symbol that skipped its first bar did not open normally.
                    if len(rows) == minutes // 5 and rows[0][0] > 0:
                        combined = inplay_logic.combine_range(rows)
                        if combined is not None:
                            result[str(symbol).upper()] = combined
                break
        return result

    def inplay_fetch_daily_stats(
        self, data_client: Any, symbols: list[str], today: date
    ) -> dict[str, inplay_logic.DailyStats]:
        now = datetime.now(timezone.utc)
        result: dict[str, inplay_logic.DailyStats] = {}
        for index in range(0, len(symbols), 100):
            batch = symbols[index : index + 100]
            while batch:
                try:
                    bars = data_client.get_stock_bars(
                        StockBarsRequest(
                            symbol_or_symbols=batch,
                            timeframe=TimeFrame.Day,
                            start=now - timedelta(days=60),
                            end=now - timedelta(minutes=self.INPLAY_SIP_DELAY_MINUTES),
                            feed=DataFeed.SIP,
                            adjustment=Adjustment.SPLIT,
                            limit=HISTORICAL_BARS_REQUEST_LIMIT,
                            sort=Sort.ASC,
                        )
                    )
                except Exception as exc:
                    rejected = rejected_market_data_symbol(exc, batch)
                    if not rejected:
                        raise
                    batch = [symbol for symbol in batch if symbol != rejected]
                    continue
                for symbol, symbol_bars in (getattr(bars, "data", {}) or {}).items():
                    rows = []
                    for bar in symbol_bars:
                        session = rvol_universe.bar_session_date(getattr(bar, "timestamp", None), MARKET_TIMEZONE)
                        if session is None or session >= today:
                            continue
                        rows.append(
                            (
                                decimal_value(getattr(bar, "open", None)),
                                decimal_value(getattr(bar, "high", None)),
                                decimal_value(getattr(bar, "low", None)),
                                decimal_value(getattr(bar, "close", None)),
                                decimal_value(getattr(bar, "volume", None)),
                            )
                        )
                    stat = inplay_logic.daily_stats(rows)
                    if stat is not None:
                        result[str(symbol).upper()] = stat
                break
        return result

    def inplay_entry_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        for reason in (self.inverse_etf_hold_reason(symbol, config), self.halt_hold_reason(symbol)):
            if reason:
                return reason
        with self.lock:
            pick = self.inplay_picks.get(symbol.strip().upper())
            entries_today = self.entries_today_by_symbol.get(symbol.strip().upper(), 0)
        if pick is None:
            return "Hold (in play: not a pick today)"
        if entries_today:
            return "Hold (in play: bought once today)"
        price = self.latest_stream_price(symbol) or snapshot.price
        reason = inplay_logic.entry_hold_reason(pick, price, config.inplay_max_chase_percent)
        if reason:
            return reason
        return self.asset_tradeability_hold_reason(symbol)

    def inplay_entry_candidate(self, symbol: str, rank: int, snapshot: Any, config: AppConfig) -> dict[str, Any] | None:
        hold = self.inplay_entry_hold_reason(symbol, snapshot, config)
        if hold:
            self.strategy_state.last_action[symbol] = hold
            return None
        with self.lock:
            pick = self.inplay_picks.get(symbol.strip().upper())
        pick_rank = pick.rank if pick is not None else rank
        score = Decimal("100") - Decimal(pick_rank)
        self.set_entry_score(symbol, score)
        self.strategy_state.last_action[symbol] = "Candidate in-play breakout"
        return {"symbol": symbol, "rank": pick_rank, "score": score}

    # ----- Mover readings (scored and weighted accounts) ----------------------------------------

    MOVERS_PATH = APP_DIR / "movers_volume.json"
    MOVERS_REFRESH_SECONDS = 150
    MOVERS_STALE_SECONDS = 10 * 60

    def mover_weights(self, config: AppConfig) -> movers_logic.Weights:
        return movers_logic.Weights(
            volume=config.mover_weight_volume,
            half_hour_move=config.mover_weight_half_hour_move,
            vwap=config.mover_weight_vwap,
            five_min_move=config.mover_weight_five_min_move,
            daily_range=config.mover_weight_range,
            session=config.mover_weight_session,
            rsi=config.mover_weight_rsi,
            volume_full_at=config.mover_volume_full_at,
            spread=config.mover_weight_spread,
            volume_current=bool(config.mover_volume_current),
            two_sided=config.entry_mode == "weighted",
        )

    def mover_price_change(
        self, symbol: str, price: Decimal | None, minutes: int, price_at: datetime | None = None
    ) -> Decimal | None:
        """Percent change of price against the session bar from `minutes` ago (or the session's
        first bar while the session is younger than that)."""
        if price is None or price <= 0:
            return None
        session = _latest_session_points(self.strategy_state.histories.get(symbol.strip().upper(), []))
        if not session:
            return None
        price_at = price_at or _bar_local_time(session[-1].timestamp)
        if price_at is None:
            return None
        cutoff = price_at - timedelta(minutes=minutes)
        base = session[0].close
        for point in reversed(session):
            local = _bar_local_time(point.timestamp)
            if local is not None and local <= cutoff:
                base = point.close
                break
        if base <= 0:
            return None
        return (price / base - Decimal("1")) * Decimal("100")

    def mover_readings(self, symbol: str, snapshot: Any) -> movers_logic.Readings:
        clean = symbol.strip().upper()
        with self.lock:
            relative = self.mover_volume.get(clean)
            recent = self.mover_volume_recent.get(clean)
            stat = self.mover_stats.get(clean)
            volume_age = time.monotonic() - self.mover_volume_at
        if volume_age > self.MOVERS_STALE_SECONDS:
            # The volume worker has not succeeded for a while: an old reading earns no points.
            relative = recent = None
        session = _latest_session_points(self.strategy_state.histories.get(clean, []))
        bar_at = _bar_local_time(session[-1].timestamp) if session else None
        price, price_at = snapshot.price, bar_at
        trade = self.latest_stream_trade(clean)
        if trade and bar_at and trade[1] >= bar_at and trade[1].astimezone(MARKET_TIMEZONE).date() == bar_at.date():
            price, price_at = trade
        vwap = snapshot.vwap
        opening_close = session[0].close if session else None
        return movers_logic.Readings(
            relative_volume=relative,
            half_hour_move=self.mover_price_change(clean, price, 30, price_at),
            five_min_move=self.mover_price_change(clean, price, 5, price_at),
            vwap_distance=percent_change(price, vwap) if price and vwap else None,
            session_change=percent_change(price, opening_close) if price and opening_close else None,
            daily_range=stat.atr_percent if stat is not None else None,
            rsi=snapshot.rsi,
            recent_relative_volume=recent,
            spread_percent=self.mover_spread_percent(clean, price),
            stop_percent=self.position_stop_percent(clean, self.config),
            price=price,
        )

    MOVERS_QUOTE_SECONDS = 10 * 60

    def mover_spread_percent(self, symbol: str, price: Decimal | None) -> Decimal | None:
        """The bid/ask spread as a percent of price. The quote is the one read just before an order
        (kept for ten minutes); without one, and never below it, the spread is one price tick, the
        narrowest the stock can be quoted."""
        if price is None or price <= 0:
            return None
        spread = self.price_increment_for(price)
        with self.lock:
            quote = self.mover_quotes.get(symbol)
        if quote is not None:
            bid, ask, read_at = quote
            if time.monotonic() - read_at <= self.MOVERS_QUOTE_SECONDS and bid > 0 and ask > bid:
                spread = max(spread, ask - bid)
        return spread / price * Decimal("100")

    def movers_entry_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        """Why this stock is not a buy right now, for a scored or weighted account that uses the
        mover readings; empty when its score clears the bar.

        The account's settings decide every step. Scored style: the old-style trend checks run first
        when they are switched on, then whichever of the three direction checks are on (up on the
        session, above VWAP, not falling over the last five minutes). Weighted style: no yes/no
        check at all. Then the score: the mover readings by their weights, plus the old-style score
        when any of its weights is above zero. RSI only ever moves the score.
        """
        clean = symbol.strip().upper()
        for reason in (self.inverse_etf_hold_reason(symbol, config), self.halt_hold_reason(symbol)):
            if reason:
                return reason
        if config.entry_mode == "scored" and config.use_trend_checks:
            trend = self.trend_checks_hold_reason(symbol, snapshot, config)
            if trend:
                return trend
        readings = self.mover_readings(symbol, snapshot)
        direction = movers_logic.direction_hold_reason(readings, *direction_checks(config))
        if direction:
            return direction
        # A stock with no volume reading yet (no history on record, or before the first reading
        # about 09:51 ET) or no daily range simply earns no points for it.
        result = movers_logic.score(readings, self.mover_weights(config))
        if uses_old_score(config):
            result = result.plus("old-style score", self.entry_score(snapshot, config, self.order_flow_ratio(symbol)))
        with self.lock:
            self.mover_scores[clean] = result
        self.set_entry_score(symbol, result.total)
        if result.total < config.min_entry_score:
            return f"Hold (score {result.total:.0f} of {config.min_entry_score:.0f}: {result.describe() or 'no points yet'})"
        if not uses_climbing_reentry(config):
            return self.asset_tradeability_hold_reason(symbol)  # the floor rule is checked with the candidate
        needed, losses = self.movers_reentry_bar(clean, config)
        old_high = self.movers_unbeaten_high(clean, readings.price)
        if old_high is not None:
            needed += max(Decimal("0"), config.reentry_score_boost)
        if result.total < needed:
            why = []
            if losses:
                why.append(f"{losses} losing exit{'' if losses == 1 else 's'} today")
            if old_high is not None:
                why.append(f"a sale at a gain, until it trades above ${old_high}")
            return f"Hold (re-entry needs {needed:.0f} after {' and '.join(why)}; score {result.total:.0f})"
        return self.asset_tradeability_hold_reason(symbol)

    def movers_unbeaten_high(self, symbol: str, price: Decimal | None) -> Decimal | None:
        """The price a stock sold at a gain today has to trade above before its re-entry score comes
        back down; None when there is no such sale or the price is already above it. The sale was
        the trailing stop reading the stock as falling from its high, so buying it straight back
        needs a stronger score until it has gone on to a new high. Released by price, not by time."""
        with self.lock:
            pending = self.reentry_new_highs.get(symbol)
            if pending is None:
                return None
            sell_id, target = pending
            if price is not None and price > target:
                self.reentry_new_highs.pop(symbol, None)
                self.reentry_released_sells.add(sell_id)
                return None
            return target

    def movers_reentry_bar(self, symbol: str, config: AppConfig) -> tuple[Decimal, int]:
        """The score a mover needs to be bought, and its losing round trips today.

        Each losing round trip today adds the account's Re-entry Boost to Min Score: at 60 and 20
        a stock that lost once needs 80, twice 100, and after that it is out for the day (a bar
        above the top score). Winners add nothing; the count starts over each trading day."""
        today = datetime.now(MARKET_TIMEZONE).date()
        with self.lock:
            losses = len(self.reentry_losses_today.get(symbol, ())) if self.reentry_losses_date == today else 0
        return config.min_entry_score + max(Decimal("0"), config.reentry_score_boost) * losses, losses

    def movers_entry_candidate(self, symbol: str, rank: int, snapshot: Any, config: AppConfig) -> dict[str, Any] | None:
        hold = self.movers_entry_hold_reason(symbol, snapshot, config)
        if hold:
            self.strategy_state.last_action[symbol] = hold
            return None
        with self.lock:
            result = self.mover_scores.get(symbol.strip().upper())
        total = result.total if result is not None else Decimal("0")
        reentry_floor = self.reentry_score_floors.get(symbol)
        if uses_reentry_floor(config) and reentry_floor is not None and total < reentry_floor:
            self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
            return None
        self.strategy_state.last_action[symbol] = f"Candidate movers score {total:.0f}"
        return {"symbol": symbol, "rank": rank, "score": total}

    def movers_pass(self, clock: Any, market_open: bool) -> str:
        """Keep the volume data fresh (on a worker thread) and describe where it stands."""
        today = self.allocation_today(clock)
        with self.lock:
            new_session = self.mover_session != today.isoformat()
            if new_session:
                self.mover_session = today.isoformat()
                self.mover_profiles = {}
                self.mover_stats = {}
                self.mover_volume = {}
                self.mover_volume_recent = {}
                self.mover_quotes = {}
                self.mover_scores = {}
                self.mover_volume_slot = None
                self.mover_volume_at = 0.0
        if new_session:
            self.load_mover_data(today)
        symbols = [symbol for symbol in self.scan_symbols() if not symbol[:1].isdigit()]
        with self.lock:
            missing = [symbol for symbol in symbols if symbol not in self.mover_profiles]
            stale = time.monotonic() - self.mover_volume_at >= self.MOVERS_REFRESH_SECONDS
            volume = dict(self.mover_volume)
            slot = self.mover_volume_slot
        if market_open and (missing or stale):
            self.start_mover_worker(today, symbols)
        leaders = sorted(volume.items(), key=lambda item: -item[1])[:10]
        as_of = ""
        if slot is not None:
            stamp = datetime.combine(today, datetime.min.time()).replace(hour=9, minute=30) + timedelta(
                minutes=movers_logic.SLOT_MINUTES * (slot + 1)
            )
            as_of = stamp.strftime("%I:%M %p ET").lstrip("0")
        view = {
            "session": today.isoformat(),
            "volume_as_of": as_of,
            "symbols_with_volume": len(volume),
            "symbols_loading": len(missing),
            "leaders": [{"symbol": symbol, "relative_volume": f"{value:.2f}"} for symbol, value in leaders],
        }
        with self.lock:
            self.mover_view = view
        if market_open and not volume:
            return "Movers: loading volume data; buys start once it is in"
        return ""

    def load_mover_data(self, today: date) -> None:
        try:
            saved = (json.loads(self.MOVERS_PATH.read_text(encoding="utf-8")) or {}).get(self.account_id) or {}
            if saved.get("session") != today.isoformat():
                return
            profiles = {
                str(symbol).upper(): ([float(value) for value in values] if values else None)
                for symbol, values in (saved.get("profiles") or {}).items()
            }
            stats = {
                str(symbol).upper(): inplay_logic.DailyStats(atr_percent=Decimal(str(item[0])), dollar_volume=Decimal(str(item[1])))
                for symbol, item in (saved.get("stats") or {}).items()
            }
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, AttributeError, IndexError):
            return
        with self.lock:
            self.mover_profiles.update(profiles)
            self.mover_stats.update(stats)

    def save_mover_data(self, today: date) -> None:
        with self.lock:
            entry = {
                "session": today.isoformat(),
                "profiles": {symbol: values for symbol, values in self.mover_profiles.items()},
                "stats": {symbol: [str(stat.atr_percent), str(stat.dollar_volume)] for symbol, stat in self.mover_stats.items()},
            }
        try:
            payload = json.loads(self.MOVERS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload[self.account_id] = entry
        try:
            write_private_json(self.MOVERS_PATH, payload)
        except OSError as exc:
            self.log("warn", f"Movers: could not save the volume data: {exc}")

    def start_mover_worker(self, today: date, symbols: list[str]) -> None:
        with self.lock:
            if self.mover_worker is not None and self.mover_worker.is_alive():
                return
            if time.monotonic() < self.mover_retry_at:
                return
            api_key, secret_key = self.api_key, self.secret_key
            if not api_key or not secret_key:
                return
            worker = threading.Thread(
                target=self.mover_work, args=(today, list(symbols), api_key, secret_key), daemon=True, name=f"movers-{self.account_id[:6]}"
            )
            self.mover_worker = worker
        worker.start()

    def mover_work(self, today: date, symbols: list[str], api_key: str, secret_key: str) -> None:
        """Worker thread: load the usual volume by time of day for new symbols, then today's volume so far."""
        try:
            data_client = StockHistoricalDataClient(api_key, secret_key)
            with self.lock:
                known = set(self.mover_profiles)
            missing = [symbol for symbol in symbols if symbol not in known]
            if missing:
                trading_client = TradingClient(api_key, secret_key, paper=True)
                sessions = self.mover_previous_sessions(trading_client, today)
                per_symbol: dict[str, list[list[float]]] = {symbol: [] for symbol in missing}
                for session in sessions:
                    bars = self.mover_fetch_volume(data_client, missing, session, None)
                    for symbol in missing:
                        per_symbol[symbol].append(movers_logic.cumulative_volume(bars.get(symbol, [])))
                stats = self.inplay_fetch_daily_stats(data_client, missing, today)
                profiles = {symbol: movers_logic.average_profile(per_symbol[symbol]) for symbol in missing}
                with self.lock:
                    current = self.mover_session == today.isoformat()
                    if current:
                        self.mover_profiles.update(profiles)
                        self.mover_stats.update(stats)
                if not current:
                    return
                self.save_mover_data(today)
            open_et = datetime.combine(today, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30)
            minutes = (datetime.now(MARKET_TIMEZONE) - open_et).total_seconds() / 60
            slot = movers_logic.last_complete_slot(minutes, self.INPLAY_SIP_DELAY_MINUTES)
            volumes: dict[str, Decimal] = {}
            recent_volumes: dict[str, Decimal] = {}
            if slot is not None:
                with self.lock:
                    profiles_now = {symbol: self.mover_profiles.get(symbol) for symbol in symbols}
                wanted = [symbol for symbol in symbols if profiles_now.get(symbol)]
                end = open_et + timedelta(minutes=movers_logic.SLOT_MINUTES * (slot + 1))
                bars = self.mover_fetch_volume(data_client, wanted, today, end) if wanted else {}
                for symbol in wanted:
                    today_volume = movers_logic.cumulative_volume(bars.get(symbol, []))
                    value = movers_logic.relative_volume(today_volume, profiles_now[symbol], slot)
                    if value is not None:
                        volumes[symbol] = value
                    recent = movers_logic.recent_relative_volume(today_volume, profiles_now[symbol], slot)
                    if recent is not None:
                        recent_volumes[symbol] = recent
            with self.lock:
                if self.mover_session == today.isoformat():
                    if slot is not None:
                        self.mover_volume = volumes
                        self.mover_volume_recent = recent_volumes
                        self.mover_volume_slot = slot
                    self.mover_volume_at = time.monotonic()
                    self.mover_failures = 0
        except Exception as exc:
            with self.lock:
                self.mover_failures += 1
                wait = min(600, 60 * 2 ** (self.mover_failures - 1))
                self.mover_retry_at = time.monotonic() + wait
            self.log("warn", f"Movers volume data load failed; retrying in {wait // 60} min: {exc}")

    def mover_previous_sessions(self, trading_client: Any, today: date) -> list[date]:
        """The last full sessions before today. Half days are left out: their flat afternoon would
        make every normal afternoon look like heavy volume for weeks."""
        calendar = trading_client.get_calendar(GetCalendarRequest(start=today - timedelta(days=45), end=today - timedelta(days=1)))
        sessions: list[date] = []
        for item in calendar or []:
            value = getattr(item, "date", None)
            if isinstance(value, datetime):
                value = value.date()
            close = getattr(item, "close", None)
            close_hour = getattr(close, "hour", 16)
            if isinstance(value, date) and value < today and close_hour >= 16:
                sessions.append(value)
        return sorted(sessions)[-movers_logic.PROFILE_SESSIONS:]

    def mover_fetch_volume(
        self, data_client: Any, symbols: list[str], session: date, end: datetime | None
    ) -> dict[str, list[tuple[int, Decimal]]]:
        """(minute of day ET, volume) for each symbol's consolidated 5-minute bars on session, from
        the open to `end` (the close when None)."""
        start = datetime.combine(session, datetime.min.time(), MARKET_TIMEZONE).replace(hour=9, minute=30)
        stop = end or start.replace(hour=16, minute=0)
        result: dict[str, list[tuple[int, Decimal]]] = {}
        for index in range(0, len(symbols), 100):
            batch = symbols[index : index + 100]
            while batch:
                try:
                    bars = data_client.get_stock_bars(
                        StockBarsRequest(
                            symbol_or_symbols=batch,
                            timeframe=TimeFrame(5, TimeFrameUnit.Minute),
                            start=start,
                            end=stop,
                            feed=DataFeed.SIP,
                            adjustment=Adjustment.RAW,
                            limit=HISTORICAL_BARS_REQUEST_LIMIT,
                            sort=Sort.ASC,
                        )
                    )
                except Exception as exc:
                    rejected = rejected_market_data_symbol(exc, batch)
                    if not rejected:
                        raise
                    batch = [symbol for symbol in batch if symbol != rejected]
                    continue
                for symbol, symbol_bars in (getattr(bars, "data", {}) or {}).items():
                    rows: list[tuple[int, Decimal]] = []
                    for bar in symbol_bars:
                        stamp = getattr(bar, "timestamp", None)
                        if stamp is None:
                            continue
                        local = stamp.astimezone(MARKET_TIMEZONE)
                        if not (start <= local < stop):
                            continue
                        rows.append((local.hour * 60 + local.minute, decimal_value(getattr(bar, "volume", None))))
                    result[str(symbol).upper()] = rows
                break
        return result

    # ----- Hold mode (entry_mode "allocation") -------------------------------------------------

    def allocation_today(self, clock: Any) -> date:
        """The market's calendar date (US/Eastern) by the broker clock."""
        return self.clock_now(clock, getattr(clock, "next_close", None)).astimezone(MARKET_TIMEZONE).date()

    def allocation_window_detail(self, clock: Any, config: AppConfig) -> str:
        """Non-empty while hold mode may trade: the last allocation minutes before the close,
        stopping two minutes short of it so a market order still has time to fill."""
        if not bool(getattr(clock, "is_open", False)):
            return ""
        next_close = getattr(clock, "next_close", None)
        if not hasattr(next_close, "astimezone"):
            return ""
        seconds_left = (next_close - self.clock_now(clock, next_close)).total_seconds()
        if seconds_left <= 120 or seconds_left > config.allocation_trade_minutes_before_close * 60:
            return ""
        return f"trade window open; market closes in {max(0, int((seconds_left + 59) // 60))} min"

    def allocation_sessions(self, client: Any, today: date) -> list[date]:
        """Trading sessions from today through the next two weeks (cached per day)."""
        cached = self.allocation_sessions_cache
        if cached and cached[0] == today.isoformat():
            return cached[1]
        if time.monotonic() < self.allocation_retry_at:
            return []
        try:
            calendar = client.get_calendar(GetCalendarRequest(start=today, end=today + timedelta(days=14)))
        except Exception as exc:
            self.allocation_retry_at = time.monotonic() + 60
            self.log("warn", f"Hold mode: market calendar lookup failed; retrying in a minute: {exc}")
            return []
        sessions: list[date] = []
        for item in calendar or []:
            value = getattr(item, "date", None) if not isinstance(item, dict) else item.get("date")
            if isinstance(value, datetime):
                value = value.date()
            elif isinstance(value, str):
                try:
                    value = date.fromisoformat(value[:10])
                except ValueError:
                    value = None
            if isinstance(value, date):
                sessions.append(value)
        sessions.sort()
        self.allocation_sessions_cache = (today.isoformat(), sessions)
        return sessions

    def allocation_previous_closes(self, symbol: str, today: date, days: int) -> list[Decimal] | None:
        """Consolidated (SIP) daily closes of the sessions before today, oldest first (cached per day).

        Free market data may not query the last 15 minutes of SIP data, so the request ends 16
        minutes back; only finished sessions before today are kept anyway.
        """
        key = (symbol, today.isoformat(), days)
        if key in self.allocation_closes_cache:
            return self.allocation_closes_cache[key]
        if time.monotonic() < self.allocation_retry_at:
            return None
        client = self.data_client
        if client is None:
            return None
        now = datetime.now(timezone.utc)
        try:
            bars = client.get_stock_bars(
                StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=TimeFrame.Day,
                    start=now - timedelta(days=int(days * 1.6) + 30),
                    end=now - timedelta(minutes=16),
                    feed=DataFeed.SIP,
                    adjustment=Adjustment.ALL,
                    sort=Sort.ASC,
                )
            )
        except Exception as exc:
            self.allocation_retry_at = time.monotonic() + 60
            self.log("warn", f"Hold mode: daily closes for {symbol} failed; retrying in a minute: {exc}")
            return None
        data = getattr(bars, "data", {}) or {}
        closes: list[Decimal] = []
        for bar in data.get(symbol, []) or []:
            session = rvol_universe.bar_session_date(getattr(bar, "timestamp", None), MARKET_TIMEZONE)
            if session is None or session >= today:
                continue
            close = decimal_value(getattr(bar, "close", None))
            if close > 0:
                closes.append(close)
        self.allocation_closes_cache = {k: v for k, v in self.allocation_closes_cache.items() if k[1] == today.isoformat()}
        self.allocation_closes_cache[key] = closes
        return closes

    def allocation_live_price(self, symbol: str) -> Decimal | None:
        price = self.latest_stream_price(symbol)
        if price is None or price <= 0:
            price = self.snapshot(symbol).price
        return price if price is not None and price > 0 else None

    def allocation_latch_from_orders(self, orders: list[dict[str, Any]], today: date) -> str:
        """Today's decided regime, read back from the app's own hold-mode order ids (survives a restart)."""
        for order in orders:
            client_id = str(order.get("client_order_id") or "")
            match = re.match(r"^apt-(?:entry|exit)-alloc-(on|off)-", client_id)
            if not match:
                continue
            submitted = self.parse_order_datetime(order.get("submitted_at") or order.get("created_at"))
            if submitted is not None and submitted.astimezone(MARKET_TIMEZONE).date() == today:
                return match.group(1)
        return ""

    def build_allocation_order(self, symbol: str, side: OrderSide, qty: Decimal, regime: str) -> MarketOrderRequest:
        prefix = "entry" if side == OrderSide.BUY else "exit"
        return MarketOrderRequest(
            symbol=symbol,
            qty=float(qty),
            side=side,
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id=f"apt-{prefix}-alloc-{regime}-{symbol.lower()}-{int(time.time() * 1000)}",
        )

    def run_allocation_pass(
        self,
        client: Any,
        clock: Any,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        open_orders: list[dict[str, Any]],
        closed_orders: list[dict[str, Any]],
        should_trade: bool,
        market_open: bool,
    ) -> str:
        """One hold-mode pass: read the signal, decide today's target, and place at most one wave of
        orders (sells, or else buys). Every pass re-reads broker state, so it is safe to repeat."""
        config = self.config
        today = self.allocation_today(clock)
        risk_on = list(config.allocation_risk_on_symbols)
        risk_off = list(config.allocation_risk_off_symbols)
        sets = {"on": risk_on, "off": risk_off}
        signal_symbol = config.allocation_signal_symbol
        closes = self.allocation_previous_closes(signal_symbol, today, config.allocation_sma_days)
        signal = allocation_logic.allocation_signal(
            closes or [], self.allocation_live_price(signal_symbol), config.allocation_sma_days
        )
        sessions = self.allocation_sessions(client, today)
        check_day = allocation_logic.is_check_day(today, sessions, config.allocation_check) if sessions else False
        next_check = allocation_logic.next_check_day(today, sessions, config.allocation_check) if sessions else None
        holdings = [
            allocation_logic.Holding(
                symbol=str(item.get("symbol", "")).upper(),
                qty=decimal_value(item.get("qty")),
                market_value=decimal_value(item.get("market_value")),
                qty_available=self.sellable_qty(item),
            )
            for item in positions
            if decimal_value(item.get("qty")) > 0 and not is_placeholder_position(item)
        ]
        held = allocation_logic.held_regime(holdings, risk_on, risk_off)
        equity = decimal_value(account.get("equity"))
        window = self.allocation_window_detail(clock, config)

        latch = self.allocation_latch if self.allocation_latch and self.allocation_latch[0] == today.isoformat() else None
        if latch is None:
            rebuilt = self.allocation_latch_from_orders(open_orders + closed_orders, today)
            if rebuilt:
                latch = (today.isoformat(), rebuilt)
                self.allocation_latch = latch
        target_regime = ""
        decided_by = ""
        if latch:
            target_regime, decided_by = latch[1], "decided earlier today"
        elif check_day and signal is not None:
            target_regime, decided_by = signal.regime, "weekly check" if config.allocation_check == "weekly" else "daily check"
        elif held in ("on", "off"):
            target_regime, decided_by = held, "holding"
        elif signal is not None:
            target_regime, decided_by = signal.regime, "funding" if held == "none" else "repair"
        target = sets.get(target_regime, [])
        switching = held in ("on", "off", "mixed") and bool(target_regime) and held != target_regime

        regime_text = {"on": "risk-on", "off": "risk-off"}.get(target_regime, "undecided")
        signal_text = signal.describe(signal_symbol) if signal is not None else f"{signal_symbol} signal warming up"
        next_text = next_check.strftime("%a %b %d") if next_check else "unknown"
        view = {
            "session": today.isoformat(),
            "signal": signal_text,
            "regime": target_regime,
            "held": held,
            "target": target,
            "check_day": check_day,
            "next_check": next_text,
            "window": window,
            "decided_by": decided_by,
        }
        positions_by_symbol = {item.symbol: item for item in holdings}
        target_weight = config.allocation_invest_percent / Decimal(len(target)) if target else Decimal("0")
        for symbol in merged_symbols([signal_symbol], risk_on + risk_off):
            parts = []
            if symbol == signal_symbol:
                parts.append(f"signal: {signal_text}")
            if symbol in target:
                held_value = positions_by_symbol[symbol].market_value if symbol in positions_by_symbol else Decimal("0")
                now_weight = held_value / equity * Decimal("100") if equity > 0 else Decimal("0")
                parts.append(f"target {target_weight:.1f}%, now {now_weight:.1f}%")
            elif symbol in positions_by_symbol:
                parts.append("held; sells at the next trade window")
            elif symbol in risk_on + risk_off:
                parts.append("not in the current target")
            self.strategy_state.last_action[symbol] = "Hold mode (" + "; ".join(parts) + ")"
        status = f"Hold mode {regime_text}: {signal_text}. Next check {next_text}"
        if window:
            status += f"; {window}"

        def finish(detail: str = "") -> str:
            view["detail"] = detail
            with self.lock:
                self.allocation_view = view
            return status + (f". {detail}" if detail else "")

        if not target_regime:
            return finish("Waiting for the signal")
        if not (should_trade and market_open and window):
            return finish("")
        if latch is None and decided_by in ("weekly check", "daily check"):
            # Only a real check decision is latched: if the signal or calendar is missing on the first
            # pass, "keep holding" must not stick when they come back a minute later.
            self.allocation_latch = (today.isoformat(), target_regime)

        plan = allocation_logic.plan_allocation(
            holdings,
            target,
            equity,
            decimal_value(account.get("cash")),
            decimal_value(account.get("buying_power")),
            config.allocation_invest_percent,
            config.allocation_rebalance_drift_percent,
            rebalance=check_day or switching,
        )
        # A stray holding (in neither fund set) whose sell the broker rejected cannot be sold, so it
        # must not hold up the buys: plan again with it kept as a holding but with nothing to sell.
        # A fund in the sets whose sell was rejected (a trim, or the old side of a switch) still
        # waits, so a failed trim never buys more of the fund and a switch never holds both sides.
        # Buys only ever spend cash, never margin.
        stray_stuck = {
            symbol for symbol, _, _ in plan.sells
            if symbol not in risk_on and symbol not in risk_off and self.sell_rejected(symbol)
        }
        if stray_stuck and stray_stuck == {symbol for symbol, _, _ in plan.sells}:
            plan = allocation_logic.plan_allocation(
                [dataclasses.replace(item, qty_available=Decimal("0")) if item.symbol in stray_stuck else item for item in holdings],
                target,
                equity,
                decimal_value(account.get("cash")),
                decimal_value(account.get("buying_power")),
                config.allocation_invest_percent,
                config.allocation_rebalance_drift_percent,
                rebalance=check_day or switching,
            )
        if not plan.sells and not plan.buys:
            return finish(plan.note or "on target")
        if config.dry_run:
            if self.allocation_dry_run_session != today.isoformat():
                self.allocation_dry_run_session = today.isoformat()
                for symbol, qty, why in plan.sells:
                    self.log("info", f"Dry run: hold mode would sell {qty} {symbol} ({why}).")
                for symbol, notional, why in plan.buys:
                    self.log("info", f"Dry run: hold mode would buy {money(notional)} of {symbol} ({why}).")
            return finish("dry run")
        # One wave at a time: let the app's own leftover stops clear, and wait out open orders that
        # touch this account's holdings or sets (a manual order on an unrelated symbol is ignored).
        leftovers = [order for order in open_orders if self.is_app_protective_order(order)]
        if leftovers:
            for order in leftovers:
                self.cancel_open_order(order)
            return finish("cancelling leftover stop orders first")
        involved = set(risk_on) | set(risk_off) | {item.symbol for item in holdings}
        blocking = [
            order for order in open_orders
            if str(order.get("symbol", "")).upper() in involved or str(order.get("client_order_id") or "").startswith("apt-")
        ]
        if blocking:
            return finish(f"waiting for {len(blocking)} open order(s)")
        # A symbol on a submit or reject hold is skipped this pass; the rest of the wave still goes.
        sells = [item for item in plan.sells if not self.order_hold_reason(item[0], OrderSide.SELL)]
        buys = [item for item in plan.buys if not self.order_hold_reason(item[0], OrderSide.BUY)]
        held_back = len(plan.sells) - len(sells) + (0 if plan.sells else len(plan.buys) - len(buys))
        reason_head = f"hold mode {regime_text} ({decided_by}): {signal_text}"
        if plan.sells:
            if not sells:
                return finish("waiting for the last order to show up")
            self.allocation_latch = (today.isoformat(), target_regime)
            for symbol, qty, why in sells:
                order = self.build_allocation_order(symbol, OrderSide.SELL, qty, target_regime)
                self.submit_allocation_order(symbol, OrderSide.SELL, qty, order, f"{reason_head}; sell: {why}", "Strategy Exit")
            return finish(f"selling {len(sells)} holding(s)" + (f"; {held_back} on hold" if held_back else ""))
        if not buys:
            return finish("waiting for the last order to show up")
        self.allocation_latch = (today.isoformat(), target_regime)
        for symbol, notional, why in buys:
            price = self.current_trade_price(symbol, self.allocation_live_price(symbol) or Decimal("0"))
            qty = order_quantity(notional, price)
            if qty <= 0:
                self.log("warn", f"Hold mode: no price for {symbol}; buy skipped this pass.")
                continue
            order = self.build_allocation_order(symbol, OrderSide.BUY, qty, target_regime)
            self.submit_allocation_order(
                symbol, OrderSide.BUY, qty, order, f"{reason_head}; buy {money(notional)} {why}; order_ref={price}", "Pending Entry"
            )
        return finish(f"buying {len(buys)} holding(s)" + (f"; {held_back} on hold" if held_back else ""))

    def submit_allocation_order(
        self, symbol: str, side: OrderSide, qty: Decimal, order: MarketOrderRequest, reason: str, role: str
    ) -> None:
        client_order_id = str(getattr(order, "client_order_id", ""))
        try:
            submitted = self.submit_order_request(order)
        except OrderExecutionError as exc:
            self.hold_rejected_order(symbol, side, ORDER_REJECT_HOLD_SECONDS)
            self.record_order_intent(symbol, side, qty, role, "error", f"{reason}; {exc}", client_order_id)
            self.log("error", f"Hold mode {self.order_side_text(side)} rejected for {symbol}: {exc}")
            return
        submitted_id = str(getattr(submitted, "id", ""))
        self.hold_submitted_order(symbol, side)
        self.record_order_intent(symbol, side, qty, role, "submitted", reason, client_order_id, submitted_id)
        if side == OrderSide.BUY:
            self.mark_entry_today(symbol)
        self.log("success", f"Hold mode: submitted {self.order_side_text(side)} for {qty} {symbol}: {submitted_id}")

    def entry_spacing_hold_reason(self, config: AppConfig) -> str:
        seconds = int(config.entry_spacing_seconds or 0)
        if seconds <= 0 or not self.last_entry_submitted_at:
            return ""
        elapsed = time.monotonic() - self.last_entry_submitted_at
        if elapsed >= seconds:
            return ""
        return f"Hold (entry spacing {int(seconds - elapsed) + 1}s)"

    def entry_quality_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        if self.inverse_trend_active(symbol, config):
            return self.inverse_trend_entry_hold_reason(symbol, snapshot, config)
        if config.entry_mode == "inplay":
            return self.inplay_entry_hold_reason(symbol, snapshot, config)
        if uses_mover_readings(config):
            return self.movers_entry_hold_reason(symbol, snapshot, config)
        inverse_reason = self.inverse_etf_hold_reason(symbol, config)
        if inverse_reason:
            return inverse_reason
        halt_reason = self.halt_hold_reason(symbol)
        if halt_reason:
            return halt_reason
        if config.entry_mode != "scored" or config.use_trend_checks:
            trend_reason = self.trend_checks_hold_reason(symbol, snapshot, config)
            if trend_reason:
                return trend_reason
        asset_reason = self.asset_tradeability_hold_reason(symbol)
        if asset_reason:
            return asset_reason
        return ""

    def trend_checks_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        """The old-style yes/no checks, in their order: RSI range, trend, momentum floors, session and
        VWAP bands, pullback limits, rising price, SMI, volume and order flow. A scored account runs
        them when "use trend checks" is on; opening-range accounts always do."""
        limits = entry_profile_limits(config)
        if snapshot.rsi is None:
            return "Hold (RSI warming)"
        if snapshot.rsi < config.buy_rsi_min:
            return f"Hold (RSI {snapshot.rsi:.1f})"
        if config.max_entry_rsi > 0 and snapshot.rsi > config.max_entry_rsi:
            return f"Hold (RSI {snapshot.rsi:.1f} above {config.max_entry_rsi})"
        if snapshot.rsi > config.buy_rsi_max:
            return f"Hold (RSI {snapshot.rsi:.1f} above {config.buy_rsi_max})"
        if snapshot.bias == "Waiting":
            return "Hold (trend warming)"
        if snapshot.bias != "Bullish":
            return f"Hold (trend {snapshot.bias})"
        if snapshot.momentum_percent is None:
            return "Hold (momentum warming)"
        if below_entry_floor(snapshot.momentum_percent, config.min_momentum_percent):
            return floor_hold_reason("momentum", snapshot.momentum_percent, config.min_momentum_percent)
        recent_momentum = getattr(snapshot, "recent_momentum_percent", None)
        if recent_momentum is None:
            return "Hold (recent momentum warming)"
        if below_entry_floor(recent_momentum, limits["min_recent_momentum"]):
            return floor_hold_reason("recent momentum", recent_momentum, limits["min_recent_momentum"])
        late_floor = limits["late_momentum_floor"]
        if late_floor > 0 and snapshot.rsi >= config.buy_rsi_max - Decimal("3") and snapshot.momentum_percent < late_floor:
            return f"Hold (late RSI {snapshot.rsi:.1f}, momentum {snapshot.momentum_percent:+.2f}%)"
        if late_floor > 0 and snapshot.smi is not None and snapshot.smi >= Decimal("90") and snapshot.momentum_percent < late_floor:
            return f"Hold (late SMI {snapshot.smi:.1f}, momentum {snapshot.momentum_percent:+.2f}%)"
        if getattr(snapshot, "long_momentum_percent", None) is None:
            return "Hold (long momentum warming)"
        if below_entry_floor(snapshot.long_momentum_percent, limits["min_long_momentum"]):
            return floor_hold_reason("long momentum", snapshot.long_momentum_percent, limits["min_long_momentum"])
        if getattr(snapshot, "session_change_percent", None) is None:
            return "Hold (session trend warming)"
        if below_entry_floor(snapshot.session_change_percent, limits["min_session_change"]):
            return f"Hold (session trend {snapshot.session_change_percent:+.2f}%)"
        if snapshot.session_change_percent > atr_scaled_cap(limits["max_session_extension"], snapshot, config):
            return f"Hold (session extended {snapshot.session_change_percent:+.2f}%)"
        if getattr(snapshot, "vwap_distance_percent", None) is None:
            return "Hold (VWAP warming)"
        if below_entry_floor(snapshot.vwap_distance_percent, limits["min_vwap_distance"]):
            return f"Hold (below VWAP {snapshot.vwap_distance_percent:+.2f}%)"
        if snapshot.vwap_distance_percent > atr_scaled_cap(limits["max_vwap_extension"], snapshot, config):
            return f"Hold (extended above VWAP {snapshot.vwap_distance_percent:+.2f}%)"
        session_pullback = getattr(snapshot, "session_pullback_percent", None)
        if session_pullback is None:
            return "Hold (session pullback warming)"
        if session_pullback > limits["max_session_pullback"]:
            return f"Hold (pulled back {session_pullback:.2f}% from session high)"
        recent_pullback = getattr(snapshot, "recent_pullback_percent", None)
        if recent_pullback is None:
            return "Hold (recent pullback warming)"
        if recent_pullback > limits["max_recent_pullback"]:
            return f"Hold (pulled back {recent_pullback:.2f}% from recent high)"
        if config.require_rising_price:
            rising_reason = self.rising_price_hold_reason(symbol, snapshot)
            if rising_reason:
                return rising_reason
        if config.min_session_pullback_percent > 0:
            pullback = getattr(snapshot, "session_pullback_percent", None)
            if pullback is None:
                return "Hold (session pullback warming)"
            if pullback < config.min_session_pullback_percent:
                return f"Hold (no pullback yet {pullback:.2f}%)"
        if snapshot.smi is None:
            return "Hold (SMI warming)"
        if snapshot.smi < config.min_smi:
            return f"Hold (SMI {snapshot.smi:.1f} below {config.min_smi})"
        if snapshot.relative_volume is None:
            return "Hold (volume warming)"
        if not getattr(snapshot, "volume_ok", True):
            avg_volume = getattr(snapshot, "avg_volume", None)
            if config.min_avg_volume > 0 and avg_volume is not None and avg_volume < config.min_avg_volume:
                return f"Hold (avg volume {avg_volume:,.0f} below {config.min_avg_volume:,.0f})"
            return f"Hold (volume {snapshot.relative_volume:.2f}x of average)"
        flow_reason = self.order_flow_hold_reason(symbol, config)
        if flow_reason:
            return flow_reason
        return ""

    def remember_stream_trade(self, symbol: str, price: Decimal, timestamp: Any) -> None:
        """Keep the newest streamed trade per symbol, judged by the trade's own timestamp (lock held)."""
        traded_at = self.parse_order_datetime(timestamp) or datetime.now(timezone.utc)
        current = self.latest_stream_trades.get(symbol)
        if current is None or traded_at >= current[1]:
            self.latest_stream_trades[symbol] = (price, traded_at)

    def latest_stream_trade(self, symbol: str, max_age_seconds: float = 120.0) -> tuple[Decimal, datetime] | None:
        """The latest cached trade and its time when fresh, without an API call."""
        with self.lock:
            entry = self.latest_stream_trades.get(symbol.strip().upper())
        if not entry:
            return None
        price, traded_at = entry
        if price <= 0 or (datetime.now(timezone.utc) - traded_at).total_seconds() > max_age_seconds:
            return None
        return entry

    def latest_stream_price(self, symbol: str, max_age_seconds: float = 120.0) -> Decimal | None:
        trade = self.latest_stream_trade(symbol, max_age_seconds)
        return trade[0] if trade else None

    def rising_price_hold_reason(self, symbol: str, snapshot: Any) -> str:
        """Hold unless the price is still rising: the last completed bar closed at or above the one
        before it, and the latest streamed trade (if fresh) has not fallen below that last close."""
        change = getattr(snapshot, "last_bar_change_percent", None)
        if change is None:
            return "Hold (last bar warming)"
        if change < Decimal("0"):
            return f"Hold (last bar {change:+.2f}%)"
        last_close = getattr(snapshot, "price", None)
        live = self.latest_stream_price(symbol)
        if live is not None and last_close is not None and last_close > 0 and live < last_close:
            slip = percent_change(live, last_close)
            return f"Hold (price slipping {slip:+.2f}% since last bar)"
        return ""

    def inverse_etf_hold_reason(self, symbol: str, config: AppConfig) -> str:
        clean_symbol = symbol.strip().upper()
        is_inverse = clean_symbol in INVERSE_ETF_SYMBOLS
        if config.inverse_etf_mode == "exclude" and is_inverse:
            return "Hold (inverse ETF excluded)"
        if config.inverse_etf_mode == "inverse_only" and not is_inverse:
            return "Hold (inverse-only profile)"
        return ""

    def halt_hold_reason(self, symbol: str) -> str:
        clean_symbol = symbol.strip().upper()
        with self.lock:
            halted = clean_symbol in self.halted_symbols
            status = dict(self.latest_trading_statuses.get(clean_symbol) or {})
        if halted or self.is_halt_status(status):
            detail = self.trading_status_label(status)
            return f"Hold (halt/status {detail})"
        return ""

    def order_flow_ratio(self, symbol: str) -> Decimal | None:
        clean_symbol = symbol.strip().upper()
        with self.lock:
            rows = [dict(row) for row in self.top_volume_rows]
        for row in rows:
            if str(row.get("symbol") or "").upper() != clean_symbol:
                continue
            buy_volume = decimal_value(row.get("buy_volume_raw"))
            sell_volume = decimal_value(row.get("sell_volume_raw"))
            classified = buy_volume + sell_volume
            if classified < ORDER_FLOW_MIN_CLASSIFIED_VOLUME:
                return None
            return buy_volume / classified if classified > 0 else None
        return None

    def order_flow_hold_reason(self, symbol: str, config: AppConfig) -> str:
        ratio = self.order_flow_ratio(symbol)
        if ratio is None:
            return ""
        floor = config.min_buy_volume_ratio
        if floor <= 0:
            return ""
        if ratio < floor:
            return f"Hold (buy flow {ratio * Decimal('100'):.1f}%)"
        return ""

    def asset_tradeability_hold_reason(self, symbol: str) -> str:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return "Hold (asset missing)"
        now = time.monotonic()
        with self.lock:
            cached = self.asset_tradeability_cache.get(clean_symbol)
            if cached and now - cached[0] < ASSET_CHECK_CACHE_SECONDS:
                return cached[1]
        client = self.trading_client
        if client is None:
            return ""
        reason = ""
        try:
            asset = client.get_asset(clean_symbol)
            raw = model_dict(asset)
            status = str(raw.get("status") or "").strip().lower()
            tradable = raw.get("tradable")
            fractionable = raw.get("fractionable")
            if status and status != "active":
                reason = f"Hold (asset {status})"
            elif tradable is False:
                reason = "Hold (asset not tradable)"
            elif fractionable is False:
                reason = "Hold (not fractionable)"
        except Exception as exc:
            self.log("warn", f"Asset precheck failed for {clean_symbol}; leaving symbol eligible: {exc}")
        with self.lock:
            self.asset_tradeability_cache[clean_symbol] = (now, reason)
        return reason

    def entry_candidate(
        self,
        symbol: str,
        rank: int,
        account: dict[str, Any],
        position: dict[str, Any] | None,
        open_position_count: int,
        open_orders: list[dict[str, Any]],
        entries_allowed: bool,
    ) -> dict[str, Any] | None:
        config = self.config
        snapshot = self.snapshot(symbol)
        self.clear_entry_score(symbol)

        if snapshot.price is None:
            self.strategy_state.last_action[symbol] = "Hold (Waiting)"
            return None

        qty = decimal_value(position.get("qty")) if position else Decimal("0")
        if qty > 0:
            return None

        order_roles = [self.order_role(order, set()) for order in open_orders]
        buy_hold = self.order_hold_reason(symbol, OrderSide.BUY)
        if buy_hold:
            self.strategy_state.last_action[symbol] = buy_hold
            return None
        if "Pending Entry" in order_roles:
            self.strategy_state.last_action[symbol] = "Hold (entry pending)"
            return None
        if "Protective Exit" in order_roles:
            self.strategy_state.last_action[symbol] = "Hold (orphan exit order)"
            return None
        if "Manual/Unknown" in order_roles:
            self.strategy_state.last_action[symbol] = "Hold (manual order)"
            return None
        if not entries_allowed:
            self.strategy_state.last_action[symbol] = "Hold (entry guard)"
            return None
        if config.max_entries_per_symbol_per_day > 0:
            with self.lock:
                entries_today = self.entries_today_by_symbol.get(symbol.strip().upper(), 0)
            if entries_today >= config.max_entries_per_symbol_per_day:
                self.strategy_state.last_action[symbol] = f"Hold (bought {entries_today}x today)"
                return None
        if self.inverse_trend_active(symbol, config):
            return self.inverse_trend_entry_candidate(symbol, rank, snapshot, config)
        if config.entry_mode == "inplay":
            return self.inplay_entry_candidate(symbol, rank, snapshot, config)
        if config.entry_mode == "orb":
            return self.orb_entry_candidate(symbol, rank, snapshot, config)
        if uses_mover_readings(config):
            return self.movers_entry_candidate(symbol, rank, snapshot, config)
        quality_hold = self.entry_quality_hold_reason(symbol, snapshot, config)
        if quality_hold:
            self.strategy_state.last_action[symbol] = quality_hold
            return None
        flow_ratio = self.order_flow_ratio(symbol)
        score = self.entry_score(snapshot, config, flow_ratio)
        self.set_entry_score(symbol, score)
        if score < config.min_entry_score:
            self.strategy_state.last_action[symbol] = f"Hold (score {score:.1f} < {config.min_entry_score})"
            return None
        climb_hold = self.climbing_reentry_hold_reason(symbol, score, config, snapshot.price)
        if climb_hold:
            self.strategy_state.last_action[symbol] = climb_hold
            return None
        reentry_floor = self.reentry_score_floors.get(symbol)
        if uses_reentry_floor(config) and reentry_floor is not None and score < reentry_floor:
            self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
            return None
        self.strategy_state.last_action[symbol] = f"Candidate score {score:.1f}"
        return {"symbol": symbol, "rank": rank, "score": score}

    def climbing_reentry_hold_reason(
        self, symbol: str, score: Decimal, config: AppConfig, price: Decimal | None = None
    ) -> str:
        """The climbing re-entry rule for a scored account that does not use the mover readings
        (accounts that do are checked in movers_entry_hold_reason): the bar raised by each losing
        exit, and by a sale at a gain until the stock trades above the high it was sold from."""
        if not uses_climbing_reentry(config) or uses_mover_readings(config):
            return ""
        clean = symbol.strip().upper()
        needed, losses = self.movers_reentry_bar(clean, config)
        old_high = self.movers_unbeaten_high(clean, price)
        if old_high is not None:
            needed += max(Decimal("0"), config.reentry_score_boost)
        if score >= needed or not (losses or old_high is not None):
            return ""
        why = []
        if losses:
            why.append(f"{losses} losing exit{'' if losses == 1 else 's'} today")
        if old_high is not None:
            why.append(f"a sale at a gain, until it trades above ${old_high}")
        return f"Hold (re-entry needs {needed:.0f} after {' and '.join(why)}; score {score:.0f})"

    def inverse_trend_active(self, symbol: str, config: AppConfig) -> bool:
        """True when this symbol trades by the inverse trend-hold rules instead of the profile's own."""
        return (
            bool(config.inverse_trend_hold)
            and config.inverse_etf_mode != "exclude"
            and symbol.strip().upper() in INVERSE_ETF_SYMBOLS
        )

    def inverse_trend_entry_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        halt_reason = self.halt_hold_reason(symbol)
        if halt_reason:
            return halt_reason
        with self.lock:
            entries_today = self.entries_today_by_symbol.get(symbol.strip().upper(), 0)
        if config.inverse_trend_max_entries > 0 and entries_today >= config.inverse_trend_max_entries:
            return f"Hold (trend hold: bought {entries_today}x today)"
        vwap_distance = getattr(snapshot, "vwap_distance_percent", None)
        session_change = getattr(snapshot, "session_change_percent", None)
        if vwap_distance is None or session_change is None or snapshot.bias == "Waiting":
            return "Hold (trend hold warming)"
        if not self.inverse_trend_session_ready(symbol):
            return "Hold (trend hold warming)"
        if vwap_distance <= 0:
            return f"Hold (trend hold: {vwap_distance:+.2f}% vs VWAP)"
        if snapshot.bias != "Bullish":
            return f"Hold (trend {snapshot.bias})"
        if session_change <= 0:
            return f"Hold (trend hold: session {session_change:+.2f}%)"
        return self.asset_tradeability_hold_reason(symbol)

    def inverse_trend_entry_candidate(
        self, symbol: str, rank: int, snapshot: Any, config: AppConfig
    ) -> dict[str, Any] | None:
        hold = self.inverse_trend_entry_hold_reason(symbol, snapshot, config)
        if hold:
            self.strategy_state.last_action[symbol] = hold
            return None
        # A fund that passes is the downturn signal, so it ranks ahead of ordinary candidates.
        score = Decimal("100") - Decimal(rank) / Decimal("100")
        self.set_entry_score(symbol, score)
        self.strategy_state.last_action[symbol] = "Candidate trend hold"
        return {"symbol": symbol, "rank": rank, "score": score}

    def inverse_trend_session_ready(self, symbol: str) -> bool:
        """Today's session VWAP exists: the bars are from the current session (when the market clock
        says which one that is). Right at the open the newest bar is still yesterday's."""
        session_date, regular_bars = self.strategy_state.session_bar_info(symbol)
        with self.lock:
            clock_date = str(self.market_clock.get("session_date") or "")
        if clock_date and session_date and session_date != clock_date:
            return False
        return regular_bars >= 1

    def inverse_trend_exit_reason(self, symbol: str, config: AppConfig, current_gain: Decimal) -> str:
        """The trend is over once the fund is back under its session VWAP by the exit buffer."""
        if not self.inverse_trend_session_ready(symbol):
            return ""
        vwap_distance = getattr(self.snapshot(symbol), "vwap_distance_percent", None)
        if vwap_distance is None or vwap_distance >= -config.inverse_trend_exit_percent:
            return ""
        return f"trend hold ended: {vwap_distance:+.2f}% under VWAP (gain {current_gain:.2f}%)"

    def orb_entry_candidate(self, symbol: str, rank: int, snapshot: Any, config: AppConfig) -> dict[str, Any] | None:
        hold = self.orb_entry_hold_reason(symbol, snapshot, config)
        if hold:
            self.strategy_state.last_action[symbol] = hold
            return None
        # The scan list is already in priority order (relative-volume rank for the daily list).
        score = Decimal("100") - Decimal(rank)
        self.set_entry_score(symbol, score)
        self.strategy_state.last_action[symbol] = "Candidate ORB breakout"
        return {"symbol": symbol, "rank": rank, "score": score}

    def orb_entry_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        for reason in (self.inverse_etf_hold_reason(symbol, config), self.halt_hold_reason(symbol)):
            if reason:
                return reason
        with self.lock:
            entries_today = self.entries_today_by_symbol.get(symbol.strip().upper(), 0)
        if entries_today:
            return "Hold (ORB: one entry per day)"
        opening = self.strategy_state.opening_range(symbol, config.orb_minutes)
        if opening is None or not opening.complete:
            return "Hold (opening range forming)"
        price = snapshot.price
        if price <= opening.high:
            return f"Hold (inside opening range; high {opening.high})"
        breakout = (price / opening.high - Decimal("1")) * Decimal("100")
        if config.orb_max_breakout_percent > 0 and breakout > config.orb_max_breakout_percent:
            return f"Hold (breakout extended +{breakout:.2f}% past range)"
        vwap_distance = getattr(snapshot, "vwap_distance_percent", None)
        if vwap_distance is None or vwap_distance <= 0:
            return "Hold (below VWAP)"
        return self.order_flow_hold_reason(symbol, config) or self.asset_tradeability_hold_reason(symbol)

    def entry_score(self, snapshot: Any, config: AppConfig, flow_ratio: Decimal | None = None) -> Decimal:
        limits = entry_profile_limits(config)
        score = Decimal("0")
        if snapshot.rsi is not None:
            rsi_range = max(config.buy_rsi_max - config.buy_rsi_min, Decimal("1"))
            ideal_rsi = config.buy_rsi_min + (rsi_range * Decimal("0.55"))
            rsi_half_range = max(rsi_range / Decimal("2"), Decimal("1"))
            rsi_fit = Decimal("1") - (abs(snapshot.rsi - ideal_rsi) / rsi_half_range)
            score += clamp_decimal(rsi_fit) * config.score_weight_rsi
        if snapshot.relative_volume is not None:
            score += clamp_decimal(snapshot.relative_volume / Decimal("2.5")) * config.score_weight_relative_volume
        if snapshot.momentum_percent is not None:
            momentum_fit = (snapshot.momentum_percent - config.min_momentum_percent) / Decimal("1.5")
            score += clamp_decimal(momentum_fit) * config.score_weight_momentum
        recent_momentum = getattr(snapshot, "recent_momentum_percent", None)
        if recent_momentum is not None:
            score += clamp_decimal((recent_momentum - limits["min_recent_momentum"]) / Decimal("1")) * config.score_weight_recent_momentum
        if getattr(snapshot, "long_momentum_percent", None) is not None:
            score += clamp_decimal(snapshot.long_momentum_percent / Decimal("4")) * config.score_weight_long_momentum
        if getattr(snapshot, "session_change_percent", None) is not None:
            score += clamp_decimal(snapshot.session_change_percent / Decimal("5")) * config.score_weight_session_change
        if getattr(snapshot, "vwap_distance_percent", None) is not None:
            vwap_score = clamp_decimal(snapshot.vwap_distance_percent / Decimal("1.5")) * config.score_weight_vwap
            if snapshot.vwap_distance_percent > Decimal("2"):
                excess_range = max(limits["max_vwap_extension"] - Decimal("2"), Decimal("1"))
                vwap_score -= (
                    clamp_decimal((snapshot.vwap_distance_percent - Decimal("2")) / excess_range)
                    * config.score_weight_vwap_extension_penalty
                )
            score += max(Decimal("0"), vwap_score)
        if snapshot.smi is not None:
            smi_range = max(Decimal("80") - config.min_smi, Decimal("1"))
            score += clamp_decimal((snapshot.smi - config.min_smi) / smi_range) * config.score_weight_smi
        volatility = getattr(snapshot, "atr_percent", None) or getattr(snapshot, "volatility_percent", None)
        if volatility is not None:
            score += clamp_decimal(volatility / Decimal("2")) * config.score_weight_volatility
        if flow_ratio is None:
            score += config.score_weight_liquidity_bonus
        else:
            score += clamp_decimal(flow_ratio) * config.score_weight_flow

        penalty = Decimal("0")
        session_change = getattr(snapshot, "session_change_percent", None)
        if session_change is not None and session_change > Decimal("4"):
            penalty += (
                clamp_decimal((session_change - Decimal("4")) / Decimal("2"))
                * config.score_weight_session_extension_penalty
            )
        session_pullback = getattr(snapshot, "session_pullback_percent", None)
        if session_pullback is not None:
            session_pullback_weight = (
                config.score_weight_session_pullback_penalty
                if config.score_weight_session_pullback_penalty > 0
                else config.score_weight_pullback_penalty
            )
            penalty += clamp_decimal(session_pullback / limits["max_session_pullback"]) * session_pullback_weight
        recent_pullback = getattr(snapshot, "recent_pullback_percent", None)
        if recent_pullback is not None:
            recent_pullback_weight = (
                config.score_weight_recent_pullback_penalty
                if config.score_weight_recent_pullback_penalty > 0
                else config.score_weight_pullback_penalty
            )
            penalty += clamp_decimal(recent_pullback / limits["max_recent_pullback"]) * recent_pullback_weight
        if volatility is not None:
            penalty += clamp_decimal(volatility / Decimal("2")) * config.score_weight_volatility_penalty
        if snapshot.smi is not None and snapshot.smi > Decimal("85"):
            overheat_weight = (
                config.score_weight_smi_overheat_penalty
                if config.score_weight_smi_overheat_penalty > 0
                else config.score_weight_overbought_penalty
            )
            penalty += clamp_decimal((snapshot.smi - Decimal("85")) / Decimal("15")) * overheat_weight

        return min(Decimal("100"), max(Decimal("0"), score - penalty)).quantize(Decimal("0.1"))

    def apply_strategy(
        self,
        symbol: str,
        account: dict[str, Any],
        position: dict[str, Any] | None,
        open_position_count: int,
        open_orders: list[dict[str, Any]],
        total_exposure: Decimal,
        entries_allowed: bool = True,
        entry_guard_detail: str = "",
        opening_guard_detail: str = "",
        allow_entries: bool = True,
    ) -> tuple[list[tuple[str, str]], bool, dict[str, Any] | None]:
        config = self.config
        snapshot = self.snapshot(symbol)
        events: list[tuple[str, str]] = []

        if snapshot.price is None:
            return events, False, None

        equity = decimal_value(account.get("equity"))

        qty = decimal_value(position.get("qty")) if position else Decimal("0")
        has_long = qty > 0
        position_symbols = {symbol} if has_long else set()
        order_roles = [self.order_role(order, position_symbols) for order in open_orders]
        pending_entry = "Pending Entry" in order_roles
        pending_strategy_exit = "Strategy Exit" in order_roles
        protective_orders = [
            order for order, role in zip(open_orders, order_roles) if role == "Protective Exit"
        ]
        unknown_orders = [order for order, role in zip(open_orders, order_roles) if role == "Manual/Unknown"]
        buy_hold = self.order_hold_reason(symbol, OrderSide.BUY)
        sell_hold = self.order_hold_reason(symbol, OrderSide.SELL)

        protection_active = bool(protective_orders)
        if has_long and any(self.is_app_entry_order(order) for order in open_orders):
            # The app's market buy has partly filled and is still open. Alpaca rejects a sell stop
            # (or sell) beside an open buy as a potential wash trade, so protect the full quantity
            # once it fills.
            self.strategy_state.last_action[symbol] = "Hold (entry still filling)"
            return events, False, None
        if has_long and config.use_bracket_orders and pending_strategy_exit:
            downgrade_events = self.downgrade_stale_take_profit(
                symbol, position, snapshot, open_orders, order_roles, opening_guard_detail
            )
            if downgrade_events is not None:
                events.extend(downgrade_events)
                return events, False, None
        # A trend hold that has ended is sold now: re-pricing its stop first would cancel the stop
        # for a replacement and push the sell out by a pass or two.
        trend_exit_due = (
            has_long
            and config.use_bracket_orders
            and not pending_strategy_exit
            and self.inverse_trend_active(symbol, config)
            and bool(self.inverse_trend_exit_reason(symbol, config, Decimal("0")))
        )
        if has_long and config.use_bracket_orders and not pending_strategy_exit and not trend_exit_due:
            protection_events, exit_submitted, protection_active, placed_protective = self.ensure_position_exit_orders(
                symbol,
                position,
                snapshot,
                protective_orders,
            )
            events.extend(protection_events)
            if exit_submitted or placed_protective:
                return events, False, None

        local_exit_reason, local_hold_reason = self.local_protection_exit_decision(
            symbol,
            config,
            position,
            snapshot.price,
            any(self.protective_exit_kind(order) == "take_profit" for order in protective_orders),
            any(self.protective_exit_kind(order) == "stop_loss" for order in protective_orders),
        )
        if has_long and local_hold_reason and not pending_strategy_exit:
            self.strategy_state.last_action[symbol] = local_hold_reason
            return events, False, None
        if has_long and local_exit_reason and not pending_strategy_exit:
            if opening_guard_detail and self.is_stop_loss_exit_reason(local_exit_reason):
                self.strategy_state.last_action[symbol] = "Hold (open guard stop-loss)"
                return events, False, None
            if opening_guard_detail and self.is_trend_hold_exit_reason(local_exit_reason):
                # VWAP is a handful of bars old right after the open; let it settle first.
                self.strategy_state.last_action[symbol] = "Hold (open guard trend exit)"
                return events, False, None
            if sell_hold:
                self.strategy_state.last_action[symbol] = sell_hold
                return events, False, None
            cancelled = self.cancel_orders_for_symbol(protective_orders, symbol)
            if cancelled is None or (cancelled and not self.wait_for_symbol_app_orders_cleared(symbol)):
                self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
                return events, False, None
            # The position snapshot predates the cancel, so its qty_available still leaves out the
            # shares the app's own stop was holding. A trend-hold exit always fires beside a live
            # stop; without adding them back it would re-place the stop and never sell.
            released = sum(
                (
                    max(Decimal("0"), abs(decimal_value(order.get("qty"))) - abs(decimal_value(order.get("filled_qty"))))
                    for order in protective_orders
                    if self.is_app_protective_order(order)
                ),
                Decimal("0"),
            )
            qty_to_sell = min(abs(qty), self.sellable_qty(position) + released)
            if cancelled:
                # The cancelled stop may have partly filled after the order list was read. A fresh
                # position says exactly what is left to sell; fall back to the estimate without it.
                fresh_qty = self.fresh_sellable_qty(symbol)
                if fresh_qty is not None:
                    qty_to_sell = fresh_qty
            if qty_to_sell <= 0:
                self.strategy_state.last_action[symbol] = "Hold (shares held by a working order)"
                return events, False, None
            if self.is_take_profit_exit_reason(local_exit_reason):
                take_profit_price = self.position_take_profit_price(
                    symbol, decimal_value(position.get("avg_entry_price")), config
                )
                _, limit_events = self.submit_limit_exit_order(
                    symbol,
                    qty_to_sell,
                    snapshot,
                    local_exit_reason,
                    take_profit_price,
                )
                events.extend(limit_events)
            else:
                events.extend(self.submit_exit_order(symbol, qty_to_sell, snapshot, local_exit_reason))
            return events, False, None

        if allow_entries and not has_long:
            if buy_hold:
                self.strategy_state.last_action[symbol] = buy_hold
                return events, False, None
            if pending_entry:
                self.strategy_state.last_action[symbol] = "Hold (entry pending)"
                return events, False, None
            if protective_orders:
                self.strategy_state.last_action[symbol] = "Hold (orphan exit order)"
                return events, False, None
            if unknown_orders:
                self.strategy_state.last_action[symbol] = "Hold (manual order)"
                return events, False, None
            if not entries_allowed:
                self.strategy_state.last_action[symbol] = "Hold (entry guard)"
                return events, False, None
            quality_hold = self.entry_quality_hold_reason(symbol, snapshot, config)
            if quality_hold:
                self.strategy_state.last_action[symbol] = quality_hold
                return events, False, None
            entry_score = self.strategy_state.entry_score.get(symbol)
            if entry_score is None:
                entry_score = self.entry_score(snapshot, config, self.order_flow_ratio(symbol))
                self.set_entry_score(symbol, entry_score)
            # A trend-hold candidate has no real score (its number only orders it), so neither the
            # minimum score nor a re-entry floor left by an earlier stop applies to it.
            scored_entry = not self.inverse_trend_active(symbol, config) and config.entry_mode != "inplay"
            if scored_entry and entry_score < config.min_entry_score:
                self.strategy_state.last_action[symbol] = f"Hold (score {entry_score:.1f} < {config.min_entry_score})"
                return events, False, None
            climb_hold = self.climbing_reentry_hold_reason(symbol, entry_score, config, snapshot.price) if scored_entry else ""
            if climb_hold:
                self.strategy_state.last_action[symbol] = climb_hold
                return events, False, None
            reentry_floor = self.reentry_score_floors.get(symbol)
            # A floor only binds an account on the floor rule; the climbing rule keeps its own count.
            if scored_entry and uses_reentry_floor(config) and reentry_floor is not None and entry_score < reentry_floor:
                self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
                return events, False, None
            if config.max_open_positions > 0 and open_position_count >= config.max_open_positions:
                self.strategy_state.last_action[symbol] = "Hold (max positions)"
                return events, False, None

            order_price = self.current_trade_price(symbol, snapshot.price)
            if uses_mover_readings(config) and scored_entry:
                # The order lookup can reveal a more recent trade than the one used for ranking.
                self.clear_entry_score(symbol)
                hold = self.movers_entry_hold_reason(symbol, self.snapshot(symbol), config)
                if hold:
                    self.strategy_state.last_action[symbol] = hold
                    return events, False, None
                entry_score = self.strategy_state.entry_score.get(symbol)
                if (
                    uses_reentry_floor(config)
                    and reentry_floor is not None
                    and entry_score is not None
                    and entry_score < reentry_floor
                ):
                    self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
                    return events, False, None
            if config.entry_mode == "inplay":
                # The order goes at the live price, which can be past the chase limit by now.
                with self.lock:
                    pick = self.inplay_picks.get(symbol)
                chase_hold = inplay_logic.entry_hold_reason(pick, order_price, config.inplay_max_chase_percent) if pick else "Hold (in play: not a pick)"
                if chase_hold:
                    self.strategy_state.last_action[symbol] = chase_hold
                    return events, False, None
            reference_premium = percent_change(order_price, snapshot.price)
            if reference_premium > MAX_ENTRY_REFERENCE_PREMIUM_PERCENT:
                self.strategy_state.last_action[symbol] = (
                    f"Hold (wide order reference +{reference_premium:.2f}%)"
                )
                return events, False, None
            buying_power = decimal_value(account.get("buying_power"))
            notional = self.trade_notional(config, equity, buying_power, total_exposure, order_price)
            if notional <= 0:
                self.strategy_state.last_action[symbol] = "Hold (block budget)"
                return events, False, None
            qty_to_buy = order_quantity(notional, order_price)
            if qty_to_buy <= 0:
                events.append(("warn", f"Skipped {symbol}: calculated quantity is zero."))
                return events, False, None
            entry_notes = [entry_guard_detail]
            if uses_mover_readings(config):
                with self.lock:
                    mover_score = self.mover_scores.get(symbol)
                if mover_score is not None:
                    entry_notes.append(f"movers: {mover_score.describe()}")
            if config.entry_mode == "inplay":
                with self.lock:
                    day_pick = self.inplay_picks.get(symbol)
                if day_pick is not None:
                    entry_notes.append(f"in play #{day_pick.rank + 1}: {day_pick.describe()}")
            if entry_score is not None:
                entry_notes.append(f"score={entry_score:.1f}")
            if config.use_bracket_orders and self.is_fractional_quantity(qty_to_buy):
                entry_notes.append("fractional entry; manual DAY exit orders")

            order = self.build_order(symbol, OrderSide.BUY, qty_to_buy, order_price)
            client_order_id = str(getattr(order, "client_order_id", ""))
            entry_notes.append(f"target_notional={money(notional)}")
            price_note = f"order_ref={order_price}"
            entry_notes.append(price_note)
            intent_reason = self.intent_reason(
                snapshot,
                "; ".join(part for part in entry_notes if part),
            )
            if config.dry_run:
                self.record_order_intent(
                    symbol,
                    OrderSide.BUY,
                    qty_to_buy,
                    "Pending Entry",
                    "dry_run",
                    intent_reason,
                    client_order_id,
                )
                events.append(("info", f"Dry run: would buy {qty_to_buy} shares of {symbol}."))
            else:
                try:
                    submitted = self.submit_order_request(order)
                except OrderExecutionError as exc:
                    self.hold_rejected_order(
                        symbol,
                        OrderSide.BUY,
                        NON_FRACTIONABLE_HOLD_SECONDS if is_non_fractionable_error(str(exc)) else ORDER_REJECT_HOLD_SECONDS,
                    )
                    self.record_order_intent(
                        symbol,
                        OrderSide.BUY,
                        qty_to_buy,
                        "Pending Entry",
                        "error",
                        f"{intent_reason}; {exc}",
                        client_order_id,
                    )
                    self.mark_trade(symbol, "Order rejected")
                    events.append(("error", f"Entry order rejected for {symbol}: {exc}"))
                    return events, False, None
                submitted_id = getattr(submitted, "id", "")
                self.hold_submitted_order(symbol, OrderSide.BUY)
                self.record_order_intent(
                    symbol,
                    OrderSide.BUY,
                    qty_to_buy,
                    "Pending Entry",
                    "submitted",
                    intent_reason,
                    client_order_id,
                    str(submitted_id),
                )
                events.append(("success", f"Submitted buy order for {symbol}: {submitted_id}"))
            with self.lock:
                self.reentry_score_floors.pop(symbol, None)
            self.mark_trade(symbol, "Buy submitted")
            return events, False, {
                "side": "buy",
                "symbol": symbol,
                "notional": qty_to_buy * order_price,
            }

        elif has_long:
            if pending_strategy_exit:
                self.strategy_state.last_action[symbol] = "Hold (exit pending)"
            elif protective_orders:
                self.strategy_state.last_action[symbol] = "Hold (manual exit orders)"
            elif config.use_bracket_orders and self.is_fractional_quantity(abs(qty)):
                self.strategy_state.last_action[symbol] = "Hold (fractional local percent fallback)"
            else:
                self.strategy_state.last_action[symbol] = "Hold (position open)"
        else:
            self.strategy_state.last_action[symbol] = "Hold (entry disabled)"

        return events, False, None

    def snapshot(self, symbol: str):
        config = self.config
        return self.strategy_state.snapshot(
            symbol,
            config.short_period,
            config.long_period,
            config.rsi_period,
            config.volume_period,
            config.volume_multiplier,
            config.min_avg_volume,
            config.momentum_period,
            config.smi_period,
            config.atr_period,
        )

    def effective_daily_loss_limit(self, config: AppConfig, last_equity: Decimal) -> Decimal:
        """Strictest positive limit of the dollar and percent settings (0 = off).

        The percent is taken of yesterday's closing equity, which does not move during the day.
        """
        limits = []
        if config.daily_loss_limit > 0:
            limits.append(config.daily_loss_limit)
        if config.daily_loss_limit_percent > 0 and last_equity > 0:
            limits.append(last_equity * config.daily_loss_limit_percent / Decimal("100"))
        return min(limits) if limits else Decimal("0")

    def evaluate_daily_loss_limit(self, config: AppConfig, account: dict[str, Any], session_date: str) -> bool:
        """Latch a breach for the session once today's P/L reaches the loss limit.

        Today's P/L is equity minus last_equity from the account call made every refresh. The
        latch does not clear if equity recovers; it resets on the next session date.
        """
        if self.daily_loss_breach_session and self.daily_loss_breach_session != session_date:
            self.daily_loss_breach_session = ""
            self.daily_loss_detail = ""
        if self.daily_loss_breach_session == session_date:
            return True
        equity = decimal_value(account.get("equity"))
        last_equity = decimal_value(account.get("last_equity"))
        limit = self.effective_daily_loss_limit(config, last_equity)
        if limit <= 0 or equity <= 0 or last_equity <= 0:
            return False
        daily_pl = equity - last_equity
        if daily_pl > -limit:
            return False
        self.daily_loss_breach_session = session_date
        self.daily_loss_detail = f"down {money(-daily_pl)} today vs {money(limit)} limit; no new entries until next session"
        self.log("warn", f"Daily loss limit hit: {self.daily_loss_detail}.")
        self.alert("problem", "Daily loss limit hit", self.daily_loss_detail, key=f"loss-limit:{session_date}",
                   ttl_seconds=86400, urgency="critical")
        return True

    def flatten_for_daily_loss(
        self,
        position_map: dict[str, dict[str, Any]],
        flat_orders: list[dict[str, Any]],
    ) -> tuple[list[tuple[str, str]], set[str]]:
        return self.flatten_all_positions(position_map, flat_orders, "daily loss limit flatten")

    def flatten_all_positions(
        self,
        position_map: dict[str, dict[str, Any]],
        flat_orders: list[dict[str, Any]],
        reason: str,
    ) -> tuple[list[tuple[str, str]], set[str]]:
        """Market-sell every long position; returns events and the symbols handled this pass.

        `reason` must contain "flatten" so a rejected sell gets the short retry hold.
        """
        events: list[tuple[str, str]] = []
        handled: set[str] = set()
        for symbol, position in sorted(position_map.items()):
            if trading_halted():
                break
            raw_qty = decimal_value(position.get("qty"))
            if raw_qty <= 0 or str(position.get("side") or "long").lower() == "short":
                continue  # long-only bot: never "flatten" a short by selling more
            if decimal_value(position.get("current_price")) <= 0:
                continue
            symbol_orders = [order for order in flat_orders if str(order.get("symbol", "")).upper() == symbol]
            roles = [self.order_role(order, {symbol}) for order in symbol_orders]
            strategy_exits = [order for order, role in zip(symbol_orders, roles) if role == "Strategy Exit"]
            take_profit_limits = [
                order for order in strategy_exits
                if str(order.get("client_order_id") or "").startswith("apt-exit-")
                and str(order.get("type") or order.get("order_type") or "").lower() == "limit"
            ]
            if len(take_profit_limits) < len(strategy_exits):
                handled.add(symbol)  # a market exit is already working
                continue
            protective = [order for order, role in zip(symbol_orders, roles) if role == "Protective Exit"]
            # Shares held by the orders this pass cancels (the app's own stop and take-profit) are sold
            # too; Alpaca's qty_available excludes them, which left every stop-protected position
            # unsold at the 2026-11-09 close. Shares held by anything else stay out of the sell.
            released = sum(
                (
                    max(Decimal("0"), abs(decimal_value(order.get("qty"))) - abs(decimal_value(order.get("filled_qty"))))
                    for order in protective + take_profit_limits
                    if self.is_app_protective_order(order) or order in take_profit_limits
                ),
                Decimal("0"),
            )
            qty = min(raw_qty, self.sellable_qty(position) + released)
            if qty <= 0:
                handled.add(symbol)  # another order is already taking the shares
                continue
            if self.order_hold_reason(symbol, OrderSide.SELL):
                continue  # not handled: the normal pass keeps the stop in place meanwhile
            # From here this pass owns the symbol's exit: no new stop behind the flatten sell.
            handled.add(symbol)
            if take_profit_limits and not all(self.cancel_open_order(order) for order in take_profit_limits):
                events.append(("warn", f"Waiting for {symbol} take-profit cancellation before {reason}."))
                continue
            cancelled = self.cancel_orders_for_symbol(protective, symbol)
            if cancelled is None or (
                (cancelled or take_profit_limits)
                and not self.wait_for_symbol_app_orders_cleared(symbol, include_exits=True)
            ):
                events.append(("warn", f"Waiting for {symbol} order cancellation before {reason}."))
                continue
            # A stop can fill during cancellation or between the position and order snapshots.
            fresh_qty = self.fresh_sellable_qty(symbol)
            if fresh_qty is None:
                events.append(("warn", f"Waiting for a fresh {symbol} position before {reason}."))
                continue
            qty = min(qty, fresh_qty)
            if qty > 0:
                events.extend(self.submit_exit_order(symbol, qty, self.snapshot(symbol), reason))
        return events, handled

    def ensure_offhours_stop(
        self,
        symbol: str,
        position: dict[str, Any] | None,
        symbol_orders: list[dict[str, Any]],
        next_open: Any = None,
    ) -> list[tuple[str, str]]:
        """While the market is closed, make sure a DAY stop is queued for the next open.

        Never sells off-hours. Alpaca only allows DAY time-in-force for fractional quantities,
        so the stop is re-placed every session; a stop submitted after the close is queued.
        """
        if not position:
            return []
        qty = abs(decimal_value(position.get("qty")))
        entry_price = decimal_value(position.get("avg_entry_price"))
        current_price = decimal_value(position.get("current_price"))
        if qty <= 0 or entry_price <= 0:
            return []
        take_profit_price = self.position_take_profit_price(symbol, entry_price, self.config)
        self.seed_peak_from_live_stops(symbol, entry_price, symbol_orders, self.config)
        stop_loss_price = self.position_stop_price(symbol, entry_price, current_price, self.config)
        if stop_loss_price <= 0:
            return []
        roles = [self.order_role(order, {symbol}) for order in symbol_orders]
        if "Strategy Exit" in roles:
            return []
        if any(self.is_app_entry_order(order) for order in symbol_orders):
            # A sell stop beside the app's open buy is rejected as a potential wash trade.
            self.strategy_state.last_action[symbol] = "Hold (entry still filling)"
            return []
        protective = [order for order, role in zip(symbol_orders, roles) if role == "Protective Exit"]
        active = [
            order for order in protective
            if not self.cancel_stale_protective_order(order, qty, take_profit_price, stop_loss_price, entry_price)
        ]
        if len(active) < len(protective):
            # A stale stop was just cancelled; place the replacement on the next pass once Alpaca
            # has released the quantity, so a transient rejection doesn't block it until the open.
            return []
        if any(self.protective_exit_kind(order) == "stop_loss" for order in active):
            self.strategy_state.last_action[symbol] = "Protected (stop queued for next open)"
            return []
        if current_price <= 0:
            self.strategy_state.last_action[symbol] = "No market price; cannot place stop"
            return []
        if current_price <= stop_loss_price:
            self.strategy_state.last_action[symbol] = "Below stop; exits at the open"
            return []
        submitted, events, _ = self.submit_protective_exit_order(
            symbol,
            qty,
            "stop_loss",
            stop_loss_price,
            self.snapshot(symbol),
            f"off-hours stop-loss {self.position_stop_percent(symbol, self.config)}% queued for next open",
            reject_hold_until=next_open,
        )
        if submitted:
            self.strategy_state.last_action[symbol] = "Protected (stop queued for next open)"
        return events

    def downgrade_stale_take_profit(
        self,
        symbol: str,
        position: dict[str, Any],
        snapshot: Any,
        open_orders: list[dict[str, Any]],
        order_roles: list[str],
        opening_guard_detail: str = "",
    ) -> list[tuple[str, str]] | None:
        """A pending take-profit limit has no stop behind it; if price falls to the stop, sell."""
        entry_price = decimal_value(position.get("avg_entry_price"))
        current_price = decimal_value(position.get("current_price")) or (snapshot.price or Decimal("0"))
        stop_loss_price = self.position_stop_price(symbol, entry_price, current_price, self.config)
        if stop_loss_price <= 0 or current_price <= 0 or current_price > stop_loss_price:
            return None
        limit_exits = [
            order for order, role in zip(open_orders, order_roles)
            if role == "Strategy Exit"
            and str(order.get("client_order_id") or "").startswith("apt-exit-")
            and str(order.get("side", "")).lower() == "sell"
            and str(order.get("type") or order.get("order_type") or "").lower() == "limit"
        ]
        if not limit_exits:
            return None
        if opening_guard_detail:
            self.strategy_state.last_action[symbol] = "Hold (open guard stop-loss)"
            return []
        sell_hold = self.order_hold_reason(symbol, OrderSide.SELL)
        if sell_hold:
            self.strategy_state.last_action[symbol] = sell_hold
            return []
        events: list[tuple[str, str]] = []
        # Sell only once every take-profit limit is confirmed cancelled; a limit that could not be
        # cancelled may have filled, and a second full-quantity sell could then open a short.
        if not all(self.cancel_open_order(order) for order in limit_exits) or not self.wait_for_symbol_app_orders_cleared(
            symbol, include_exits=True
        ):
            events.append(("warn", f"Waiting for {symbol} take-profit cancellation before stop-loss sell."))
            return events
        qty = self.sellable_qty(position)
        if qty <= 0:
            events.append(("warn", f"Waiting for {symbol} shares to be released before stop-loss sell."))
            return events
        events.extend(
            self.submit_exit_order(
                symbol,
                qty,
                snapshot,
                (
                    f"trailing stop {money(stop_loss_price)} (take-profit limit unfilled, price fell back)"
                    if stop_loss_price >= entry_price
                    else f"stop-loss {self.position_stop_percent(symbol, self.config)}% (take-profit limit unfilled, price fell back)"
                ),
            )
        )
        return events

    def planned_entry_notional_cap(self, config: AppConfig, equity: Decimal, price: Decimal | None = None) -> Decimal:
        candidates: list[Decimal] = []
        if config.trade_size_mode == "notional" and config.max_trade_notional > 0:
            candidates.append(config.max_trade_notional)
        elif config.trade_size_mode == "percent" and config.max_trade_percent > 0 and equity > 0:
            candidates.append(equity * config.max_trade_percent / Decimal("100"))
        if config.max_total_exposure_percent > 0 and config.max_open_positions > 0 and equity > 0:
            exposure_budget = equity * config.max_total_exposure_percent / Decimal("100")
            candidates.append(exposure_budget / Decimal(config.max_open_positions))
        positive = [value for value in candidates if value > 0]
        return min(positive) if positive else Decimal("0")

    def trade_notional(
        self,
        config: AppConfig,
        equity: Decimal,
        buying_power: Decimal,
        total_exposure: Decimal,
        price: Decimal,
    ) -> Decimal:
        planned_cap = self.planned_entry_notional_cap(config, equity, price)
        if planned_cap < MIN_ENTRY_NOTIONAL:
            return Decimal("0")
        if buying_power < planned_cap:
            planned_cap = buying_power
        if config.max_total_exposure_percent > 0 and equity > 0:
            exposure_budget = equity * config.max_total_exposure_percent / Decimal("100")
            exposure_room = exposure_budget - total_exposure
            planned_cap = min(planned_cap, exposure_room)
        if planned_cap < MIN_ENTRY_NOTIONAL:
            return Decimal("0")
        return planned_cap

    def position_stop_price(
        self, symbol: str, entry_price: Decimal, current_price: Decimal, config: AppConfig
    ) -> Decimal:
        """The protective stop for a held position.

        Starts at the stop-loss percent below entry. Once the position's peak gain reaches
        breakeven_at_percent the stop rises to the entry price; once it reaches
        profit_trail_start_percent the stop trails profit_trail_drop_percent below the peak, floored
        to 0.25%-of-entry steps so the broker order is only replaced every quarter percent. The
        result only ever rises for a position (callers never lower a live stop below it).
        """
        if config.entry_mode == "inplay":
            with self.lock:
                pick = self.inplay_picks.get(symbol.strip().upper())
            if pick is not None and pick.stop > 0:
                # The pick's own stop (range middle or low).
                return max(Decimal("0"), self.round_exit_price(pick.stop, ROUND_DOWN))
            # No pick on record (picks lost after a restart): a wide percent stop still protects the
            # position, but never one tighter than INPLAY_FALLBACK_STOP_PERCENT, so it cannot raise
            # (and so trigger) the live range stop that was placed when the pick was known.
            if entry_price <= 0:
                return Decimal("0")
            percent = max(config.stop_loss_percent, INPLAY_FALLBACK_STOP_PERCENT)
            return self.percent_stop_price(entry_price, percent)
        if self.inverse_trend_active(symbol, config):
            # A wide stop from entry, so index noise cannot shake the hold out; the VWAP exit ends
            # it. Once the fund has been up the lock percent the profit is locked: the stop trails
            # the peak, never under entry, in the same quarter-percent steps as the normal trail.
            if entry_price <= 0:
                return Decimal("0")
            stop = self.percent_stop_price(entry_price, config.inverse_trend_stop_percent)
            if config.inverse_trend_lock_at_percent > 0 and config.inverse_trend_trail_percent > 0:
                peak = self.update_position_peak(symbol, entry_price, current_price if current_price > 0 else entry_price)
                if percent_change(peak, entry_price) >= config.inverse_trend_lock_at_percent:
                    trailed = peak * (Decimal("1") - config.inverse_trend_trail_percent / Decimal("100"))
                    step = entry_price * Decimal("0.0025")
                    if trailed > entry_price and step > 0:
                        trailed = entry_price + ((trailed - entry_price) // step) * step
                    stop = max(stop, entry_price, trailed)
            return max(Decimal("0"), self.round_exit_price(stop, ROUND_DOWN))
        _, stop = self.exit_prices(entry_price, config)
        if entry_price <= 0:
            return stop
        peak = self.update_position_peak(symbol, entry_price, current_price if current_price > 0 else entry_price)
        peak_gain = percent_change(peak, entry_price)
        if config.breakeven_at_percent > 0 and peak_gain >= config.breakeven_at_percent:
            stop = max(stop, entry_price)
        if (
            config.profit_trail_start_percent > 0
            and config.profit_trail_drop_percent > 0
            and peak_gain >= config.profit_trail_start_percent
        ):
            trailed = peak * (Decimal("1") - config.profit_trail_drop_percent / Decimal("100"))
            step = entry_price * Decimal("0.0025")
            if trailed > entry_price and step > 0:
                trailed = entry_price + ((trailed - entry_price) // step) * step
            # Rounded down like every other stop: rounded up, the trail on a $1-$2 stock lands on
            # the price itself (1% under a $1.245 peak is $1.2326; $1.24 is the market, $1.23 is a stop).
            stop = max(stop, trailed)
        if stop <= 0:
            return Decimal("0")
        return self.round_exit_price(stop, ROUND_DOWN)

    def seed_peak_from_live_stops(
        self, symbol: str, entry_price: Decimal, orders: list[dict[str, Any]], config: AppConfig
    ) -> None:
        """After a restart the in-memory peak is gone; a live app stop at or above entry says how
        far the position had run, so the computed stop agrees with it instead of falling back."""
        if entry_price <= 0:
            return
        for order in orders:
            if not self.is_app_protective_order(order) or self.protective_exit_kind(order) != "stop_loss":
                continue
            stop_price = decimal_value(order.get("stop_price"))
            if stop_price < entry_price or stop_price <= 0:
                continue
            implied_peak = entry_price
            if self.inverse_trend_active(symbol, config):
                if config.inverse_trend_trail_percent > 0 and stop_price > entry_price:
                    implied_peak = stop_price / (Decimal("1") - config.inverse_trend_trail_percent / Decimal("100"))
                implied_peak = max(
                    implied_peak,
                    entry_price * (Decimal("1") + config.inverse_trend_lock_at_percent / Decimal("100")),
                )
            elif config.profit_trail_drop_percent > 0 and stop_price > entry_price:
                implied_peak = stop_price / (Decimal("1") - config.profit_trail_drop_percent / Decimal("100"))
            elif config.breakeven_at_percent > 0:
                implied_peak = entry_price * (Decimal("1") + config.breakeven_at_percent / Decimal("100"))
            self.update_position_peak(symbol, entry_price, implied_peak)

    def position_take_profit_price(self, symbol: str, entry_price: Decimal, config: AppConfig) -> Decimal:
        """The profit target for a held position; none while an inverse fund is on trend hold, and none
        in day-trade mode, where winners run until the stop or the sale before the close."""
        if self.inverse_trend_active(symbol, config) or config.entry_mode == "inplay":
            return Decimal("0")
        return self.exit_prices(entry_price, config)[0]

    def position_stop_percent(self, symbol: str, config: AppConfig) -> Decimal:
        """The stop distance from entry that applies to this position, for log and order notes."""
        if config.entry_mode == "inplay":
            with self.lock:
                pick = self.inplay_picks.get(symbol.strip().upper())
            if pick is not None and pick.high > 0:
                return ((pick.high - pick.stop) / pick.high * Decimal("100")).quantize(Decimal("0.01"))
        if self.inverse_trend_active(symbol, config):
            return config.inverse_trend_stop_percent
        return config.stop_loss_percent

    def exit_prices(self, entry_price: Decimal, config: AppConfig) -> tuple[Decimal, Decimal]:
        take_profit = Decimal("0")
        stop_loss = Decimal("0")
        if entry_price <= 0:
            return take_profit, stop_loss
        if config.take_profit_percent > 0:
            take_profit_offset = max(
                entry_price * config.take_profit_percent / Decimal("100"),
                self.minimum_exit_offset(entry_price),
            )
            take_profit = self.round_exit_price(entry_price + take_profit_offset, ROUND_UP)
        if config.stop_loss_percent > 0:
            stop_loss = self.percent_stop_price(entry_price, config.stop_loss_percent)
        return take_profit, stop_loss

    def percent_stop_price(self, entry_price: Decimal, percent: Decimal) -> Decimal:
        """A long position's initial sell stop: the valid price nearest the configured percent under
        entry, and never the tick right under the fill. On a penny-spread stock that tick is the
        bid: Alpaca rejects a stop there ("stop price must be less than current price") and the
        position reads as stopped out the moment it is bought. A $1.19 fill at 1.25% gets $1.17."""
        stop = entry_price * (Decimal("1") - percent / Decimal("100"))
        if stop <= 0:
            return Decimal("0")
        increment = self.price_increment_for(stop)
        nearest = stop.quantize(increment, rounding=ROUND_HALF_UP)
        under_the_bid = self.round_exit_price(entry_price, ROUND_UP) - 2 * increment
        return max(Decimal("0"), min(nearest, under_the_bid))

    def ensure_position_exit_orders(
        self,
        symbol: str,
        position: dict[str, Any] | None,
        snapshot: Any,
        protective_orders: list[dict[str, Any]],
    ) -> tuple[list[tuple[str, str]], bool, bool, bool]:
        events: list[tuple[str, str]] = []
        if not position:
            return events, False, bool(protective_orders), False

        qty = abs(decimal_value(position.get("qty")))
        entry_price = decimal_value(position.get("avg_entry_price"))
        current_price = decimal_value(position.get("current_price"))
        if current_price <= 0 and snapshot.price is not None:
            current_price = snapshot.price
        if qty <= 0 or entry_price <= 0 or current_price <= 0:
            return events, False, bool(protective_orders), False

        take_profit_price = self.position_take_profit_price(symbol, entry_price, self.config)
        self.seed_peak_from_live_stops(symbol, entry_price, protective_orders, self.config)
        stop_loss_price = self.position_stop_price(symbol, entry_price, current_price, self.config)
        if take_profit_price <= 0 and stop_loss_price <= 0:
            return events, False, bool(protective_orders), False

        active_orders = [
            order for order in protective_orders
            if not self.cancel_stale_protective_order(order, qty, take_profit_price, stop_loss_price, entry_price)
        ]
        if len(active_orders) < len(protective_orders):
            # A stale stop was just cancelled (quantity, price or a trail ratchet); place the
            # replacement next pass once Alpaca has released the quantity. The local stop covers
            # the gap.
            self.strategy_state.last_action[symbol] = "Replacing protective order"
            return events, False, True, False
        take_profit_orders = [
            order for order in active_orders if self.protective_exit_kind(order) == "take_profit"
        ]
        stop_loss_orders = [
            order for order in active_orders if self.protective_exit_kind(order) == "stop_loss"
        ]
        current_gain = percent_change(current_price, entry_price)

        if stop_loss_price > 0 and current_price <= stop_loss_price and not stop_loss_orders:
            return self.submit_missing_stop_exit(symbol, position, snapshot, active_orders, stop_loss_price, current_price)

        if take_profit_price > 0 and current_price >= take_profit_price and not take_profit_orders:
            cancelled = self.cancel_orders_for_symbol(active_orders, symbol)
            if cancelled is None or (cancelled and not self.wait_for_symbol_app_orders_cleared(symbol)):
                self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
                events.append(("warn", f"Waiting for stop cancellation before placing take-profit limit for {symbol}."))
                return events, False, True, False
            submitted, submit_events = self.submit_limit_exit_order(
                symbol,
                qty,
                snapshot,
                f"manual take-profit limit {self.config.take_profit_percent}%"
                f" (gain {current_gain:.2f}%)",
                take_profit_price,
            )
            events.extend(submit_events)
            return events, submitted, submitted, False

        protection_active = bool(active_orders)
        # A protective order placed in this pass is not in this pass's order list, so callers must
        # not also send a local exit now (Alpaca would reject the sell: the stop holds the qty).
        placed_protective = False
        if stop_loss_price > 0 and not stop_loss_orders:
            submitted, submit_events, crossed_price = self.submit_protective_exit_order(
                symbol,
                qty,
                "stop_loss",
                stop_loss_price,
                snapshot,
                f"manual stop-loss {self.position_stop_percent(symbol, self.config)}%",
                recover_crossed_stop=True,
            )
            events.extend(submit_events)
            if crossed_price is not None:
                exit_events, exiting, protected, placed = self.submit_missing_stop_exit(
                    symbol, position, snapshot, active_orders, stop_loss_price, crossed_price, verify_at_broker=True
                )
                return events + exit_events, exiting, protected, placed
            protection_active = protection_active or submitted
            placed_protective = placed_protective or submitted
        if take_profit_price > 0 and not take_profit_orders:
            if stop_loss_price > 0 or stop_loss_orders:
                self.strategy_state.last_action[symbol] = f"Hold (profit target armed at {money(take_profit_price)})"
            else:
                submitted, submit_events, _ = self.submit_protective_exit_order(
                    symbol,
                    qty,
                    "take_profit",
                    take_profit_price,
                    snapshot,
                    f"manual take-profit limit {self.config.take_profit_percent}%",
                )
                events.extend(submit_events)
                protection_active = protection_active or submitted
                placed_protective = placed_protective or submitted
        return events, False, protection_active, placed_protective

    def submit_missing_stop_exit(
        self,
        symbol: str,
        position: dict[str, Any],
        snapshot: Any,
        active_orders: list[dict[str, Any]],
        stop_price: Decimal,
        market_price: Decimal,
        *,
        verify_at_broker: bool = False,
    ) -> tuple[list[tuple[str, str]], bool, bool, bool]:
        sell_hold = self.order_hold_reason(symbol, OrderSide.SELL)
        if sell_hold:
            self.strategy_state.last_action[symbol] = sell_hold
            return [], False, True, False
        cancelled = self.cancel_orders_for_symbol(active_orders, symbol)
        if cancelled is None or (cancelled and not self.wait_for_symbol_app_orders_cleared(symbol)):
            self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
            return [("warn", f"Waiting for existing exit order cancellation before selling {symbol}.")], False, True, False
        if verify_at_broker:
            try:
                client = self.require_trading_client()
                orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol], nested=True))
            except Exception as exc:
                self.record_runtime_exception(
                    "order_execution", "Crossed stop open-order check failed", OrderExecutionError(str(exc))
                )
                return [], False, False, False
            open_orders = self.flatten_orders([model_dict(item) for item in orders])
            if any(str(order.get("symbol") or "").upper() == symbol for order in open_orders):
                self.strategy_state.last_action[symbol] = "Hold (working order after stop rejection)"
                return [], False, False, False
        check_quantity = verify_at_broker or bool(cancelled)
        qty_to_sell = self.fresh_sellable_qty(symbol) if check_quantity else self.sellable_qty(position)
        if qty_to_sell is None or qty_to_sell <= 0:
            self.strategy_state.last_action[symbol] = (
                "Hold (no confirmed shares available to sell)" if check_quantity
                else "Hold (shares held by a working order)"
            )
            return [], False, True, False

        entry_price = decimal_value(position.get("avg_entry_price"))
        gain = percent_change(market_price, entry_price)
        detail = "broker confirmed stop crossed" if verify_at_broker else "manual stop missing"
        stop = (
            f"trailing stop {money(stop_price)}" if stop_price >= entry_price
            else f"stop-loss {self.position_stop_percent(symbol, self.config)}%"
        )
        events = self.submit_exit_order(symbol, qty_to_sell, snapshot, f"local {stop} (gain {gain:.2f}%, {detail})")
        return events, True, False, False

    def cancel_stale_protective_order(
        self,
        order: dict[str, Any],
        qty: Decimal,
        take_profit_price: Decimal,
        stop_loss_price: Decimal,
        entry_price: Decimal = Decimal("0"),
    ) -> bool:
        if not self.is_app_protective_order(order):
            return False
        order_qty = decimal_value(order.get("qty"))
        filled_qty = decimal_value(order.get("filled_qty"))
        kind = self.protective_exit_kind(order)
        if kind == "stop_loss" and filled_qty > 0:
            # The stop has triggered and is selling. Its size no longer matches the position (the
            # filled part has already left it), and cancelling it mid-fill only to sell the rest by
            # hand costs a rejected replacement stop and leaves the shares unprotected meanwhile.
            return False
        if order_qty > 0 and abs(order_qty - filled_qty - qty) > Decimal("0.0001"):
            return self.cancel_open_order(order)
        if kind == "take_profit" and take_profit_price > 0:
            limit_price = decimal_value(order.get("limit_price"))
            if limit_price > 0 and abs(limit_price - take_profit_price) >= self.price_increment_for(take_profit_price):
                return self.cancel_open_order(order)
        if kind == "stop_loss" and stop_loss_price > 0:
            stop_price = decimal_value(order.get("stop_price"))
            # Valid stops can differ by less than a cent across the dollar boundary.
            increment = min(self.price_increment_for(stop_price), self.price_increment_for(stop_loss_price))
            if stop_price > 0 and stop_loss_price - stop_price >= increment:
                return self.cancel_open_order(order)  # raise the stop (trail ratchet or config change)
            # Lower a stop only when it is a plain base stop below entry (a settings change). A stop
            # at or above entry came from break-even/trailing and is never lowered, restart or not.
            # Day-trade stops come from the pick's range and never loosen; a missing pick after a
            # restart must not swap the range stop for the wider fallback.
            if (
                stop_price > 0
                and stop_price < entry_price
                and stop_price - stop_loss_price >= increment
                and self.config.entry_mode != "inplay"
            ):
                return self.cancel_open_order(order)
        return False

    def submit_protective_exit_order(
        self,
        symbol: str,
        qty: Decimal,
        kind: str,
        price: Decimal,
        snapshot: Any,
        reason: str,
        reject_hold_until: Any = None,
        *,
        recover_crossed_stop: bool = False,
    ) -> tuple[bool, list[tuple[str, str]], Decimal | None]:
        events: list[tuple[str, str]] = []
        if self.protective_order_blocked(symbol, kind):
            return False, events, None
        client_kind = "tp" if kind == "take_profit" else "sl"
        client_order_id = f"apt-protect-{client_kind}-{symbol.lower()}-{int(time.time() * 1000)}"
        role = "Protective Exit"
        if kind == "take_profit":
            order = LimitOrderRequest(
                symbol=symbol,
                qty=float(qty),
                side=OrderSide.SELL,
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                limit_price=float(price),
                client_order_id=client_order_id,
            )
            price_note = f"limit={price}"
        else:
            order = StopOrderRequest(
                symbol=symbol,
                qty=float(qty),
                side=OrderSide.SELL,
                type=OrderType.STOP,
                time_in_force=TimeInForce.DAY,
                stop_price=float(price),
                client_order_id=client_order_id,
            )
            price_note = f"stop={price}"
        intent_reason = self.intent_reason(snapshot, f"{reason}; fractional DAY exit; {price_note}")
        if self.config.dry_run:
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty,
                role,
                "dry_run",
                intent_reason,
                client_order_id,
            )
            events.append(("info", f"Dry run: would place {kind.replace('_', ' ')} for {qty} {symbol} at {price}."))
            return True, events, None
        try:
            submitted = self.submit_order_request(order)
        except OrderExecutionError as exc:
            crossed_price = crossed_sell_stop_market_price(exc, price) if recover_crossed_stop else None
            if crossed_price is None:
                self.hold_rejected_protective_order(symbol, kind, until=reject_hold_until)
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty,
                role,
                "error",
                f"{intent_reason}; {exc}",
                client_order_id,
            )
            events.append(("error", f"Protective {kind.replace('_', ' ')} rejected for {symbol}: {exc}"))
            return False, events, crossed_price
        submitted_id = getattr(submitted, "id", "")
        self.record_order_intent(
            symbol,
            OrderSide.SELL,
            qty,
            role,
            "submitted",
            intent_reason,
            client_order_id,
            str(submitted_id),
        )
        events.append(("success", f"Submitted protective {kind.replace('_', ' ')} for {symbol}: {submitted_id}"))
        return True, events, None

    def local_protection_exit_decision(
        self,
        symbol: str,
        config: AppConfig,
        position: dict[str, Any] | None,
        strategy_price: Decimal | None,
        has_take_profit_order: bool,
        has_stop_loss_order: bool,
    ) -> tuple[str, str]:
        if not config.use_bracket_orders or not position:
            return "", ""
        qty = abs(decimal_value(position.get("qty")))
        if qty <= 0:
            return "", ""
        entry_price = decimal_value(position.get("avg_entry_price"))
        current_price = decimal_value(position.get("current_price"))
        if current_price <= 0 and strategy_price is not None:
            current_price = strategy_price
        if entry_price <= 0 or current_price <= 0:
            return "", ""

        current_gain = percent_change(current_price, entry_price)

        if self.inverse_trend_active(symbol, config):
            trend_exit = self.inverse_trend_exit_reason(symbol, config, current_gain)
            if trend_exit:
                return trend_exit, ""
            stop_price = self.position_stop_price(symbol, entry_price, current_price, config)
            if stop_price > 0 and current_price <= stop_price and not has_stop_loss_order:
                if stop_price >= entry_price:
                    return f"local trailing stop {money(stop_price)} (gain {current_gain:.2f}%)", ""
                return f"local stop-loss {config.inverse_trend_stop_percent}% (gain {current_gain:.2f}%)", ""
            return "", ""

        if (
            config.take_profit_percent > 0
            and config.entry_mode != "inplay"
            and current_gain >= config.take_profit_percent
            and not has_take_profit_order
        ):
            return (
                f"local take-profit {config.take_profit_percent}%"
                f" (gain {current_gain:.2f}%)",
                "",
            )

        stop_price = self.position_stop_price(symbol, entry_price, current_price, config)
        if stop_price > 0 and current_price <= stop_price and not has_stop_loss_order:
            if stop_price >= entry_price:
                return f"local trailing stop {money(stop_price)} (gain {current_gain:.2f}%)", ""
            return f"local stop-loss {config.stop_loss_percent}% (gain {current_gain:.2f}%)", ""
        return "", ""

    def is_stop_loss_exit_reason(self, reason: str) -> bool:
        text = str(reason or "").lower()
        return "stop-loss" in text or "trailing stop" in text

    def is_trend_hold_exit_reason(self, reason: str) -> bool:
        return str(reason or "").lower().startswith("trend hold ended")

    def is_take_profit_exit_reason(self, reason: str) -> bool:
        return "take-profit" in str(reason or "").lower()

    def submit_limit_exit_order(
        self,
        symbol: str,
        qty_to_sell: Decimal,
        snapshot: Any,
        reason: str,
        limit_price: Decimal,
    ) -> tuple[bool, list[tuple[str, str]]]:
        if limit_price <= 0:
            events = self.submit_exit_order(symbol, qty_to_sell, snapshot, reason)
            return bool(events), events
        events: list[tuple[str, str]] = []
        client_order_id = f"apt-exit-limit-{symbol.lower()}-{int(time.time() * 1000)}"
        order = LimitOrderRequest(
            symbol=symbol,
            qty=float(qty_to_sell),
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=float(limit_price),
            client_order_id=client_order_id,
        )
        intent_reason = self.intent_reason(snapshot, f"{reason}; limit={limit_price}")
        if self.config.dry_run:
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty_to_sell,
                "Strategy Exit",
                "dry_run",
                intent_reason,
                client_order_id,
            )
            events.append(("info", f"Dry run: would place take-profit limit for {qty_to_sell} shares of {symbol} at {limit_price}."))
            self.mark_exit_today(symbol)
            self.record_loss_reentry_floor(symbol, snapshot, reason)
            return True, events
        try:
            submitted = self.submit_order_request(order)
        except OrderExecutionError as exc:
            message = str(exc)
            self.hold_rejected_order(symbol, OrderSide.SELL, ORDER_REJECT_HOLD_SECONDS)
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty_to_sell,
                "Strategy Exit",
                "error",
                f"{intent_reason}; {message}",
                client_order_id,
            )
            self.mark_trade(symbol, "Take-profit limit rejected")
            events.append(("error", f"Take-profit limit rejected for {symbol}: {message}"))
            return False, events
        submitted_id = getattr(submitted, "id", "")
        self.record_order_intent(
            symbol,
            OrderSide.SELL,
            qty_to_sell,
            "Strategy Exit",
            "submitted",
            intent_reason,
            client_order_id,
            str(submitted_id),
        )
        events.append(("success", f"Submitted take-profit limit for {symbol} at {limit_price}: {submitted_id}"))
        self.hold_submitted_order(symbol, OrderSide.SELL)
        self.mark_exit_today(symbol)
        self.record_loss_reentry_floor(symbol, snapshot, reason)
        self.mark_trade(symbol, "Take-profit limit submitted")
        return True, events

    def submit_exit_order(
        self,
        symbol: str,
        qty_to_sell: Decimal,
        snapshot: Any,
        reason: str,
    ) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        order = self.build_order(symbol, OrderSide.SELL, qty_to_sell, snapshot.price)
        client_order_id = str(getattr(order, "client_order_id", ""))
        intent_reason = self.intent_reason(snapshot, reason)
        if self.config.dry_run:
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty_to_sell,
                "Strategy Exit",
                "dry_run",
                intent_reason,
                client_order_id,
            )
            events.append(("info", f"Dry run: would sell {qty_to_sell} shares of {symbol}."))
            self.mark_exit_today(symbol)
            self.record_loss_reentry_floor(symbol, snapshot, reason)
        else:
            try:
                submitted = self.submit_order_request(order)
            except OrderExecutionError as exc:
                message = str(exc)
                # Protective sells (stop-loss, loss-limit flatten) retry soon; while held, the normal
                # pass restores the stop so the position is not left unprotected.
                protective_sell = self.is_stop_loss_exit_reason(reason) or "flatten" in str(reason).lower()
                hold_seconds = STOP_LOSS_EXIT_REJECT_HOLD_SECONDS if protective_sell else ORDER_REJECT_HOLD_SECONDS
                self.hold_rejected_order(symbol, OrderSide.SELL, hold_seconds)
                self.record_order_intent(
                    symbol,
                    OrderSide.SELL,
                    qty_to_sell,
                    "Strategy Exit",
                    "error",
                    f"{intent_reason}; {message}",
                    client_order_id,
                )
                self.mark_trade(symbol, "Exit rejected")
                events.append(("error", f"Exit order rejected for {symbol}: {message}"))
                return events
            submitted_id = getattr(submitted, "id", "")
            self.record_order_intent(
                symbol,
                OrderSide.SELL,
                qty_to_sell,
                "Strategy Exit",
                "submitted",
                intent_reason,
                client_order_id,
                str(submitted_id),
            )
            events.append(("success", f"Submitted sell order for {symbol}: {submitted_id}"))
            self.hold_submitted_order(symbol, OrderSide.SELL)
            self.mark_exit_today(symbol)
            self.record_loss_reentry_floor(symbol, snapshot, reason)
        self.mark_trade(symbol, "Sell submitted")
        return events

    def current_trade_price(self, symbol: str, fallback: Decimal) -> Decimal:
        if self.config.dry_run:
            return fallback
        client = self.data_client
        if client is None:
            return fallback
        candidates: list[Decimal] = []
        try:
            trades = client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed(self.config.feed))
            )
            trade = trades.get(symbol) if isinstance(trades, dict) else None
            append_market_trade(trade, feed=self.config.feed, source="order_price_lookup")
            raw = model_dict(trade)
            price = decimal_value(raw.get("price"))
            if price > 0:
                candidates.append(price)
                if uses_mover_readings(self.config) and not self.inverse_trend_active(symbol, self.config):
                    traded_at = self.parse_order_datetime(raw.get("timestamp"))
                    if traded_at is not None:
                        with self.lock:
                            self.remember_stream_trade(symbol.strip().upper(), price, traded_at)
        except Exception as exc:
            self.log("warn", f"Latest trade price lookup failed for {symbol}; using strategy price: {exc}")
        try:
            quotes = client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed(self.config.feed))
            )
            quote = quotes.get(symbol) if isinstance(quotes, dict) else None
            append_market_quote(quote, feed=self.config.feed, source="order_price_lookup")
            raw_quote = model_dict(quote)
            bid = decimal_value(raw_quote.get("bid_price"))
            ask = decimal_value(raw_quote.get("ask_price"))
            if uses_mover_readings(self.config):
                with self.lock:
                    self.mover_quotes[symbol.strip().upper()] = (bid, ask, time.monotonic())
            if bid > 0:
                candidates.append(bid)
            if ask > 0:
                candidates.append(ask)
            if bid > 0 and ask > 0:
                candidates.append((bid + ask) / Decimal("2"))
        except Exception as exc:
            self.log("warn", f"Latest quote lookup failed for {symbol}; using trade/strategy price: {exc}")
        positive = [candidate for candidate in candidates if candidate > 0]
        return max(positive) if positive else fallback

    def price_increment_for(self, value: Decimal) -> Decimal:
        return SUB_DOLLAR_PRICE_INCREMENT if Decimal("0") < value < Decimal("1") else PRICE_INCREMENT

    def minimum_exit_offset(self, price: Decimal) -> Decimal:
        return self.price_increment_for(price)

    def round_exit_price(self, value: Decimal, rounding: str) -> Decimal:
        return value.quantize(self.price_increment_for(value), rounding=rounding)

    def is_fractional_quantity(self, qty: Decimal) -> bool:
        return qty != qty.to_integral_value()

    def prune_position_trackers(self, active_symbols: set[str]) -> None:
        active = {symbol.strip().upper() for symbol in active_symbols if symbol}
        with self.lock:
            for symbol in list(self.position_peak_prices):
                if symbol not in active:
                    self.position_peak_prices.pop(symbol, None)
            for symbol in list(self.entry_times):
                if symbol not in active and self.entry_lock_dates.get(symbol) != self.trade_day_key():
                    self.entry_times.pop(symbol, None)
            for key in list(self.protective_order_reject_holds):
                if key[0] not in active:
                    self.protective_order_reject_holds.pop(key, None)
            for holds in (self.order_submit_holds, self.order_reject_holds):
                for key in list(holds):
                    if key[1] == "sell" and key[0] not in active:
                        holds.pop(key, None)

    def update_position_peak(self, symbol: str, entry_price: Decimal, current_price: Decimal) -> Decimal:
        clean_symbol = symbol.strip().upper()
        seed = max(entry_price, current_price)
        if not clean_symbol:
            return seed
        with self.lock:
            peak = self.position_peak_prices.get(clean_symbol, seed)
            peak = max(peak, current_price, entry_price)
            self.position_peak_prices[clean_symbol] = peak
            return peak

    def stop_loss_grace_reason(self, symbol: str, config: AppConfig) -> str:
        grace_minutes = int(config.stop_loss_grace_minutes or 0)
        if grace_minutes <= 0:
            return ""
        clean_symbol = symbol.strip().upper()
        with self.lock:
            entry_time = self.entry_times.get(clean_symbol)
        if not entry_time:
            return ""
        elapsed = datetime.now(timezone.utc) - entry_time
        seconds_remaining = (grace_minutes * 60) - elapsed.total_seconds()
        if seconds_remaining <= 0:
            return ""
        minutes = max(1, int((seconds_remaining + 59) // 60))
        return f"Hold (stop-loss grace {minutes}m)"

    def order_side_text(self, side: OrderSide) -> str:
        return str(getattr(side, "value", side)).lower()

    def hold_rejected_order(self, symbol: str, side: OrderSide, seconds: int) -> None:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol or seconds <= 0:
            return
        key = (clean_symbol, self.order_side_text(side))
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        with self.lock:
            self.order_reject_holds[key] = until

    def sell_rejected(self, symbol: str) -> bool:
        """True while a sell of this symbol is on hold after the broker rejected it."""
        key = (symbol.strip().upper(), self.order_side_text(OrderSide.SELL))
        with self.lock:
            until = self.order_reject_holds.get(key)
        return bool(until and until > datetime.now(timezone.utc))

    def hold_submitted_order(self, symbol: str, side: OrderSide, seconds: int = ORDER_SUBMIT_HOLD_SECONDS) -> None:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol or seconds <= 0:
            return
        key = (clean_symbol, self.order_side_text(side))
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        with self.lock:
            self.order_submit_holds[key] = until

    def order_hold_reason(self, symbol: str, side: OrderSide) -> str:
        clean_symbol = symbol.strip().upper()
        key = (clean_symbol, self.order_side_text(side))
        side_text = self.order_side_text(side)
        with self.lock:
            submit_until = self.order_submit_holds.get(key)
            now = datetime.now(timezone.utc)
            if submit_until:
                if submit_until <= now:
                    self.order_submit_holds.pop(key, None)
                else:
                    minutes = max(1, int(((submit_until - now).total_seconds() + 59) // 60))
                    return f"Hold ({side_text} submitted {minutes}m ago)"
            until = self.order_reject_holds.get(key)
            if not until:
                return ""
            if until <= now:
                self.order_reject_holds.pop(key, None)
                return ""
        minutes = max(1, int(((until - now).total_seconds() + 59) // 60))
        return f"Hold ({side_text} blocked {minutes}m after rejected order)"

    def hold_rejected_protective_order(self, symbol: str, kind: str, until: Any = None) -> None:
        clean_symbol = symbol.strip().upper()
        clean_kind = kind.strip().lower()
        if not clean_symbol or not clean_kind:
            return
        hold_until = until if isinstance(until, datetime) else None
        if hold_until is not None and hold_until.tzinfo is None:
            hold_until = hold_until.replace(tzinfo=timezone.utc)
        until = hold_until or datetime.now(timezone.utc) + timedelta(seconds=PROTECTIVE_ORDER_REJECT_HOLD_SECONDS)
        with self.lock:
            self.protective_order_reject_holds[(clean_symbol, clean_kind)] = until

    def protective_order_blocked(self, symbol: str, kind: str) -> bool:
        clean_symbol = symbol.strip().upper()
        clean_kind = kind.strip().lower()
        key = (clean_symbol, clean_kind)
        with self.lock:
            until = self.protective_order_reject_holds.get(key)
            now = datetime.now(timezone.utc)
            if not until:
                return False
            if until <= now:
                self.protective_order_reject_holds.pop(key, None)
                return False
            return True

    def trade_day_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def mark_entry_today(self, symbol: str) -> None:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return
        with self.lock:
            self.entry_lock_dates[clean_symbol] = self.trade_day_key()
            self.entry_times[clean_symbol] = datetime.now(timezone.utc)

    def entered_today(self, symbol: str) -> bool:
        clean_symbol = symbol.strip().upper()
        with self.lock:
            return self.entry_lock_dates.get(clean_symbol) == self.trade_day_key()

    def mark_exit_today(self, symbol: str) -> None:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return
        with self.lock:
            self.exit_lock_dates[clean_symbol] = self.trade_day_key()
            self.position_peak_prices.pop(clean_symbol, None)

    def exited_today(self, symbol: str) -> bool:
        clean_symbol = symbol.strip().upper()
        with self.lock:
            return self.exit_lock_dates.get(clean_symbol) == self.trade_day_key()

    def restore_trade_guards_from_replay(self) -> None:
        path = replay_file_path()
        if not path.exists():
            return
        restored_entries: dict[str, str] = {}
        restored_entry_times: dict[str, datetime] = {}
        restored_exits: dict[str, str] = {}
        restored_holds: dict[tuple[str, str], datetime] = {}
        current_day = self.trade_day_key()
        non_fractionable_hold_until = datetime.now(timezone.utc) + timedelta(seconds=NON_FRACTIONABLE_HOLD_SECONDS)
        try:
            with REPLAY_LOCK:
                lines = path.read_text(encoding="utf-8").splitlines()[-2000:]
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("kind") != "order_intent":
                    continue
                payload = event.get("payload") or {}
                if str(payload.get("account_id") or "") != self.account_id:
                    continue
                symbol = str(payload.get("symbol") or "").strip().upper()
                side = str(payload.get("side") or "").strip().lower()
                status = str(payload.get("status") or "").strip().lower()
                reason = str(payload.get("reason") or "")
                if not symbol:
                    continue
                event_day = current_day
                parsed_event_time: datetime | None = None
                event_time = str(event.get("time") or "")
                if event_time:
                    try:
                        parsed_event_time = datetime.fromisoformat(event_time).astimezone(timezone.utc)
                        event_day = parsed_event_time.strftime("%Y-%m-%d")
                    except ValueError:
                        event_day = current_day
                if event_day != current_day:
                    continue
                if side == "buy" and status in {"submitted", "filled", "fill"}:
                    restored_entries[symbol] = current_day
                    if parsed_event_time:
                        restored_entry_times[symbol] = parsed_event_time
                if side == "sell" and status in {"submitted", "filled", "fill"}:
                    restored_exits[symbol] = current_day
                if side == "buy" and status == "error" and is_non_fractionable_error(reason):
                    restored_holds[(symbol, "buy")] = non_fractionable_hold_until
        except (OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
            self.record_runtime_exception(
                "replay",
                "Trade guard replay restore failed",
                ReplayPersistenceError(str(exc) or exc.__class__.__name__),
            )
            return
        with self.lock:
            self.entry_lock_dates.update(restored_entries)
            self.entry_times.update(restored_entry_times)
            self.exit_lock_dates.update(restored_exits)
            self.order_reject_holds.update(restored_holds)

    def build_order(self, symbol: str, side: OrderSide, qty: Decimal, price: Decimal) -> MarketOrderRequest:
        config = self.config
        client_prefix = "entry" if side == OrderSide.BUY else "exit"
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "qty": float(qty),
            "side": side,
            "type": OrderType.MARKET,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": f"apt-{client_prefix}-{symbol.lower()}-{int(time.time() * 1000)}",
        }

        return MarketOrderRequest(**kwargs)

    def in_cooldown(self, symbol: str) -> bool:
        cooldown = self.config.cooldown_minutes
        if cooldown <= 0:
            return False
        last = self.strategy_state.last_trade_at.get(symbol)
        if not last:
            return False
        elapsed = datetime.now(timezone.utc) - last
        return elapsed.total_seconds() < cooldown * 60

    def mark_trade(self, symbol: str, action: str) -> None:
        self.strategy_state.last_trade_at[symbol] = datetime.now(timezone.utc)
        self.strategy_state.last_action[symbol] = action

    def record_loss_reentry_floor(self, symbol: str, snapshot: Any, reason: str = "") -> None:
        # Only a losing exit raises the re-entry bar; a winner (take-profit, or a stop that fired
        # above entry) may come straight back through the normal entry checks.
        if self.is_stop_loss_exit_reason(reason) and "trailing stop" not in str(reason or "").lower():
            self.record_reentry_floor(symbol, snapshot, reason)

    def record_reentry_floor(self, symbol: str, snapshot: Any, reason: str = "") -> None:
        boost = self.config.reentry_score_boost
        if boost <= 0:
            return
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return
        if uses_mover_readings(self.config):
            # The score this account buys on: the mover readings (plus the old-style score when
            # its weights are on). The old-style score alone would be the wrong scale, or zero.
            result = movers_logic.score(self.mover_readings(clean_symbol, snapshot), self.mover_weights(self.config))
            score = result.total
            if uses_old_score(self.config):
                score += self.entry_score(snapshot, self.config, self.order_flow_ratio(clean_symbol))
        else:
            score = self.entry_score(snapshot, self.config, self.order_flow_ratio(clean_symbol))
        floor = min(Decimal("100"), max(self.config.min_entry_score, score + boost))
        with self.lock:
            self.reentry_score_floors[clean_symbol] = floor

    def intent_reason(self, snapshot: Any, extra: str = "") -> str:
        parts = [
            f"price={snapshot.price}",
            f"rsi={snapshot.rsi:.1f}" if snapshot.rsi is not None else "rsi=warming",
            f"momentum={snapshot.momentum_percent:+.2f}%" if getattr(snapshot, "momentum_percent", None) is not None else "momentum=warming",
            f"recent_momentum={snapshot.recent_momentum_percent:+.2f}%" if getattr(snapshot, "recent_momentum_percent", None) is not None else "recent_momentum=warming",
            f"long_momentum={snapshot.long_momentum_percent:+.2f}%" if getattr(snapshot, "long_momentum_percent", None) is not None else "long_momentum=warming",
            f"session={snapshot.session_change_percent:+.2f}%" if getattr(snapshot, "session_change_percent", None) is not None else "session=warming",
            f"session_pullback={snapshot.session_pullback_percent:.2f}%" if getattr(snapshot, "session_pullback_percent", None) is not None else "session_pullback=warming",
            f"recent_pullback={snapshot.recent_pullback_percent:.2f}%" if getattr(snapshot, "recent_pullback_percent", None) is not None else "recent_pullback=warming",
            f"vwap_dist={snapshot.vwap_distance_percent:+.2f}%" if getattr(snapshot, "vwap_distance_percent", None) is not None else "vwap=warming",
            f"smi={snapshot.smi:.1f}" if getattr(snapshot, "smi", None) is not None else "smi=warming",
            f"rel_vol={snapshot.relative_volume:.2f}" if snapshot.relative_volume is not None else "rel_vol=warming",
            f"atr={snapshot.atr_percent:.2f}%" if getattr(snapshot, "atr_percent", None) is not None else "atr=warming",
            f"volatility={snapshot.volatility_percent:.2f}%" if getattr(snapshot, "volatility_percent", None) is not None else "volatility=warming",
        ]
        if extra:
            parts.append(extra)
        return "; ".join(parts)

    def alert(self, kind: str, title: str, body: str, *, key: str = "", ttl_seconds: float = 0,
              urgency: str = "normal") -> None:
        """Desktop notification, gated by the account's alert settings; never blocks."""
        enabled = self.config.alert_trades if kind == "trade" else self.config.alert_problems
        if not enabled:
            return
        NOTIFIER.notify(f"{self.name}: {title}", body, key=f"{self.account_id}:{key}" if key else "",
                        ttl_seconds=ttl_seconds, urgency=urgency)

    def alert_new_fills(self, closed_orders: list[dict[str, Any]]) -> None:
        """Alert on orders that filled since the last refresh (the first refresh only seeds).

        Only the latest 100 closed orders are visible, so a fill older than that window when it
        first appears (rare: it would need 100 newer closed orders) is not alerted.
        """
        filled = [
            order for order in self.flatten_orders(closed_orders)
            if str(order.get("status") or "").lower() == "filled" and order.get("id")
        ]
        ids = {str(order["id"]) for order in filled}
        if self.alerted_fill_ids is None:
            self.alerted_fill_ids = ids
            return
        for order in filled:
            order_id = str(order["id"])
            if order_id in self.alerted_fill_ids:
                continue
            self.alerted_fill_ids.add(order_id)
            symbol = str(order.get("symbol") or "").upper()
            side = str(order.get("side") or "").lower()
            client_id = str(order.get("client_order_id") or "")
            qty = str(order.get("filled_qty") or order.get("qty") or "")
            price = decimal_value(order.get("filled_avg_price"))
            if side == "buy":
                title = f"Bought {symbol}"
            elif client_id.startswith("apt-protect-sl-") or "stop" in str(order.get("type") or "").lower():
                title = f"Stopped out of {symbol}"
            elif client_id.startswith(("apt-protect-tp-", "apt-exit-limit-")):
                title = f"Took profit on {symbol}"
            else:
                title = f"Sold {symbol}"
            self.alert("trade", title, f"{qty} @ {money(price)}", key=f"fill:{order_id}", ttl_seconds=86400)
        self.alerted_fill_ids = ids  # bounded to what Alpaca still returns; old ids never reappear

    def record_order_intent(
        self,
        symbol: str,
        side: OrderSide,
        qty: Decimal,
        role: str,
        status: str,
        reason: str,
        client_order_id: str = "",
        order_id: str = "",
    ) -> None:
        qty_text = format(qty, "f") if isinstance(qty, Decimal) else str(qty)
        if "." in qty_text:
            qty_text = qty_text.rstrip("0").rstrip(".")
        event = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "account_id": self.account_id,
            "account": self.name,
            "symbol": symbol,
            "side": getattr(side, "value", str(side)),
            "qty": qty_text,
            "role": role,
            "status": status,
            "client_order_id": client_order_id,
            "order_id": order_id,
            "reason": reason,
        }
        append_day_tape_event("order_intent", compact_order_intent(event))
        if status == "error":
            side_text = getattr(side, "value", str(side))
            self.alert("problem", f"Order rejected: {side_text} {symbol}", str(reason)[-200:],
                       key=f"reject:{symbol}:{side_text}", ttl_seconds=600)
        with self.lock:
            self.order_intents.append(event)
            self.order_intents = self.order_intents[-REPLAY_EVENT_LIMIT:]
        if callable(self.replay_recorder):
            self.replay_recorder("order_intent", event)
        else:
            append_replay_event("order_intent", event)

    def fresh_sellable_qty(self, symbol: str) -> Decimal | None:
        """Shares of symbol free to sell per a position read made right now; None if it cannot be read."""
        getter = getattr(self.trading_client, "get_open_position", None)
        if getter is None:
            return None
        try:
            fresh = model_dict(getter(symbol))
        except APIError as exc:
            return Decimal("0") if exc.status_code == 404 else None
        except Exception:
            return None
        if not fresh or decimal_value(fresh.get("qty")) <= 0 or str(fresh.get("side", "")).lower() == "short":
            return Decimal("0") if fresh else None
        return self.sellable_qty(fresh)

    def sellable_qty(self, position: dict[str, Any]) -> Decimal:
        """Shares a market sell may ask for right now: Alpaca's qty_available when it reports one.

        While a protective stop is filling in pieces, part of the position is still held by that
        order; a sell for the full position is rejected ("insufficient qty available"), as happened
        with U on 2026-11-06. Replay positions carry no qty_available, so the full quantity is used.
        """
        qty = abs(decimal_value(position.get("qty")))
        available = position.get("qty_available")
        if available is None or available == "":
            return qty
        return max(Decimal("0"), min(qty, abs(decimal_value(available))))

    def format_position(self, item: dict[str, Any]) -> dict[str, Any]:
        qty = decimal_value(item.get("qty"))
        avg_entry = decimal_value(item.get("avg_entry_price"))
        cost_basis = decimal_value(item.get("cost_basis"))
        current_price = decimal_value(item.get("current_price"))
        market_value = decimal_value(item.get("market_value"))
        unrealized_pl = decimal_value(item.get("unrealized_pl"))
        unrealized_plpc = decimal_value(item.get("unrealized_plpc"))
        intraday_pl = decimal_value(item.get("unrealized_intraday_pl"))
        intraday_plpc = decimal_value(item.get("unrealized_intraday_plpc"))
        return {
            "symbol": item.get("symbol", ""),
            "side": item.get("side", ""),
            "qty": item.get("qty", ""),
            "qty_raw": float(qty),
            "avg_entry": money(avg_entry),
            "avg_entry_raw": float(avg_entry),
            "cost_basis": money(cost_basis),
            "cost_basis_raw": float(cost_basis),
            "current_price": money(current_price),
            "current_price_raw": float(current_price),
            "market_value": money(market_value),
            "market_value_raw": float(market_value),
            "unrealized_pl": money(unrealized_pl),
            "unrealized_pl_raw": float(unrealized_pl),
            "unrealized_pl_pct": percent_from_ratio(unrealized_plpc),
            "unrealized_pl_pct_raw": float(unrealized_plpc * Decimal("100")),
            "intraday_pl": money(intraday_pl),
            "intraday_pl_raw": float(intraday_pl),
            "intraday_pl_pct": percent_from_ratio(intraday_plpc),
            "intraday_pl_pct_raw": float(intraday_plpc * Decimal("100")),
        }

    def flatten_orders(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flattened: list[dict[str, Any]] = []
        for order in orders:
            flattened.append(order)
            legs = order.get("legs") or []
            if isinstance(legs, list):
                for leg in legs:
                    if isinstance(leg, dict):
                        flattened.append(leg)
        return flattened

    def order_role(self, item: dict[str, Any], position_symbols: set[str] | None = None) -> str:
        position_symbols = position_symbols or set()
        symbol = str(item.get("symbol", "")).upper()
        side = str(item.get("side", "")).lower()
        order_type = str(item.get("type") or item.get("order_type") or "").lower()
        order_class = str(item.get("order_class") or "").lower()
        client_id = str(item.get("client_order_id") or "")
        has_parent = bool(item.get("parent_order_id") or item.get("legs"))

        if client_id.startswith("apt-entry-") or (side == "buy" and order_class != "oco"):
            return "Pending Entry"
        if client_id.startswith("apt-exit-") or client_id.startswith("apt-purge-"):
            return "Strategy Exit"
        if client_id.startswith("apt-protect-"):
            return "Protective Exit"
        if side == "sell" and (
            order_class in {"bracket", "oco", "oto"}
            or has_parent
            or (symbol in position_symbols and order_type in {"limit", "stop", "stop_limit", "trailing_stop"})
        ):
            return "Protective Exit"
        return "Manual/Unknown"

    def is_app_entry_order(self, item: dict[str, Any]) -> bool:
        return str(item.get("client_order_id") or "").startswith("apt-entry-")

    def is_app_protective_order(self, item: dict[str, Any]) -> bool:
        return str(item.get("client_order_id") or "").startswith("apt-protect-")

    def protective_exit_kind(self, item: dict[str, Any]) -> str:
        client_id = str(item.get("client_order_id") or "")
        order_type = str(item.get("type") or item.get("order_type") or "").lower()
        if client_id.startswith("apt-protect-tp-") or order_type == "limit":
            return "take_profit"
        if client_id.startswith("apt-protect-sl-") or order_type in {"stop", "stop_limit", "trailing_stop"}:
            return "stop_loss"
        return ""

    def cancel_orders_for_symbol(self, orders: list[dict[str, Any]], symbol: str) -> int | None:
        """Cancel the app's protective orders for symbol; returns how many are now cancelling.

        None means a cancel was refused: the order may still hold the shares (or have filled),
        so callers must not sell this pass.
        """
        clean_symbol = symbol.strip().upper()
        cancelled = 0
        refused = False
        for order in orders:
            if str(order.get("symbol") or "").upper() != clean_symbol:
                continue
            if not self.is_app_protective_order(order):
                continue
            if self.cancel_open_order(order):
                cancelled += 1
            else:
                refused = True
        return None if refused else cancelled

    def wait_for_symbol_app_orders_cleared(
        self, symbol: str, timeout_seconds: float = 3.0, include_exits: bool = False
    ) -> bool:
        clean_symbol = symbol.strip().upper()
        if not clean_symbol or self.config.dry_run:
            return True
        client = self.require_trading_client()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                open_orders = client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=50, nested=True, direction=Sort.DESC)
                )
            except Exception as exc:
                self.record_runtime_exception(
                    "order_execution",
                    "Open-order status check failed",
                    OrderExecutionError(str(exc) or exc.__class__.__name__),
                )
                return False
            flat_orders = self.flatten_orders([model_dict(item) for item in open_orders])
            still_held = [
                order for order in flat_orders
                if str(order.get("symbol") or "").upper() == clean_symbol
                and (
                    self.is_app_protective_order(order)
                    or (include_exits and str(order.get("client_order_id") or "").startswith("apt-exit-"))
                )
            ]
            if not still_held:
                return True
            time.sleep(0.25)
        return False

    def cancel_orphan_protective_orders(self, orders: list[dict[str, Any]], position_symbols: set[str]) -> None:
        for order in orders:
            symbol = str(order.get("symbol") or "").upper()
            if not symbol or symbol in position_symbols:
                continue
            if not self.is_app_protective_order(order):
                continue
            if self.cancel_open_order(order):
                self.log("warn", f"Cancelled orphan protective exit for {symbol}; no open position.")

    def cancel_open_order(self, item: dict[str, Any]) -> bool:
        order_id = str(item.get("id") or "")
        if not order_id:
            return False
        if str(item.get("status") or "").lower() == "pending_cancel":
            return True
        try:
            self.cancel_order_request(order_id)
            return True
        except OrderExecutionError as exc:
            self.log("warn", f"Could not cancel protective order {order_id}: {exc}")
            return False

    def format_order(self, item: dict[str, Any], position_symbols: set[str] | None = None) -> dict[str, Any]:
        return {
            "symbol": item.get("symbol", ""),
            "side": item.get("side", ""),
            "type": item.get("type") or item.get("order_type", ""),
            "qty": item.get("qty", ""),
            "status": item.get("status", ""),
            "role": self.order_role(item, position_symbols),
            "time_in_force": item.get("time_in_force", ""),
            "order_class": item.get("order_class", ""),
            "submitted": item.get("submitted_at", ""),
            "client_order_id": item.get("client_order_id", ""),
        }

    def trade_history_rows(
        self, orders: list[dict[str, Any]], limit: int | None = TRADE_HISTORY_DISPLAY_ROWS
    ) -> list[dict[str, Any]]:
        filled_orders: list[dict[str, Any]] = []
        for item in self.flatten_orders(orders):
            filled_qty = decimal_value(item.get("filled_qty"))
            status = str(item.get("status") or "").lower()
            if filled_qty <= 0 and status not in {"filled", "partially_filled"}:
                continue
            filled_orders.append(item)

        intent_lookup = self.trade_intent_lookup()
        lots: dict[str, list[dict[str, Decimal]]] = {}
        rows: list[dict[str, Any]] = []
        for item in sorted(filled_orders, key=self.trade_history_sort_value):
            symbol = str(item.get("symbol") or "").upper()
            side = str(item.get("side") or "").lower()
            filled_qty = decimal_value(item.get("filled_qty"))
            avg_price = decimal_value(item.get("filled_avg_price"))
            filled_value = (
                filled_qty * avg_price
                if filled_qty > 0 and avg_price > 0
                else decimal_value(item.get("notional"))
            )
            intent = self.trade_intent_for_order(item, intent_lookup)
            cost_basis: Decimal | None = None
            realized_pl: Decimal | None = None
            realized_pl_pct: Decimal | None = None

            if symbol and side == "buy" and filled_qty > 0 and avg_price > 0:
                lots.setdefault(symbol, []).append({"qty": filled_qty, "price": avg_price})
                cost_basis = filled_value
            elif symbol and side == "sell" and filled_qty > 0:
                cost_basis = self.consume_trade_lots(lots.setdefault(symbol, []), filled_qty)
                if cost_basis > 0 and filled_value > 0:
                    realized_pl = filled_value - cost_basis
                    realized_pl_pct = realized_pl / cost_basis * Decimal("100")

            rows.append(
                self.format_trade_history_order(
                    item,
                    intent,
                    cost_basis,
                    realized_pl,
                    realized_pl_pct,
                )
            )
        rows.sort(key=lambda row: row.get("sort_time", ""), reverse=True)
        return rows if limit is None else rows[:limit]

    def daily_realized_pl_summary(
        self,
        rows: list[dict[str, Any]],
        account_basis: Decimal,
        session_date: str | None = None,
    ) -> dict[str, Any]:
        try:
            today = datetime.fromisoformat(str(session_date)).date() if session_date else datetime.now().astimezone().date()
        except ValueError:
            today = datetime.now().astimezone().date()
        realized_pl = Decimal("0")
        trade_cost_basis = Decimal("0")
        for row in rows:
            if str(row.get("side") or "").lower() != "sell":
                continue
            filled_at = str(row.get("sort_time") or "")
            if filled_at:
                try:
                    filled_day = datetime.fromisoformat(filled_at.replace("Z", "+00:00")).astimezone().date()
                except ValueError:
                    filled_day = today
                if filled_day != today:
                    continue
            row_cost_basis = decimal_value(row.get("cost_basis_raw"))
            if row_cost_basis <= 0:
                continue
            trade_cost_basis += row_cost_basis
            realized_pl += decimal_value(row.get("realized_pl_raw"))
        percent = (realized_pl / account_basis * Decimal("100")) if account_basis > 0 else Decimal("0")
        return {
            "value": realized_pl.quantize(Decimal("0.000001")),
            "account_basis": account_basis.quantize(Decimal("0.000001")),
            "trade_cost_basis": trade_cost_basis.quantize(Decimal("0.000001")),
            "percent": percent.quantize(Decimal("0.000001")),
            "session_date": today.isoformat(),
        }

    def sync_entries_today_from_orders(self, orders: list[dict[str, Any]]) -> None:
        # Counted from broker orders (not local memory) so the daily cap survives restarts. The
        # orders are the newest 100 plus every fill seen earlier today (with_todays_fills).
        today = datetime.now(MARKET_TIMEZONE).date()
        counts: dict[str, int] = {}
        seen: set[str] = set()
        for item in self.flatten_orders(orders):
            if str(item.get("side") or "").lower() != "buy" or decimal_value(item.get("filled_qty")) <= 0:
                continue
            order_id = str(item.get("id") or "")
            if order_id and order_id in seen:
                continue
            seen.add(order_id)
            filled_at = self.parse_order_datetime(item.get("filled_at") or item.get("submitted_at"))
            if filled_at is None or filled_at.astimezone(MARKET_TIMEZONE).date() != today:
                continue
            symbol = str(item.get("symbol") or "").strip().upper()
            if symbol:
                counts[symbol] = counts.get(symbol, 0) + 1
        with self.lock:
            # If the whole-day read has not succeeded yet the list can be short; a count already
            # reached must not drop and reopen a per-day cap.
            if self.entries_today_date == today:
                for symbol, earlier in self.entries_today_by_symbol.items():
                    counts[symbol] = max(counts.get(symbol, 0), earlier)
            self.entries_today_date = today
            self.entries_today_by_symbol = counts

    def sync_loss_reentry_floors_from_closed_orders(self, orders: list[dict[str, Any]]) -> None:
        filled_orders: list[dict[str, Any]] = []
        for item in self.flatten_orders(orders):
            filled_qty = decimal_value(item.get("filled_qty"))
            status = str(item.get("status") or "").lower()
            if filled_qty <= 0 and status not in {"filled", "partially_filled"}:
                continue
            filled_orders.append(item)

        intent_lookup = self.trade_intent_lookup()
        lots: dict[str, list[dict[str, Decimal]]] = {}
        with self.lock:
            reset_at = self.reentry_reset_at
        movers = uses_climbing_reentry(self.config)  # count losing round trips, not a score floor
        today = datetime.now(MARKET_TIMEZONE).date()
        opening_buy: dict[str, str] = {}
        losing_trips: dict[str, set[str]] = {}
        last_sale: dict[str, tuple[str, Decimal, bool, datetime]] = {}  # symbol -> (sell id, price, won, when)
        # The score floor belongs to accounts on the floor rule. Hold and day-trade accounts never
        # read it, and their order lists reach back days.
        uses_score_floor = uses_reentry_floor(self.config)
        rebuilt = False
        if movers:
            with self.lock:
                rebuilt = self.reentry_losses_date != today
                if rebuilt:
                    self.reentry_losses_today = {}
                    self.reentry_open_buys = {}
                    self.reentry_new_highs = {}
                    self.reentry_released_sells = set()
                    self.reentry_losses_date = today

        for item in sorted(filled_orders, key=self.trade_history_sort_value):
            symbol = str(item.get("symbol") or "").upper()
            side = str(item.get("side") or "").lower()
            filled_qty = decimal_value(item.get("filled_qty"))
            avg_price = decimal_value(item.get("filled_avg_price"))
            filled_value = (
                filled_qty * avg_price
                if filled_qty > 0 and avg_price > 0
                else decimal_value(item.get("notional"))
            )
            if not symbol or filled_qty <= 0:
                continue

            filled_at = self.parse_order_datetime(
                item.get("filled_at") or item.get("updated_at") or item.get("submitted_at")
            )
            if reset_at and filled_at and filled_at <= reset_at:
                continue

            if side == "buy" and avg_price > 0:
                lots.setdefault(symbol, []).append({"qty": filled_qty, "price": avg_price})
                opening_buy[symbol] = self.closed_order_identity(item)
                last_sale.pop(symbol, None)
                with self.lock:
                    self.reentry_score_floors.pop(symbol, None)
                    if movers:
                        self.reentry_open_buys[symbol] = (opening_buy[symbol], avg_price)
                continue

            if side != "sell":
                continue

            cost_basis = self.consume_trade_lots(lots.setdefault(symbol, []), filled_qty)
            realized_pl: Decimal | None = None
            if cost_basis > 0 and filled_value > 0:
                realized_pl = filled_value - cost_basis

            if movers:
                # The climbing rule counts losing round trips instead (movers_reentry_bar). A trip is keyed
                # by its buy, so a stop that fills in two pieces is one loss. The list is only the
                # newest orders: on a busy day a position's buy has scrolled out by the time it is
                # sold, so the buy is remembered from the pass that saw it. A sell with no known buy
                # has no known result and is not counted.
                trip = opening_buy.get(symbol)
                lost = realized_pl is not None and realized_pl < 0
                won = realized_pl is not None and realized_pl > 0
                if trip is None:
                    with self.lock:
                        remembered = self.reentry_open_buys.get(symbol)
                    if remembered is not None:
                        trip, bought_at = remembered
                        lost = Decimal("0") < avg_price < bought_at
                        won = avg_price > bought_at
                sold_today = filled_at is not None and filled_at.astimezone(MARKET_TIMEZONE).date() == today
                if trip and lost and sold_today:
                    losing_trips.setdefault(symbol, set()).add(trip)
                if sold_today and avg_price > 0 and filled_at is not None:
                    last_sale[symbol] = (self.closed_order_identity(item), avg_price, bool(trip and won), filled_at)
                continue

            if not uses_score_floor:
                continue
            intent = self.trade_intent_for_order(item, intent_lookup)
            reason = str(intent.get("reason") or "")
            if not self.closed_sell_needs_reentry_floor(item, reason, realized_pl):
                continue

            key = self.closed_order_identity(item)
            with self.lock:
                if key in self.processed_reentry_exit_ids:
                    continue
                self.processed_reentry_exit_ids.add(key)
            self.record_reentry_floor(
                symbol,
                self.snapshot(symbol),
                "local stop-loss filled protective/loss exit",
            )
            self.log("warn", f"{symbol} exit filled; requiring stronger score before re-entry.")

        if movers:
            self.record_movers_losing_trips(losing_trips, rebuilt)
            self.record_movers_winning_sales(last_sale)

    def traded_above_since(self, symbol: str, target: Decimal, since: datetime) -> bool:
        """True when a price bar that began after `since`, or the latest trade, is above target."""
        for point in reversed(_latest_session_points(self.strategy_state.histories.get(symbol, []))):
            began = _bar_local_time(point.timestamp)
            if began is None or began <= since:
                break
            if point.high > target:
                return True
        trade = self.latest_stream_trade(symbol)
        return bool(trade and trade[1] > since and trade[0] > target)

    def record_movers_winning_sales(self, last_sale: dict[str, tuple[str, Decimal, bool, datetime]]) -> None:
        """Each symbol's newest sale today, when it was at a gain and nothing was bought since, sets
        the price the stock has to beat (movers_unbeaten_high). That price is where the trailing
        stop was hanging from: the sale price plus the trail drop. It is checked here on every
        refresh against the bars since the sale, whatever the stock scores at the time, so a new
        high made between scans, while the score was low, or before a restart still releases it."""
        drop = min(max(self.config.profit_trail_drop_percent, Decimal("0")), Decimal("50"))
        announce: list[str] = []
        with self.lock:
            pending: dict[str, tuple[str, Decimal]] = {}
            for symbol, (sell_id, price, won, sold_at) in last_sale.items():
                if not won or sell_id in self.reentry_released_sells:
                    continue
                if self.inverse_trend_active(symbol, self.config):
                    continue  # trend-hold funds are bought by their own rules, not by the score
                target = self.round_exit_price(price / (Decimal("1") - drop / Decimal("100")), ROUND_UP)
                if self.traded_above_since(symbol, target, sold_at):
                    self.reentry_released_sells.add(sell_id)
                    continue
                known = self.reentry_new_highs.get(symbol)
                if known is None or known[0] != sell_id:
                    announce.append(f"{symbol} above ${target}")
                pending[symbol] = (sell_id, target) if known is None or known[0] != sell_id else known
            self.reentry_new_highs = pending
        boost = self.config.reentry_score_boost
        if announce and boost > 0:
            self.log(
                "info",
                f"Sold at a gain; re-buying needs {boost:.0f} more points until the stock trades at a new"
                f" high: {', '.join(sorted(announce))}.",
            )

    def record_movers_losing_trips(self, losing_trips: dict[str, set[str]], rebuilt: bool) -> None:
        """Add today's losing round trips to the day's count. The count only grows during a day:
        the order list is a window, and a morning loss that scrolled out of it still counts."""
        raised: list[tuple[str, int]] = []
        with self.lock:
            for symbol, trips in losing_trips.items():
                known = self.reentry_losses_today.setdefault(symbol, set())
                if not trips <= known:
                    known |= trips
                    raised.append((symbol, len(known)))
        raised = [item for item in raised if not self.inverse_trend_active(item[0], self.config)]
        if not raised:
            return
        bars = ", ".join(
            f"{symbol} needs {self.movers_reentry_bar(symbol, self.config)[0]:.0f} ({losses} losing"
            f" exit{'' if losses == 1 else 's'} today)"
            for symbol, losses in sorted(raised)
        )
        self.log("warn", f"Re-entry score {'rebuilt from' if rebuilt else 'raised by'} today's fills: {bars}.")

    def with_todays_fills(
        self,
        client: Any,
        closed_orders: list[dict[str, Any]],
        session_date: str = "",
        open_orders: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """closed_orders (the newest 100) plus the session's filled orders that are not in it.

        Every fill seen during the session is kept, and the whole session is read at its start and
        after a restart, so the buy counts, the losing-exit counts and the trade table cover all of
        it. Alpaca lists closed orders by when they were submitted, so a stop placed hours ago can
        fill without ever showing among the newest 100: whenever an order that was open at the last
        refresh is gone and is not in that list, the session is read again. The session is the
        market clock's (the last one while the market is closed), so Friday's table still adds up
        on Saturday. A failed read is tried again a minute later; until it succeeds the result is
        only what has been seen so far."""
        try:
            today = date.fromisoformat(session_date)
        except ValueError:
            today = datetime.now(MARKET_TIMEZONE).date()
        open_ids = {str(item.get("id") or "") for item in self.flatten_orders(open_orders or [])} - {""}
        listed = {str(item.get("id") or "") for item in self.flatten_orders(closed_orders)}
        with self.lock:
            if self.day_fills_date != today:
                self.day_fills = {}
                self.day_fills_date = today
                self.day_fills_loaded = False
                self.day_fills_retry_at = 0.0
                self.day_fills_warned = False
            if self.open_order_ids - open_ids - listed - set(self.day_fills):
                self.day_fills_loaded = False  # an order closed out of sight of the regular read
            self.open_order_ids = open_ids
            need_read = not self.day_fills_loaded and time.monotonic() >= self.day_fills_retry_at
        earlier: list[dict[str, Any]] | None = None
        if need_read:
            try:
                earlier = self.read_todays_closed_orders(client, today)
            except Exception as exc:
                with self.lock:
                    warned, self.day_fills_warned = self.day_fills_warned, True
                if not warned:
                    self.log(
                        "warn",
                        "Could not read the session's earlier orders; the day's counts and trade table cover"
                        f" only what the app has seen until this succeeds (retried each minute): {exc}",
                    )
        with self.lock:
            if need_read:
                self.day_fills_loaded = earlier is not None
                self.day_fills_retry_at = 0.0 if earlier is not None else time.monotonic() + DAY_FILLS_RETRY_SECONDS
            for order in (earlier or []) + closed_orders:  # the regular read last: its copy is the newest
                order_id = str(order.get("id") or "")
                if order_id and self.order_filled_on(order, today):
                    self.day_fills[order_id] = order
            top_level = {str(order.get("id") or "") for order in closed_orders}
            scrolled_out = [order for order_id, order in self.day_fills.items() if order_id not in top_level]
        return closed_orders + scrolled_out

    def order_filled_on(self, order: dict[str, Any], day: date) -> bool:
        for item in self.flatten_orders([order]):
            if decimal_value(item.get("filled_qty")) <= 0:
                continue
            filled_at = self.parse_order_datetime(
                item.get("filled_at") or item.get("updated_at") or item.get("submitted_at")
            )
            if filled_at is not None and filled_at.astimezone(MARKET_TIMEZONE).date() == day:
                return True
        return False

    def read_todays_closed_orders(self, client: Any, today: date) -> list[dict[str, Any]]:
        """Every closed order submitted since midnight ET, newest first, read a page at a time."""
        session_start = datetime.combine(today, datetime.min.time(), tzinfo=MARKET_TIMEZONE)
        orders: list[dict[str, Any]] = []
        seen: set[str] = set()
        until: datetime | None = None
        for _ in range(DAY_FILLS_MAX_PAGES):
            page = [
                model_dict(item)
                for item in client.get_orders(
                    GetOrdersRequest(
                        status=QueryOrderStatus.CLOSED,
                        limit=DAY_FILLS_PAGE_SIZE,
                        after=session_start,
                        until=until,
                        nested=True,
                        direction=Sort.DESC,
                    )
                )
            ]
            fresh = [order for order in page if str(order.get("id") or "") not in seen]
            orders.extend(fresh)
            seen.update(str(order.get("id") or "") for order in fresh)
            submitted = [self.parse_order_datetime(order.get("submitted_at")) for order in page]
            oldest = min((value for value in submitted if value is not None), default=None)
            if len(page) < DAY_FILLS_PAGE_SIZE or not fresh or oldest is None:
                return orders
            # Just past the oldest one, so orders sharing its timestamp are asked for again
            # (repeats are dropped above) instead of being skipped.
            until = oldest + timedelta(microseconds=1)
        self.log(
            "warn",
            f"The session has more than {DAY_FILLS_PAGE_SIZE * DAY_FILLS_MAX_PAGES} closed orders;"
            " the day's counts and trade table leave out the earliest ones.",
        )
        return orders

    def closed_sell_needs_reentry_floor(
        self,
        item: dict[str, Any],
        reason: str,
        realized_pl: Decimal | None,
    ) -> bool:
        if str(item.get("side") or "").lower() != "sell":
            return False
        # Only a losing exit raises the bar. A stop (or trailing stop) that fills in profit is a
        # winner; a stop fill with unknown cost basis is assumed to be a loss.
        if realized_pl is not None:
            return realized_pl < 0
        return self.is_stop_loss_exit_reason(reason) or self.protective_exit_kind(item) == "stop_loss"

    def closed_order_identity(self, item: dict[str, Any]) -> str:
        for key in ("id", "client_order_id"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        parts = [
            str(item.get("symbol") or ""),
            str(item.get("side") or ""),
            str(item.get("filled_at") or item.get("updated_at") or item.get("submitted_at") or ""),
            str(item.get("filled_qty") or ""),
            str(item.get("filled_avg_price") or ""),
        ]
        return ":".join(parts)

    def trade_history_sort_value(self, item: dict[str, Any]) -> str:
        filled_at = item.get("filled_at") or item.get("updated_at") or item.get("submitted_at") or ""
        return str(filled_at or "")

    def trade_intent_lookup(self) -> dict[str, dict[str, Any]]:
        events: list[dict[str, Any]] = []
        with self.lock:
            events.extend(dict(item) for item in self.order_intents)
        path = replay_file_path()
        if path.exists():
            try:
                with REPLAY_LOCK:
                    lines = path.read_text(encoding="utf-8").splitlines()[-3000:]
                for line in lines:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if event.get("kind") == "order_intent" and isinstance(event.get("payload"), dict):
                        events.append(dict(event.get("payload") or {}))
            except (OSError, UnicodeDecodeError, TypeError, ValueError) as exc:
                self.record_runtime_exception(
                    "replay",
                    "Order-intent replay lookup failed",
                    ReplayPersistenceError(str(exc) or exc.__class__.__name__),
                )

        lookup: dict[str, dict[str, Any]] = {}
        for event in events:
            if str(event.get("account_id") or "") != self.account_id:
                continue
            for key_name in ("order_id", "client_order_id"):
                key = str(event.get(key_name) or "").strip()
                if key:
                    lookup[key] = event
        return lookup

    def trade_intent_for_order(
        self,
        item: dict[str, Any],
        lookup: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        for key in (str(item.get("id") or "").strip(), str(item.get("client_order_id") or "").strip()):
            if key and key in lookup:
                return lookup[key]
        return {}

    def consume_trade_lots(self, lots: list[dict[str, Decimal]], qty: Decimal) -> Decimal:
        remaining = qty
        cost_basis = Decimal("0")
        while remaining > 0 and lots:
            lot = lots[0]
            lot_qty = lot.get("qty", Decimal("0"))
            lot_price = lot.get("price", Decimal("0"))
            take = min(remaining, lot_qty)
            if take <= 0:
                lots.pop(0)
                continue
            cost_basis += take * lot_price
            remaining -= take
            lot["qty"] = lot_qty - take
            if lot["qty"] <= Decimal("0.0000001"):
                lots.pop(0)
        return cost_basis

    def format_trade_history_order(
        self,
        item: dict[str, Any],
        intent: dict[str, Any] | None = None,
        cost_basis: Decimal | None = None,
        realized_pl: Decimal | None = None,
        realized_pl_pct: Decimal | None = None,
    ) -> dict[str, Any]:
        filled_qty = decimal_value(item.get("filled_qty"))
        avg_price = decimal_value(item.get("filled_avg_price"))
        filled_value = filled_qty * avg_price if filled_qty > 0 and avg_price > 0 else decimal_value(item.get("notional"))
        client_id = str(item.get("client_order_id") or "")
        side = str(item.get("side") or "").lower()
        reason = str((intent or {}).get("reason") or "")
        role = "Manual/Unknown"
        if client_id.startswith("apt-entry-"):
            role = "Strategy Entry"
        elif client_id.startswith("apt-exit-"):
            role = "Strategy Exit"
        elif client_id.startswith("apt-protect-"):
            role = "Exit/Protective"
        elif side == "sell":
            role = "Exit/Protective"

        filled_at = item.get("filled_at") or item.get("updated_at") or item.get("submitted_at") or ""
        cost_basis_value = cost_basis if cost_basis is not None and cost_basis > 0 else None
        result = self.trade_result_label(side, realized_pl)
        exit_reason = self.exit_reason_label(side, role, reason, item)
        return {
            "filled": self.format_order_history_time(filled_at),
            "sort_time": str(filled_at or ""),
            "symbol": str(item.get("symbol") or "").upper(),
            "side": side,
            "filled_qty": number(filled_qty, 4) if filled_qty > 0 else "-",
            "avg_fill": money(avg_price) if avg_price > 0 else "-",
            "value": money(filled_value) if filled_value > 0 else "-",
            "value_raw": float(filled_value),
            "cost_basis": money(cost_basis_value) if cost_basis_value is not None else "-",
            "cost_basis_raw": float(cost_basis_value or Decimal("0")),
            "realized_pl": money(realized_pl) if realized_pl is not None else "-",
            "realized_pl_raw": float(realized_pl or Decimal("0")),
            "realized_pl_pct": f"{realized_pl_pct:+.2f}%" if realized_pl_pct is not None else "-",
            "realized_pl_pct_raw": float(realized_pl_pct or Decimal("0")),
            "result": result,
            "exit_reason": exit_reason,
            "exit_reason_detail": self.exit_reason_detail(reason, item),
            "status": item.get("status", ""),
            "source": role,
        }

    def trade_result_label(self, side: str, realized_pl: Decimal | None) -> str:
        if side != "sell":
            return "Entry"
        if realized_pl is None:
            return "Unknown"
        if realized_pl > 0:
            return "Winner"
        if realized_pl < 0:
            return "Loser"
        return "Flat"

    def exit_reason_label(self, side: str, role: str, reason: str, item: dict[str, Any] | None = None) -> str:
        if side != "sell":
            return "Entry"
        clean = reason.lower()
        if "take-profit" in clean:
            return "Gain Realized"
        if "trailing-profit" in clean:
            return "Gain Realized (Trail)"
        if "stop-loss" in clean:
            return "Loss Protection"
        if "trend hold ended" in clean:
            return "Trend Hold Ended"
        order_type = str((item or {}).get("type") or (item or {}).get("order_type") or "").lower()
        order_class = str((item or {}).get("order_class") or "").lower()
        if role == "Exit/Protective" or order_class in {"bracket", "oco", "oto"}:
            if order_type == "limit":
                return "Gain Realized (Broker Limit)"
            if order_type in {"stop", "stop_limit"}:
                return "Loss Protection (Broker Stop)"
            if order_type == "trailing_stop":
                return "Broker Trailing Stop"
        if role == "Strategy Exit":
            return "Strategy Exit"
        if role == "Exit/Protective":
            return "Broker/Protective Exit"
        return "Exit"

    def exit_reason_detail(self, reason: str, item: dict[str, Any] | None = None) -> str:
        parts = [part.strip() for part in str(reason or "").split(";") if part.strip()]
        for part in parts:
            if part.lower().startswith("local "):
                return part
        order_type = str((item or {}).get("type") or (item or {}).get("order_type") or "").lower()
        if order_type == "limit":
            limit_price = decimal_value((item or {}).get("limit_price"))
            return f"broker take-profit limit {money(limit_price)}" if limit_price > 0 else "broker take-profit limit"
        if order_type in {"stop", "stop_limit"}:
            stop_price = decimal_value((item or {}).get("stop_price"))
            return f"broker stop-loss {money(stop_price)}" if stop_price > 0 else "broker stop-loss"
        return parts[-1] if parts else "-"

    def format_order_history_time(self, value: Any) -> str:
        if not value:
            return "-"
        if hasattr(value, "astimezone"):
            return value.astimezone().strftime("%b %d, %I:%M:%S %p")
        raw = str(value)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%b %d, %I:%M:%S %p")
        except ValueError:
            return raw

    def parse_order_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if hasattr(value, "astimezone"):
            return value.astimezone(timezone.utc)
        raw = str(value)
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None

    def protection_status_rows(
        self,
        positions: list[dict[str, Any]],
        orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for position in positions:
            symbol = str(position.get("symbol", "")).upper()
            if not symbol or decimal_value(position.get("qty")) == 0:
                continue
            symbol_orders = [order for order in orders if str(order.get("symbol", "")).upper() == symbol]
            roles = [self.order_role(order, {symbol}) for order in symbol_orders]
            protective_count = roles.count("Protective Exit")
            strategy_exit_count = roles.count("Strategy Exit")
            manual_count = roles.count("Manual/Unknown")
            pending_entry_count = roles.count("Pending Entry")

            if strategy_exit_count:
                status = "Exit pending"
            elif protective_count:
                status = "Protected"
            elif decimal_value(position.get("current_price")) <= 0:
                status = "No market price"
            elif self.config.use_bracket_orders and self.config.dry_run:
                status = "Unprotected (dry run)"
            elif self.config.use_bracket_orders:
                status = "Unprotected: stop pending"
            else:
                status = "Manual exits off"

            details: list[str] = []
            if protective_count:
                details.append(f"{protective_count} protective")
                protective_orders = [
                    order for order, role in zip(symbol_orders, roles) if role == "Protective Exit"
                ]
                protective_kinds = [self.protective_exit_kind(order) for order in protective_orders]
                if "stop_loss" in protective_kinds:
                    details.append("stop live")
                if "take_profit" in protective_kinds:
                    details.append("profit limit live")
                elif self.inverse_trend_active(symbol, self.config):
                    details.append(
                        f"trend hold: exits {self.config.inverse_trend_exit_percent}% under VWAP"
                    )
                elif self.config.take_profit_percent > 0:
                    take_profit_price, _ = self.exit_prices(decimal_value(position.get("avg_entry_price")), self.config)
                    if take_profit_price > 0:
                        details.append(f"profit limit armed at {money(take_profit_price)}")
            if strategy_exit_count:
                details.append(f"{strategy_exit_count} strategy exit")
            if pending_entry_count:
                details.append(f"{pending_entry_count} pending entry")
            if manual_count:
                details.append(f"{manual_count} manual/unknown")
            if status == "No market price":
                details.append("untradable (e.g. a CVR right); no stop possible")
            if not details:
                details.append("No open exit orders")

            rows.append(
                {
                    "symbol": symbol,
                    "qty": position.get("qty", ""),
                    "market_value": money(position.get("market_value")),
                    "unrealized_pl": money(position.get("unrealized_pl")),
                    "status": status,
                    "protective_orders": protective_count,
                    "strategy_exits": strategy_exit_count,
                    "manual_orders": manual_count,
                    "detail": "; ".join(details),
                }
            )
        return rows

    def standardized_account_metrics(self) -> dict[str, Any]:
        account = dict(self.account)
        session_date = str(
            account.get("daily_pl_session_date")
            or self.market_clock.get("session_date")
            or datetime.now().astimezone().date().isoformat()
        )
        daily_pl_source = str(account.get("daily_pl_source") or "").strip()
        has_pl_source = (
            daily_pl_source == "alpaca_portfolio_history"
            and str(account.get("daily_pl_raw") or "").strip() != ""
            and str(account.get("daily_pl_pct_raw") or "").strip() != ""
        )
        if not has_pl_source:
            account.update(self.unavailable_daily_pl_payload(session_date, str(account.get("daily_pl_source_error") or "")))
            account.update(
                {
                    "realized_pl": account.get("realized_pl_display") or "Unavailable",
                    "realized_pl_raw": str(account.get("realized_pl_raw") or ""),
                    "realized_pl_display": account.get("realized_pl_display") or "Unavailable",
                    "realized_pl_pct": account.get("realized_pl_pct_display") or "Unavailable",
                    "realized_pl_pct_raw": str(account.get("realized_pl_pct_raw") or ""),
                    "realized_pl_pct_display": account.get("realized_pl_pct_display") or "Unavailable",
                    "realized_pl_session_date": account.get("realized_pl_session_date") or session_date,
                }
            )
            return account
        daily_raw = metric_decimal(account.get("daily_pl_raw", account.get("daily_pl", "0")))
        daily_basis = metric_decimal(
            account.get(
                "daily_pl_account_basis_raw",
                account.get("last_equity") or account.get("equity") or "0",
            )
        )
        daily_pct = metric_decimal(account.get("daily_pl_pct_raw", account.get("daily_pl_pct", "0")))
        if daily_pct == 0 and daily_raw != 0 and daily_basis > 0:
            daily_pct = daily_raw / daily_basis * Decimal("100")
        account.update(
            {
                "daily_pl": account.get("daily_pl_display") or money(daily_raw),
                "daily_pl_raw": str(daily_raw.quantize(Decimal("0.000001"))),
                "daily_pl_display": account.get("daily_pl_display") or money(daily_raw),
                "daily_pl_pct_raw": str(daily_pct.quantize(Decimal("0.000001"))),
                "daily_pl_pct_display": account.get("daily_pl_pct_display") or signed_percent_value(daily_pct),
                "daily_pl_account_basis_raw": str(daily_basis.quantize(Decimal("0.000001"))),
                "daily_pl_account_basis_display": account.get("daily_pl_account_basis_display") or money(daily_basis),
                "daily_pl_session_date": session_date,
            }
        )
        if "realized_pl_raw" not in account:
            account["realized_pl_raw"] = str(metric_decimal(account.get("realized_pl", "0")).quantize(Decimal("0.000001")))
        if "realized_pl_pct_raw" not in account:
            account["realized_pl_pct_raw"] = str(metric_decimal(account.get("realized_pl_pct", "0")).quantize(Decimal("0.000001")))
        if "realized_pl_session_date" not in account:
            account["realized_pl_session_date"] = session_date
        return account

    def settings(self, include_keys: bool = False) -> dict[str, Any]:
        with self.lock:
            has_api_key = bool(self.api_key)
            has_secret_key = bool(self.secret_key)
            credentials_valid = not credential_validation_error(self.api_key, self.secret_key)
            return {
                "account_id": self.account_id,
                "name": self.name,
                "api_key": self.api_key if include_keys else "",
                "secret_key": self.secret_key if include_keys else "",
                "remember": self.remember,
                "auto_connect": self.auto_connect,
                "auto_start_trading": self.auto_start_trading,
                "has_api_key": has_api_key,
                "has_secret_key": has_secret_key,
                "credentials_loaded": credentials_valid,
                "credentials_saved": self.remember and credentials_valid,
                "settings_load_error": self.settings_load_error,
                "config": self.config.model_dump(mode="json"),
            }

    def trading_symbol_source(self) -> str:
        with self.lock:
            if self.config.inverse_etf_mode == "inverse_only":
                return "inverse_only"
            if self.config.use_top_volume_symbols and self.config.universe_mode == "daily_rvol":
                return "daily_rvol" if self.daily_universe_symbols else "daily_rvol_pending"
            if self.config.use_top_volume_symbols and self.top_volume_symbols:
                return "top_volume"
            return "manual"

    def summary(self) -> dict[str, Any]:
        with self.lock:
            trading_symbols = self.trading_symbols()
            symbol_source = self.trading_symbol_source()
            account = self.standardized_account_metrics()
            return {
                "account_id": self.account_id,
                "name": self.name,
                "connected": self.connected,
                "trading_enabled": self.trading_enabled,
                "profile": self.config.profile,
                "status": self.status,
                "credentials_loaded": not credential_validation_error(self.api_key, self.secret_key),
                "credentials_saved": self.remember and not credential_validation_error(self.api_key, self.secret_key),
                "auto_connect": self.auto_connect,
                "auto_start_trading": self.auto_start_trading,
                "settings_load_error": self.settings_load_error,
                "market_clock": self.market_clock,
                "equity": account.get("equity_display", "$0.00"),
                "daily_pl": account.get("daily_pl_display", "$0.00"),
                "daily_pl_raw": account.get("daily_pl_raw", "0"),
                "daily_pl_display": account.get("daily_pl_display", "$0.00"),
                "daily_pl_pct_raw": account.get("daily_pl_pct_raw", "0"),
                "daily_pl_pct_display": account.get("daily_pl_pct_display", "0.00%"),
                "daily_pl_account_basis_raw": account.get("daily_pl_account_basis_raw", "0"),
                "daily_pl_account_basis_display": account.get("daily_pl_account_basis_display", "$0.00"),
                "daily_pl_session_date": account.get("daily_pl_session_date", ""),
                "daily_pl_source": account.get("daily_pl_source", ""),
                "daily_pl_source_error": account.get("daily_pl_source_error", ""),
                "realized_pl": account.get("realized_pl_display", "$0.00"),
                "realized_pl_raw": account.get("realized_pl_raw", "0"),
                "realized_pl_display": account.get("realized_pl_display", "$0.00"),
                "realized_pl_pct": account.get("realized_pl_pct_display", "0.00%"),
                "realized_pl_pct_raw": account.get("realized_pl_pct_raw", "0"),
                "realized_pl_pct_display": account.get("realized_pl_pct_display", "0.00%"),
                "realized_pl_session_date": account.get("realized_pl_session_date", ""),
                "last_refresh": self.last_refresh,
                "trading_symbol_count": len(trading_symbols),
                "symbol_source": symbol_source,
            }

    def state(self) -> dict[str, Any]:
        with self.lock:
            trading_symbols = self.trading_symbols()
            symbol_source = self.trading_symbol_source()
            return {
                "account_id": self.account_id,
                "name": self.name,
                "connected": self.connected,
                "trading_enabled": self.trading_enabled,
                "status": self.status,
                "last_error": self.last_error,
                "last_refresh": self.last_refresh,
                "settings_load_error": self.settings_load_error,
                "credentials_loaded": not credential_validation_error(self.api_key, self.secret_key),
                "credentials_saved": self.remember and not credential_validation_error(self.api_key, self.secret_key),
                "auto_connect": self.auto_connect,
                "auto_start_trading": self.auto_start_trading,
                "account": self.standardized_account_metrics(),
                "positions": self.positions,
                "orders": self.orders,
                "protection": self.protection_rows,
                "allocation": dict(self.allocation_view),
                "inplay": dict(self.inplay_view),
                "movers": dict(self.mover_view),
                "trade_history": self.trade_history,
                "risk": {
                    "daily_loss_breached": bool(self.daily_loss_breach_session),
                    "daily_loss_detail": self.daily_loss_detail,
                    "exits_managed_when_stopped": bool(self.config.use_bracket_orders and not self.config.dry_run),
                },
                "order_intents": self.order_intents[-200:],
                "strategy": self.strategy_rows,
                "market_clock": self.market_clock,
                "logs": self.logs[-200:],
                "config": self.config.model_dump(mode="json"),
                "trading_symbols": trading_symbols,
                "symbol_source": symbol_source,
                "daily_universe": dict(self.daily_universe_meta, symbols=list(self.daily_universe_symbols)),
            }


class TraderManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.market_stream_control_lock = threading.RLock()
        self.accounts: dict[str, TraderEngine] = {}
        self.selected_account_id = ""
        self.market_stream: SharedMarketStreamHandle | None = None
        self.market_stream_health = self.default_market_stream_health()
        self.replay_events: list[dict[str, Any]] = []
        self.historical_bars_cache: dict[str, tuple[float, int, set[str], dict[str, list[Any]]]] = {}
        self.custom_profiles: dict[str, dict[str, Any]] = {}
        self.dashboard_trade_backfill_cursor: datetime | None = None
        self.settings_load_errors: list[dict[str, str]] = []
        self.daily_universe: rvol_universe.DailyUniverse | None = None
        self.daily_universe_lock = threading.Lock()
        self.daily_universe_retry_at = 0.0
        self.daily_universe_loaded_for = ""
        self.daily_universe_streamed = False  # the running stream was built around the daily list
        self.app_settings = app_settings.AppWideSettings()
        self.app_settings_load_failed = False  # keep the unreadable saved value instead of overwriting it
        # (session date, feed) -> symbol -> (average daily volume, sessions) or None (too little history)
        self.daily_volume_averages: dict[tuple[str, str], dict[str, tuple[float, int] | None]] = {}
        self.market_overview_lock = threading.Lock()
        self.market_overview_cache: tuple[float, dict[str, Any]] | None = None
        self.symbol_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.create_account("Account 1", AppConfig())

    def reset_settings_load_errors(self) -> None:
        with self.lock:
            self.settings_load_errors = []

    def record_settings_load_error(
        self,
        message: str,
        account_id: str = "",
        account_name: str = "",
        source: str = "settings",
    ) -> None:
        entry = {
            "source": source,
            "account_id": account_id,
            "account_name": account_name,
            "message": message,
        }
        with self.lock:
            self.settings_load_errors.append(entry)

    def settings_diagnostics(self) -> dict[str, Any]:
        with self.lock:
            return {
                "errors": [dict(item) for item in self.settings_load_errors],
                "error_count": len(self.settings_load_errors),
            }

    def create_account(self, name: str | None = None, config: AppConfig | None = None) -> TraderEngine:
        account_id = uuid.uuid4().hex
        engine = TraderEngine(account_id, name or f"Account {len(self.accounts) + 1}")
        engine.replay_recorder = self.record_replay_event
        if config is not None:
            engine.config = config
        with self.lock:
            self.accounts[account_id] = engine
            if not self.selected_account_id:
                self.selected_account_id = account_id
        return engine

    def default_market_stream_health(self) -> dict[str, Any]:
        return {
            "status": "Stopped",
            "connected": False,
            "feed": "",
            "stream_id": "",
            "source_account_id": "",
            "source_account_name": "",
            "dashboard_symbols": 0,
            "bar_symbols": 0,
            "last_message": "",
            "last_message_at": "",
            "last_message_age_seconds": None,
            "reconnect_count": 0,
            "last_error": "",
            "last_backfill": "",
        }

    def update_market_stream_health(self, increment_reconnect: bool = False, **updates: Any) -> None:
        with self.lock:
            health = dict(self.market_stream_health)
            if (
                updates.get("last_error") == ""
                and "status" not in updates
                and (
                    str(health.get("status") or "").lower() == "connection limit"
                    or is_connection_limit_error(str(health.get("last_error") or ""))
                )
            ):
                updates.pop("last_error", None)
            if increment_reconnect:
                health["reconnect_count"] = int(health.get("reconnect_count") or 0) + 1
            health.update(updates)
            if str(health.get("status") or "").lower() == "connection limit":
                health["_connection_limit_monotonic"] = time.monotonic()
            elif "status" in updates:
                health.pop("_connection_limit_monotonic", None)
            self.market_stream_health = health

    def record_market_stream_message(self, channel: str, payload: Any) -> None:
        raw = model_dict(payload)
        symbol = str(raw.get("symbol", "")).upper()
        label = f"{channel} {symbol}".strip()
        with self.lock:
            self.market_stream_health.update(
                {
                    "status": "Streaming",
                    "connected": True,
                    "last_message": label,
                    "last_message_at": datetime.now().strftime("%H:%M:%S"),
                    "_last_message_monotonic": time.monotonic(),
                    "last_error": "",
                }
            )

    def market_stream_state(self) -> dict[str, Any]:
        with self.lock:
            health = dict(self.market_stream_health)
        last_monotonic = health.pop("_last_message_monotonic", None)
        health.pop("_connection_limit_monotonic", None)
        if isinstance(last_monotonic, (int, float)):
            age = max(0, time.monotonic() - float(last_monotonic))
            health["last_message_age_seconds"] = round(age, 1)
            health["last_message_age"] = f"{int(age)}s ago"
        else:
            health["last_message_age"] = ""
        health["symbol_limit"] = self.stream_symbol_limit()
        return health

    def record_replay_event(self, kind: str, payload: dict[str, Any]) -> None:
        event = append_replay_event(kind, payload)
        if kind in {"market_backfill", "market_stream_error", "market_subscription"}:
            append_day_tape_event(kind, clean_day_tape_value(payload))
        with self.lock:
            self.replay_events.append(event)
            self.replay_events = self.replay_events[-REPLAY_EVENT_LIMIT:]

    def replay_state(self) -> dict[str, Any]:
        with self.lock:
            events = list(self.replay_events[-120:])
        return {
            "path": str(replay_file_path()),
            "day_tape_path": str(day_tape_file_path()),
            "events": [
                {
                    "time": event.get("time_display", ""),
                    "kind": event.get("kind", ""),
                    "summary": self.replay_summary(event),
                }
                for event in events
            ],
        }

    def replay_summary(self, event: dict[str, Any]) -> str:
        payload = event.get("payload") or {}
        kind = str(event.get("kind") or "")
        if kind == "market_bar":
            return f"{payload.get('symbol', '')} close {payload.get('close', '-')} vol {payload.get('volume', '-')}"
        if kind == "market_status":
            return f"{payload.get('symbol', '')} {payload.get('detail', '')}".strip()
        if kind == "market_subscription":
            return str(payload.get("detail", "market data subscribed"))
        if kind == "market_backfill":
            if "trades" in payload:
                return f"{payload.get('trades', 0)} trades across {payload.get('symbols', 0)} symbols"
            return f"{payload.get('bars', 0)} bars across {payload.get('symbols', 0)} symbols"
        if kind == "market_stream_error":
            return str(payload.get("error", "stream error"))
        if kind == "order_intent":
            return (
                f"{payload.get('account', '')} {payload.get('side', '')} {payload.get('qty', '')} "
                f"{payload.get('symbol', '')} ({payload.get('status', '')})"
            ).strip()
        return ", ".join(f"{key}={value}" for key, value in list(payload.items())[:4])

    def replace_from_settings(self, settings: list[AccountSettings], selected_account_id: str | None = None) -> None:
        with self.lock:
            self.stop_shared_market_stream_locked()
            for engine in self.accounts.values():
                engine.disconnect()
            self.accounts = {}
            for item in settings:
                engine = TraderEngine(item.account_id, item.name)
                engine.replay_recorder = self.record_replay_event
                engine.configure_saved(item)
                self.accounts[item.account_id] = engine
            if not self.accounts:
                engine = self.create_account("Account 1", AppConfig())
                self.selected_account_id = engine.account_id
            elif selected_account_id in self.accounts:
                self.selected_account_id = selected_account_id or ""
            else:
                self.selected_account_id = next(iter(self.accounts))

    def get(self, account_id: str | None = None) -> TraderEngine:
        with self.lock:
            target = account_id or self.selected_account_id
            if target not in self.accounts:
                raise KeyError("Account was not found.")
            return self.accounts[target]

    def upsert_payload(self, payload: AccountPayload) -> TraderEngine:
        with self.lock:
            account_id = payload.account_id or ""
            if account_id and account_id in self.accounts:
                engine = self.accounts[account_id]
            else:
                engine = self.create_account(payload.name, payload.config)
                account_id = engine.account_id
            self.selected_account_id = account_id
            return engine

    def set_selected(self, account_id: str) -> None:
        with self.lock:
            if account_id not in self.accounts:
                raise KeyError("Account was not found.")
            self.selected_account_id = account_id

    def remove(self, account_id: str) -> None:
        with self.lock:
            if account_id not in self.accounts:
                raise KeyError("Account was not found.")
            engine = self.accounts.pop(account_id)
            engine.disconnect()
            if self.selected_account_id == account_id:
                self.selected_account_id = next(iter(self.accounts), "")
            if not self.accounts:
                engine = self.create_account("Account 1", AppConfig())
                self.selected_account_id = engine.account_id
        self.ensure_market_data_stream()

    def refresh_all(self) -> None:
        for engine in self.list_engines():
            self.refresh_account(engine.account_id)

    def refresh_account(self, account_id: str | None = None, run_strategy: bool | None = None) -> None:
        engine = self.get(account_id)
        self.refresh_trading_universe_for(engine)
        shared_bars = self.shared_historical_bars_for(engine)
        engine.refresh(run_strategy=run_strategy, shared_bars=shared_bars)

    def refresh_trading_universe_for(self, target: TraderEngine) -> None:
        if not target.connected or not target.config.use_top_volume_symbols:
            return
        source = self.shared_market_source() or target
        if not source.connected:
            return
        source.refresh_top_volume(force=False, restart_stream=False)
        self.sync_top_volume_from(source)
        try:
            if self.daily_universe_engines():
                self.update_daily_universe(source)
            self.sync_daily_universe_stream()
        except Exception as exc:  # never let the daily list skip this account's refresh (exits run there)
            source.log("error", f"Daily stock list update failed: {exc}")

    def set_app_settings(self, settings: app_settings.AppWideSettings, load_failed: bool = False) -> bool:
        """Swap in new app-wide settings; returns True when the stream symbol limit changed."""
        with self.lock:
            changed = settings.market_stream_symbol_limit != self.app_settings.market_stream_symbol_limit
            self.app_settings = settings
            self.app_settings_load_failed = load_failed
        return changed

    def app_settings_payload(self) -> dict[str, Any]:
        with self.lock:
            return self.app_settings.model_dump(mode="json")

    def stream_symbol_limit(self) -> int:
        with self.lock:
            return int(self.app_settings.market_stream_symbol_limit)

    @staticmethod
    def daily_stream_pick_count(engines: list[TraderEngine]) -> int:
        # Every account's pick is a prefix of the same first ranking, so the largest one covers them all.
        return max((int(engine.config.daily_pick_count) for engine in engines), default=rvol_universe.PICK_COUNT)

    def daily_universe_stream_symbols(self) -> list[str]:
        """The daily list's streamed symbols when a connected streaming account uses it today, else []."""
        engines = [engine for engine in self.daily_universe_engines() if engine.config.use_market_stream]
        if not engines:
            return []
        with self.lock:
            universe = self.daily_universe
        if universe is None or universe.session_date != datetime.now(MARKET_TIMEZONE).date().isoformat():
            return []
        # Cut to the stream limit the same way market_data_symbols fills it, so a pick larger than the
        # limit still reads as carried and never resubscribes on every refresh.
        symbols = without_invalid_market_data_symbols(universe.stream_symbols(self.daily_stream_pick_count(engines)))
        return symbols[: self.stream_symbol_limit()]

    def sync_daily_universe_stream(self) -> None:
        """Resubscribe when the live stream does not match the daily list it should (or should no longer) carry.

        Compared against the running subscription, so it also covers a restart that reloaded today's
        list, an account switched to or from the daily list, and a pick or recheck. A healthy stream is
        otherwise never resubscribed just because the wanted symbols changed.
        """
        wanted = self.daily_universe_stream_symbols()
        with self.lock:
            stream = self.market_stream
            if stream is None or not stream.thread.is_alive() or stream.stop_event.is_set():
                self.daily_universe_streamed = False
                return  # nothing running: the normal stream start already uses the daily order
            current = set(stream.bar_symbols)
            carrying = self.daily_universe_streamed
        if wanted and not set(wanted) <= current:
            resubscribe = True
        elif not wanted and carrying:
            resubscribe = True
        else:
            resubscribe = False
        with self.lock:
            self.daily_universe_streamed = bool(wanted)
        if resubscribe:
            self.ensure_market_data_stream(resubscribe=True)

    def daily_universe_engines(self) -> list[TraderEngine]:
        return [
            engine
            for engine in self.connected_engines()
            if engine.config.use_top_volume_symbols and engine.config.universe_mode == "daily_rvol"
        ]

    def update_daily_universe(self, source: TraderEngine, now_et: datetime | None = None) -> None:
        """Pick the day's relative-volume list after the open, recheck it, and push it to every account."""
        if not self.daily_universe_lock.acquire(blocking=False):
            return  # another account's refresh is already updating it
        try:
            engines = self.daily_universe_engines()
            if not engines:
                return
            feed = engines[0].config.feed
            now_et = now_et or datetime.now(MARKET_TIMEZONE)
            session = now_et.date().isoformat()
            with self.lock:
                universe = self.daily_universe
            if universe is None or universe.session_date != session or universe.feed != feed:
                universe = None
                if self.daily_universe_loaded_for != f"{session}|{feed}":
                    self.daily_universe_loaded_for = f"{session}|{feed}"
                    universe = rvol_universe.load_daily_universe(DAILY_UNIVERSE_PATH, session, feed)
                with self.lock:
                    self.daily_universe = universe
            with source.lock:
                is_open = bool(source.market_clock.get("is_open"))
            with self.lock:
                current_params = self.app_settings.list_params()
            picking = rvol_universe.pick_due(universe, now_et, is_open, current_params["pick_minutes_after_open"])
            rechecking = not picking and rvol_universe.recheck_due(universe, now_et, is_open)
            # A pick snapshots the app-wide list settings; the rest of the day keeps that snapshot.
            params = current_params if picking or universe is None else universe.params
            if (picking or rechecking) and time.monotonic() >= self.daily_universe_retry_at:
                try:
                    ranked = self.rank_daily_candidates(
                        source,
                        now_et,
                        feed,
                        universe.list_for() if universe else [],
                        lookback=int(params.get("lookback_sessions") or rvol_universe.LOOKBACK_SESSIONS),
                        min_sessions=int(params.get("min_sessions") or rvol_universe.MIN_SESSIONS),
                    )
                    if not ranked:
                        raise RuntimeError("no symbols had today's volume and enough history to rank")
                except Exception as exc:
                    self.daily_universe_retry_at = time.monotonic() + DAILY_UNIVERSE_RETRY_SECONDS
                    source.log("error", f"Daily stock list update failed; retrying in {DAILY_UNIVERSE_RETRY_SECONDS}s: {exc}")
                else:
                    added: list[str] = []
                    if picking or universe is None:
                        universe = rvol_universe.new_universe(ranked, now_et, feed, params=params)
                        source.log("info", f"Daily stock list picked: {len(ranked)} ranked by relative volume ({', '.join(universe.symbols[:5])}, ...).")
                    else:
                        added = rvol_universe.merge_additions(universe, ranked, now_et)
                        if added:
                            source.log("info", f"Daily stock list recheck added {', '.join(added)}.")
                    with self.lock:
                        self.daily_universe = universe
                    try:
                        write_private_json(DAILY_UNIVERSE_PATH, rvol_universe.universe_payload(universe))
                    except OSError as exc:
                        source.log("warn", f"Could not save the daily stock list: {exc}")
                    append_day_tape_event(
                        "daily_universe_pick" if picking else "daily_universe_recheck",
                        {
                            "feed": feed,
                            "symbols": list(universe.symbols),
                            "added": added,
                            "ranks": universe.ranks,
                            # The full ranking, so a replay can rebuild any account's list size.
                            "ranking": list(universe.rankings[-1]["symbols"]) if universe.rankings else [],
                            "params": dict(universe.params),
                        },
                    )
            self.push_daily_universe(session)
        finally:
            self.daily_universe_lock.release()

    def push_daily_universe(self, session: str) -> None:
        with self.lock:
            universe = self.daily_universe
            pick_minutes = self.app_settings.daily_pick_minutes_after_open
        try:
            pick_time = et_clock_label(rvol_universe.pick_time(date.fromisoformat(session), MARKET_TIMEZONE, pick_minutes))
        except ValueError:
            pick_time = ""
        if universe is None or universe.session_date != session:
            meta = pending_daily_universe_meta(session, pick_time)
            for engine in self.list_engines():
                engine.apply_daily_universe([], meta)
            return
        try:
            picked_at = et_clock_label(datetime.fromisoformat(universe.picked_at))
        except ValueError:
            picked_at = ""
        # Each account replays the shared rankings at its own list size (no extra API calls).
        for engine in self.list_engines():
            config = engine.config
            pick_count = int(config.daily_pick_count)
            listed = universe.list_for(pick_count, int(config.daily_max_symbols))
            picked = universe.picked_for(pick_count)
            meta = {
                "status": "picked",
                "session_date": universe.session_date,
                "pick_time": pick_time,
                "picked_at": picked_at,
                "pick_count": pick_count,
                "picked_count": len(picked),
                "added_count": max(0, len(listed) - len(picked)),
            }
            engine.apply_daily_universe(without_invalid_market_data_symbols(listed), meta)

    def rank_daily_candidates(
        self,
        source: TraderEngine,
        now_et: datetime,
        feed: str,
        members: list[str],
        lookback: int = rvol_universe.LOOKBACK_SESSIONS,
        min_sessions: int = rvol_universe.MIN_SESSIONS,
    ) -> list[dict[str, Any]]:
        """Rank the most-active list (plus current members) by today's volume / average daily volume."""
        session = now_et.date()
        with source.lock:
            rows = [dict(row) for row in source.top_volume_rows]
            source_feed = source.config.feed
            data_client = source.data_client
        if data_client is None:
            raise RuntimeError("no market-data client")
        if not rows:
            raise RuntimeError("the most-active list is empty")
        today: dict[str, tuple[float, date | None]] = {}
        if source_feed == feed:
            for row in rows:
                symbol = str(row.get("symbol") or "").strip().upper()
                bar_date = str(row.get("feed_daily_bar_date") or "")
                if symbol:
                    today[symbol] = (
                        float(row.get("feed_daily_volume_raw") or 0),
                        date.fromisoformat(bar_date) if bar_date else None,
                    )
        base = [str(row.get("symbol") or "").strip().upper() for row in rows]
        missing = [symbol for symbol in dict.fromkeys(base + list(members)) if symbol and symbol not in today]
        if missing:
            # Members that fell out of the most-active list (or a different feed): one batched snapshot.
            for symbol, snapshot in fetch_stock_snapshots_chunked(data_client, missing, feed).items():
                daily_bar = model_dict(getattr(snapshot, "daily_bar", None))
                bar_date = daily_bar_session_date(daily_bar.get("timestamp"))
                today[str(symbol).upper()] = (
                    float(daily_bar.get("volume") or 0),
                    date.fromisoformat(bar_date) if bar_date else None,
                )
        key = (session.isoformat(), feed, lookback, min_sessions)
        with self.lock:
            # Keep only today's averages; earlier sessions' caches are dead weight.
            self.daily_volume_averages = {k: v for k, v in self.daily_volume_averages.items() if k == key}
            averages = dict(self.daily_volume_averages.get(key, {}))
        uncached = [symbol for symbol in today if symbol not in averages]
        if uncached:
            bars = fetch_daily_bars_chunked(
                data_client, uncached, feed, lookback_days=rvol_universe.daily_bars_lookback_days(lookback)
            )
            fresh = rvol_universe.average_daily_volumes(bars, session, MARKET_TIMEZONE, lookback, min_sessions)
            averages.update({symbol: fresh.get(symbol) for symbol in uncached})
            with self.lock:
                self.daily_volume_averages.setdefault(key, {}).update(averages)
        return rvol_universe.rank_by_rvol(today, averages, session)

    def shared_historical_bars_for(self, target: TraderEngine) -> dict[str, list[Any]] | None:
        if not target.connected:
            return None
        with target.lock:
            feed = target.config.feed
            target_symbols = set(target.scan_symbols())
        if not target_symbols:
            return None

        source: TraderEngine | None = None
        symbols: set[str] = set()
        max_required = 0
        for engine in self.connected_engines():
            if engine.config.feed != feed:
                continue
            if source is None and engine.data_client is not None:
                source = engine
            engine_symbols = set(engine.scan_symbols())
            symbols.update(engine_symbols)
            config = engine.config
            max_required = max(max_required, required_strategy_bars(config))

        if source is None or not symbols:
            return None
        per_symbol_limit = historical_bars_per_symbol(max_required)
        now = time.monotonic()

        with self.lock:
            cached = self.historical_bars_cache.get(feed)
            if cached:
                fetched_at, cached_limit, cached_symbols, data = cached
                if (
                    now - fetched_at < HISTORICAL_BARS_CACHE_SECONDS
                    and cached_limit >= per_symbol_limit
                    and symbols.issubset(cached_symbols)
                ):
                    return {symbol: list(data.get(symbol, [])) for symbol in target_symbols}

        with source.lock:
            data_client = source.data_client
        if data_client is None:
            return None

        data = fetch_stock_bars_chunked(data_client, sorted(symbols), max_required, feed)
        with self.lock:
            self.historical_bars_cache[feed] = (time.monotonic(), per_symbol_limit, set(symbols), data)
        return {symbol: list(data.get(symbol, [])) for symbol in target_symbols}

    def profile_presets(self) -> dict[str, dict[str, Any]]:
        profiles = {key: dict(value) for key, value in PROFILE_PRESETS.items()}
        profiles.update({key: dict(value) for key, value in self.custom_profiles.items()})
        return profiles

    def config_from_profile(self, profile: str, current: dict[str, Any] | None = None) -> AppConfig:
        return config_from_profile(profile, current, self.profile_presets())

    def set_custom_profiles(self, profiles: dict[str, Any]) -> None:
        cleaned: dict[str, dict[str, Any]] = {}
        for raw_key, raw_config in profiles.items():
            key = sanitize_profile_key(str(raw_key))
            if not key or key in PROFILE_PRESETS or not isinstance(raw_config, dict):
                continue
            label = str(raw_config.get("profile_label") or raw_key).strip() or key
            try:
                config = AppConfig(**(raw_config | {"profile": key})).model_dump(mode="json")
            except (TypeError, ValueError) as exc:
                record_runtime_diagnostic(
                    "config",
                    f"Custom profile {key} could not be validated; skipping profile",
                    exc,
                    source="engine",
                )
                continue
            config["profile_label"] = label
            cleaned[key] = config
        with self.lock:
            self.custom_profiles = cleaned

    def save_custom_profile(self, name: str, config: AppConfig) -> tuple[str, dict[str, Any]]:
        key = sanitize_profile_key(name) or "custom"
        if key in PROFILE_PRESETS:
            key = f"{key}-custom"
        label = str(name or key).strip() or "Custom"
        payload = config.model_copy(update={"profile": key}).model_dump(mode="json")
        payload["profile_label"] = label
        with self.lock:
            self.custom_profiles[key] = payload
        return key, payload

    def dashboard_engine(self, account_id: str | None = None) -> TraderEngine:
        with self.lock:
            requested = self.accounts.get(account_id or "")
            if account_id and account_id in self.accounts:
                if requested and requested.connected:
                    return requested
            if self.selected_account_id in self.accounts and self.accounts[self.selected_account_id].connected:
                return self.accounts[self.selected_account_id]
            for engine in self.accounts.values():
                if engine.connected:
                    return engine
            return requested or self.get(self.selected_account_id)

    def refresh_dashboard(self, account_id: str | None = None, force: bool = False) -> None:
        engine = self.dashboard_engine(account_id) if account_id else (self.shared_market_source() or self.dashboard_engine(None))
        engine.refresh_top_volume(force=force, restart_stream=False)
        self.sync_top_volume_from(engine)
        self.ensure_market_data_stream()

    def lookup_symbol(self, symbol: str, account_id: str | None = None) -> dict[str, Any]:
        payload = self.dashboard_engine(account_id).lookup_symbol(symbol)
        # A copy: the engine caches (and has already taped) the snapshot payload.
        return {**payload, "asset": self.symbol_info(str(payload.get("symbol") or symbol), account_id)}

    def symbol_info(self, symbol: str, account_id: str | None = None) -> dict[str, Any]:
        """Company name, exchange and trading flags for one ticker, from the broker's asset record.

        One trading-API call per symbol, then cached for hours; an unknown ticker or a failed call is
        cached briefly so resting the mouse on it does not keep calling. Never raises.
        """
        cleaned = clean_symbols([symbol])
        if not cleaned:
            return symbol_info_logic.missing(str(symbol or "").strip().upper())
        target = cleaned[0]
        now = time.monotonic()
        with self.lock:
            cached = self.symbol_info_cache.get(target)
        if cached and now < cached[0]:
            return cached[1]
        client = self.dashboard_engine(account_id).trading_client
        if client is None:
            return symbol_info_logic.missing(target)
        try:
            info = symbol_info_logic.asset_summary(target, model_dict(client.get_asset(target)))
        except Exception:
            info = symbol_info_logic.missing(target)
        ttl = symbol_info_logic.FOUND_CACHE_SECONDS if info["found"] else symbol_info_logic.MISSING_CACHE_SECONDS
        with self.lock:
            if len(self.symbol_info_cache) >= symbol_info_logic.CACHE_LIMIT:
                self.symbol_info_cache.clear()
            self.symbol_info_cache[target] = (now + ttl, info)
        return info

    def list_engines(self) -> list[TraderEngine]:
        with self.lock:
            return list(self.accounts.values())

    def settings(self, include_keys: bool = False) -> dict[str, Any]:
        with self.lock:
            accounts = [engine.settings(include_keys=include_keys) for engine in self.accounts.values()]
            return {
                "selected_account_id": self.selected_account_id,
                "accounts": accounts,
                "profiles": self.profile_presets(),
                "custom_profiles": {key: dict(value) for key, value in self.custom_profiles.items()},
                "app_settings": self.app_settings.model_dump(mode="json"),
                "settings_diagnostics": self.settings_diagnostics(),
                "runtime_diagnostics": runtime_diagnostics_snapshot(),
            }

    def state(self, account_id: str | None = None) -> dict[str, Any]:
        with self.lock:
            selected_id = account_id or self.selected_account_id
            selected = self.get(selected_id).state()
            return {
                "selected_account_id": selected_id,
                "accounts": [engine.summary() for engine in self.accounts.values()],
                "selected": selected,
                "profiles": self.profile_presets(),
                "market_stream": self.market_stream_state(),
                "replay": self.replay_state(),
                "settings_diagnostics": self.settings_diagnostics(),
                "runtime_diagnostics": runtime_diagnostics_snapshot(),
            }

    def market_overview(self) -> dict[str, Any]:
        """Index ETF charts, top movers and headlines for the dashboard header, cached for a minute.

        Costs three market-data calls a minute at most (index snapshots, index bars, news); the
        movers reuse the most-active rows the dashboard refresh already loaded.
        """
        with self.market_overview_lock:
            cached = self.market_overview_cache
            if cached and time.monotonic() - cached[0] < MARKET_OVERVIEW_CACHE_SECONDS:
                return cached[1]
            payload = self.fetch_market_overview()
            movers = payload.get("movers") or {}
            # Right after a restart the most-active list may not be loaded yet; don't hold empty movers for a minute.
            if payload.get("connected") and (movers.get("gainers") or movers.get("losers")):
                self.market_overview_cache = (time.monotonic(), payload)
            return payload

    def fetch_market_overview(self) -> dict[str, Any]:
        source = self.shared_market_source()
        if source is None or not source.connected:
            return {"connected": False, "indexes": [], "movers": {"gainers": [], "losers": []}, "news": [], "errors": []}
        with source.lock:
            data_client = source.data_client
            news_client = source.news_client
            feed = source.config.feed
            rows = [dict(row) for row in source.top_volume_rows]
        held = [str(position.get("symbol") or "") for engine in self.list_engines() for position in list(engine.positions)]
        with self.lock:
            watched = list(self.daily_universe.symbols) if self.daily_universe else []

        errors: list[str] = []
        symbols = [symbol for symbol, _ in market_overview.INDEX_SYMBOLS]
        snapshots: dict[str, Any] = {}
        bars: dict[str, list[Any]] = {}
        session = None
        try:
            snapshots = fetch_stock_snapshots_chunked(data_client, symbols, feed)
            session = market_overview.snapshot_session_date(snapshots.get("SPY"), MARKET_TIMEZONE)
            if session:
                start, end = market_overview.session_window(session, MARKET_TIMEZONE)
                response = data_client.get_stock_bars(
                    StockBarsRequest(
                        symbol_or_symbols=symbols,
                        timeframe=TimeFrame(market_overview.CHART_BAR_MINUTES, TimeFrameUnit.Minute),
                        start=start,
                        end=min(end, datetime.now(timezone.utc)),
                        feed=DataFeed(feed),
                        adjustment=Adjustment.RAW,
                    )
                )
                bars = {str(key).upper(): list(value) for key, value in (getattr(response, "data", None) or {}).items()}
        except Exception as exc:
            errors.append(f"Index data unavailable: {exc}")

        news: list[dict[str, Any]] = []
        if news_client is not None:
            try:
                request = NewsRequest(
                    symbols=",".join(market_overview.news_symbols(held, watched)),
                    limit=market_overview.NEWS_LIMIT,
                    exclude_contentless=False,
                )
                news = market_overview.news_items(news_client.get_news(request))
            except Exception as exc:
                errors.append(f"News unavailable: {exc}")

        return {
            "connected": True,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "feed": feed,
            "indexes": market_overview.index_cards(snapshots, bars, session, MARKET_TIMEZONE),
            "movers": market_overview.top_movers(rows),
            "news": news,
            "errors": errors,
        }

    def dashboard_state(self, account_id: str | None = None) -> dict[str, Any]:
        state = self.dashboard_engine(account_id).dashboard_state()
        state["market_stream"] = self.market_stream_state()
        state["replay"] = self.replay_state()
        state["settings_diagnostics"] = self.settings_diagnostics()
        state["runtime_diagnostics"] = runtime_diagnostics_snapshot()
        return state

    def sync_top_volume_from(self, source: TraderEngine) -> None:
        with source.lock:
            rows = [dict(row) for row in source.top_volume_rows]
            symbols = list(source.top_volume_symbols)
            updated = source.top_volume_updated
            error = source.top_volume_error
        for engine in self.list_engines():
            if engine.account_id == source.account_id:
                continue
            engine.apply_shared_top_volume(rows, symbols, updated, error)

    def connected_engines(self) -> list[TraderEngine]:
        return [engine for engine in self.list_engines() if engine.connected]

    def market_stream_should_run(self) -> bool:
        for engine in self.connected_engines():
            if not engine.config.use_market_stream:
                continue
            if not engine.config.market_hours_only:
                return True
            with engine.lock:
                market_clock = dict(engine.market_clock)
            if bool(market_clock.get("is_open")):
                return True
        return False

    def shared_market_source(self) -> TraderEngine | None:
        with self.lock:
            active_source_id = self.market_stream.source_account_id if self.market_stream is not None else ""
            active_source = self.accounts.get(active_source_id)
            if active_source and active_source.connected and active_source.config.use_market_stream:
                return active_source
            selected = self.accounts.get(self.selected_account_id)
            if selected and selected.connected and selected.config.use_market_stream:
                return selected
            for engine in self.accounts.values():
                if engine.connected and engine.config.use_market_stream:
                    return engine
        return None

    def market_data_symbols(self) -> tuple[list[str], list[str]]:
        engines = [engine for engine in self.connected_engines() if engine.config.use_market_stream]
        source = self.shared_market_source()
        ordered_engines = ([source] if source in engines else []) + [engine for engine in engines if engine is not source]

        # The plan streams at most stream_symbol_limit() symbols in total (30 on free IEX). Positions held
        # when the stream (re)subscribes come first, then the most-active list, then other scan
        # symbols; everything else is scanned through the cached REST bars. (Exits price positions
        # from the broker's current_price, so they do not depend on being streamed.)
        stream_symbols: list[str] = []
        limit = self.stream_symbol_limit()

        def add(symbol: Any) -> None:
            clean = str(symbol or "").strip().upper()
            if clean and clean not in stream_symbols and len(stream_symbols) < limit:
                stream_symbols.append(clean)

        # With a picked daily relative-volume list, its pick and the inverse sets take the slots
        # first; held positions only get leftovers (exits use the broker's price and REST bars).
        daily_engines = [
            engine
            for engine in engines
            if engine.config.use_top_volume_symbols and engine.config.universe_mode == "daily_rvol"
        ]
        with self.lock:
            universe = self.daily_universe
        if daily_engines and universe is not None and universe.session_date == datetime.now(MARKET_TIMEZONE).date().isoformat():
            pick_count = self.daily_stream_pick_count(daily_engines)
            for symbol in without_invalid_market_data_symbols(universe.stream_symbols(pick_count)):
                add(symbol)
            for engine in daily_engines:
                for symbol in engine.active_inverse_symbols():
                    add(symbol)

        for engine in ordered_engines:
            # Hold-mode and day-trade accounts never take a slot ahead of the most-active list: their
            # exits are a weekly switch or broker stops, not the stream, and what they hold must not
            # change which symbols a momentum account sees live. They still get any slots left over.
            if engine.config.entry_mode in STREAM_LEFTOVER_ENTRY_MODES:
                continue
            for symbol in without_invalid_market_data_symbols(engine.position_symbols_for_market_data()):
                add(symbol)
        source_trading = source.trading_symbols() if source in engines else []
        for symbol in source_trading:
            add(symbol)
        for engine in ordered_engines:
            for symbol in engine.scan_symbols():
                add(symbol)

        source_trading_set = {str(symbol or "").strip().upper() for symbol in source_trading}
        dashboard_symbols = [symbol for symbol in stream_symbols if symbol in source_trading_set]
        return dashboard_symbols, stream_symbols

    def ensure_market_data_stream(self, force: bool = False, resubscribe: bool = False) -> None:
        with self.market_stream_control_lock:
            self._ensure_market_data_stream_locked(force=force, resubscribe=resubscribe)

    def _ensure_market_data_stream_locked(self, force: bool = False, resubscribe: bool = False) -> None:
        # resubscribe: a healthy stream is kept only if its symbols still match (see matches() below);
        # otherwise a healthy stream is never restarted just because the wanted symbols changed.
        source = self.shared_market_source()
        if source is None:
            with self.lock:
                self.stop_shared_market_stream_locked()
                self.market_stream_health = self.default_market_stream_health()
            return

        if not self.market_stream_should_run():
            with self.lock:
                self.stop_shared_market_stream_locked()
                self.update_market_stream_health(
                    status="Market closed",
                    connected=False,
                    feed=source.config.feed,
                    dashboard_symbols=0,
                    bar_symbols=0,
                    last_error="",
                )
            clear_runtime_diagnostics(area="market_stream", source="engine")
            return

        with self.lock:
            active_stream = self.market_stream
            health = dict(self.market_stream_health)
            status = str(health.get("status") or "").lower()
            last_monotonic = health.get("_last_message_monotonic")
            fresh = isinstance(last_monotonic, (int, float)) and (time.monotonic() - float(last_monotonic) < 90)
            stream_usable = (
                active_stream is not None
                and active_stream.thread.is_alive()
                and not active_stream.stop_event.is_set()
            )
            active_source = self.accounts.get(active_stream.source_account_id) if active_stream else None
            active_source_valid = (
                active_source is not None
                and active_source.connected
                and active_source.config.use_market_stream
            )
            stable_status = status in {
                "starting",
                "connecting",
                "authenticating",
                "connected",
                "subscription sent",
                "subscribed",
                "listening",
                "streaming",
            }
            if stream_usable and active_source_valid and not force and not resubscribe:
                return
            if (
                stream_usable
                and active_source_valid
                and stable_status
                and (health.get("connected") or fresh)
                and not resubscribe
            ):
                return
            if str(self.market_stream_health.get("status") or "").lower() == "connection limit":
                limited_at = self.market_stream_health.get("_connection_limit_monotonic")
                if isinstance(limited_at, (int, float)) and (
                    time.monotonic() - float(limited_at) >= MARKET_STREAM_CONNECTION_LIMIT_RETRY_SECONDS
                ):
                    self.update_market_stream_health(status="Retrying", connected=False, last_error="")
                else:
                    return

        with self.lock:
            if str(self.market_stream_health.get("status") or "").lower() == "connection limit":
                return

        dashboard_symbols, bar_symbols = self.market_data_symbols()
        if not bar_symbols:
            with self.lock:
                self.stop_shared_market_stream_locked()
                self.update_market_stream_health(
                    status="Stopped",
                    connected=False,
                    feed="",
                    dashboard_symbols=0,
                    bar_symbols=0,
                    last_error="No symbols subscribed",
                )
            return

        with source.lock:
            api_key = source.api_key
            secret_key = source.secret_key
            feed = source.config.feed
            source_account_id = source.account_id
            source_account_name = source.name

        previous_stream: SharedMarketStreamHandle | None = None
        stream_to_start: SharedMarketStreamHandle | None = None
        with self.lock:
            if (
                self.market_stream
                and self.market_stream.thread.is_alive()
                and not self.market_stream.stop_event.is_set()
                and self.market_stream.matches(api_key, feed, dashboard_symbols, bar_symbols)
            ):
                return
            previous_stream = self.stop_shared_market_stream_locked()
            self.update_market_stream_health(
                status="Starting",
                connected=False,
                feed=feed,
                stream_id="",
                source_account_id=source_account_id,
                source_account_name=source_account_name,
                dashboard_symbols=len(dashboard_symbols),
                bar_symbols=len(bar_symbols),
                last_error="",
            )

        if previous_stream and previous_stream.thread.is_alive():
            previous_stream.thread.join(timeout=10)
            if previous_stream.thread.is_alive():
                with self.lock:
                    self.market_stream = previous_stream
                    self.update_market_stream_health(
                        status="Stopping previous stream",
                        connected=False,
                        last_error="Waiting for prior market-data websocket to close before reconnecting.",
                    )
                return

        with self.lock:
            self.market_stream = SharedMarketStreamHandle(
                api_key,
                secret_key,
                feed,
                source_account_id,
                source_account_name,
                self,
                dashboard_symbols,
                bar_symbols,
            )
            stream_to_start = self.market_stream

        stream_to_start.start()

    def reconnect_market_data_stream(self) -> None:
        with self.market_stream_control_lock:
            with self.lock:
                active_stream = self.market_stream
                self.stop_shared_market_stream_locked()
                self.update_market_stream_health(
                    status="Restarting",
                    connected=False,
                    last_error="Manual reconnect requested",
                )
            if active_stream and active_stream.thread.is_alive():
                active_stream.thread.join(timeout=10)
                if active_stream.thread.is_alive():
                    with self.lock:
                        self.market_stream = active_stream
                        self.update_market_stream_health(
                            status="Stopping previous stream",
                            connected=False,
                            last_error="Waiting for prior market-data websocket to close before reconnecting.",
                        )
                    return
            self._ensure_market_data_stream_locked(force=True)

    def stop_shared_market_stream_locked(self) -> SharedMarketStreamHandle | None:
        stopped = self.market_stream
        if stopped is not None:
            stopped.stop()
        self.market_stream = None
        self.update_market_stream_health(status="Stopped", connected=False)
        return stopped

    def is_active_market_stream(self, stream_id: str) -> bool:
        with self.lock:
            return self.market_stream is not None and self.market_stream.stream_id == stream_id

    def backfill_shared_bars(self, reason: str = "stream reconnect") -> None:
        source = self.shared_market_source()
        if source is None:
            return
        _, bar_symbols = self.market_data_symbols()
        if not bar_symbols:
            return
        with source.lock:
            data_client = source.data_client
            feed = source.config.feed
        if data_client is None:
            return

        max_required = 60
        for engine in self.connected_engines():
            config = engine.config
            max_required = max(max_required, required_strategy_bars(config))
        try:
            data = fetch_stock_bars_chunked(data_client, bar_symbols, max_required, feed)
            count = 0
            for symbol_bars in data.values():
                for bar in symbol_bars:
                    append_market_bar_once(bar, feed=feed, source="market_backfill")
                    self.record_replay_event("market_bar", compact_bar_payload(bar, daily=False))
                    for engine in self.connected_engines():
                        engine.ingest_market_bar(bar, daily=False)
                    count += 1
            self.update_market_stream_health(last_backfill=datetime.now().strftime("%H:%M:%S"), last_error="")
            self.record_replay_event(
                "market_backfill",
                {
                    "reason": reason,
                    "symbols": len(bar_symbols),
                    "bars": count,
                    "feed": feed,
                },
            )
        except Exception as exc:
            self.update_market_stream_health(last_error=f"Backfill failed: {exc}")

    def backfill_dashboard_latest_trades(self, reason: str = "stream stale") -> None:
        source = self.shared_market_source()
        if source is None:
            return
        dashboard_symbols, _ = self.market_data_symbols()
        if not dashboard_symbols:
            return
        with source.lock:
            data_client = source.data_client
            feed = source.config.feed
        if data_client is None:
            return
        try:
            trades = data_client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=dashboard_symbols, feed=DataFeed(feed))
            )
            trade_items = trades.items() if isinstance(trades, dict) else []
            count = 0
            engines = self.connected_engines()
            for _, trade in trade_items:
                append_market_trade(trade, feed=feed, source="latest_trade_backfill")
                for engine in engines:
                    engine.update_dashboard_trade(trade, count_volume=False)
                count += 1
            for engine in engines:
                engine.persist_dashboard_cache(force=True)
            self.update_market_stream_health(last_backfill=datetime.now().strftime("%H:%M:%S"), last_error="")
            self.record_replay_event(
                "market_backfill",
                {
                    "reason": reason,
                    "symbols": len(dashboard_symbols),
                    "trades": count,
                    "feed": feed,
                },
            )
        except Exception as exc:
            self.update_market_stream_health(last_error=f"Dashboard backfill failed: {exc}")

    def backfill_dashboard_recent_trades(self, reason: str = "stream fallback") -> None:
        source = self.shared_market_source()
        if source is None:
            return
        dashboard_symbols, _ = self.market_data_symbols()
        if not dashboard_symbols:
            return
        with source.lock:
            data_client = source.data_client
            feed = source.config.feed
        if data_client is None:
            return

        end = datetime.now(timezone.utc)
        with self.lock:
            start = self.dashboard_trade_backfill_cursor or (end - timedelta(seconds=60))
        if (end - start).total_seconds() < 2:
            return

        try:
            trades = data_client.get_stock_trades(
                StockTradesRequest(
                    symbol_or_symbols=dashboard_symbols,
                    start=start,
                    end=end,
                    limit=5000,
                    feed=DataFeed(feed),
                    sort=Sort.ASC,
                )
            )
            data = getattr(trades, "data", trades)
            trade_count = 0
            engines = self.connected_engines()
            if isinstance(data, dict):
                for symbol_trades in data.values():
                    for trade in symbol_trades or []:
                        append_market_trade(trade, feed=feed, source="recent_trade_backfill")
                        for engine in engines:
                            engine.update_dashboard_trade(trade, count_volume=True)
                        trade_count += 1
            for engine in engines:
                engine.persist_dashboard_cache(force=True)
            with self.lock:
                self.dashboard_trade_backfill_cursor = end
            self.update_market_stream_health(last_backfill=datetime.now().strftime("%H:%M:%S"), last_error="")
            self.record_replay_event(
                "market_backfill",
                {
                    "reason": reason,
                    "symbols": len(dashboard_symbols),
                    "trades": trade_count,
                    "feed": feed,
                },
            )
        except Exception as exc:
            self.update_market_stream_health(last_error=f"Trade backfill failed: {exc}")

    def handle_shared_market_bar(self, bar: Any, daily: bool = False) -> None:
        self.record_market_stream_message("daily_bar" if daily else "bar", bar)
        append_market_bar_once(
            bar,
            feed=self.market_stream.feed if self.market_stream else "",
            source="market_stream",
            daily=daily,
        )
        self.record_replay_event("market_bar", compact_bar_payload(bar, daily=daily))
        for engine in self.connected_engines():
            engine.ingest_market_bar(bar, daily=daily)

    def handle_shared_market_quote(self, quote: Any) -> None:
        self.record_market_stream_message("quote", quote)
        append_market_quote(
            quote,
            feed=self.market_stream.feed if self.market_stream else "",
            source="market_stream",
        )
        for engine in self.connected_engines():
            engine.update_dashboard_quote(quote)

    def handle_shared_market_trade(self, trade: Any) -> None:
        self.record_market_stream_message("trade", trade)
        append_market_trade(
            trade,
            feed=self.market_stream.feed if self.market_stream else "",
            source="market_stream",
        )
        with self.lock:
            self.dashboard_trade_backfill_cursor = datetime.now(timezone.utc)
        for engine in self.connected_engines():
            engine.update_dashboard_trade(trade)

    def handle_shared_trading_status(self, status: Any) -> None:
        raw = model_dict(status)
        self.record_market_stream_message("status", status)
        append_market_status(
            status,
            feed=self.market_stream.feed if self.market_stream else "",
            source="market_stream",
            detail=self.dashboard_engine(None).trading_status_label(raw),
        )
        self.record_replay_event(
            "market_status",
            {
                "symbol": str(raw.get("symbol", "")).upper(),
                "detail": self.dashboard_engine(None).trading_status_label(raw),
                "timestamp": format_timestamp(raw.get("timestamp")),
            },
        )
        for engine in self.connected_engines():
            engine.update_trading_status(status)


class SharedMarketStreamHandle:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str,
        source_account_id: str,
        source_account_name: str,
        manager: TraderManager,
        dashboard_symbols: list[str] | None = None,
        bar_symbols: list[str] | None = None,
    ) -> None:
        self.manager = manager
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = str(feed).strip().lower()
        self.source_account_id = source_account_id
        self.source_account_name = source_account_name
        self.stream_id = f"market-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        self.dashboard_symbols = sorted(set(dashboard_symbols or []))
        self.bar_symbols = sorted(set(bar_symbols or []) | set(self.dashboard_symbols))
        self.stream: StockDataStream | None = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="AlpacaSharedMarketStream", daemon=True)

    def build_stream(self) -> StockDataStream:
        stream = StockDataStream(self.api_key, self.secret_key, feed=stream_data_feed(self.feed))
        original_start_ws = stream._start_ws
        original_send_subscribe_msg = stream._send_subscribe_msg
        original_dispatch = stream._dispatch

        async def on_bar(bar: Any) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                return
            self.manager.handle_shared_market_bar(bar, daily=False)

        async def on_daily_bar(bar: Any) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                return
            self.manager.handle_shared_market_bar(bar, daily=True)

        async def on_status(status: Any) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                return
            self.manager.handle_shared_trading_status(status)

        async def on_quote(quote: Any) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                return
            self.manager.handle_shared_market_quote(quote)

        async def on_trade(trade: Any) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                return
            self.manager.handle_shared_market_trade(trade)

        async def dispatch_with_health(msg: dict[str, Any]) -> None:
            if not self.manager.is_active_market_stream(self.stream_id):
                await original_dispatch(msg)
                return
            msg_type = msg.get("T") if isinstance(msg, dict) else ""
            if msg_type == "subscription":
                parts = [
                    f"{key}: {len(msg.get(key) or [])}"
                    for key in ("trades", "bars", "statuses")
                    if msg.get(key)
                ]
                detail = "Subscribed " + ", ".join(parts) if parts else "Subscribed to market data"
                self.manager.update_market_stream_health(
                    status="Subscribed",
                    connected=True,
                    stream_id=self.stream_id,
                    last_message=detail,
                    last_message_at=datetime.now().strftime("%H:%M:%S"),
                    _last_message_monotonic=time.monotonic(),
                    last_error="",
                )
                self.manager.record_replay_event(
                    "market_subscription",
                    {"detail": detail, "feed": self.feed, "stream_id": self.stream_id},
                )
            elif msg_type == "error":
                code = str(msg.get("code") or "").strip()
                text = str(msg.get("msg") or "market data stream error").strip()
                status, detail = market_stream_error_status(code, text, self.manager.stream_symbol_limit())
                self.manager.update_market_stream_health(
                    status=status,
                    connected=False,
                    last_error=detail,
                )
                self.manager.record_replay_event(
                    "market_stream_error",
                    {"error": detail, "feed": self.feed, "stream_id": self.stream_id},
                )
                for engine in self.manager.connected_engines():
                    engine.log("error", f"Shared market-data websocket error: {detail}")
            await original_dispatch(msg)

        async def start_ws_with_health() -> None:
            self.manager.update_market_stream_health(
                status="Authenticating",
                connected=False,
                stream_id=self.stream_id,
                last_message="Opening market-data websocket",
                last_message_at=datetime.now().strftime("%H:%M:%S"),
                _last_message_monotonic=time.monotonic(),
                last_error="",
            )
            try:
                await original_start_ws()
            except Exception as exc:
                detail = str(exc) or exc.__class__.__name__
                connection_limited = is_connection_limit_error(detail)
                if connection_limited:
                    detail = (
                        "Alpaca market-data websocket connection limit exceeded. "
                        "Close another market-data stream using this key/feed, then reconnect."
                    )
                    self.stop_event.set()
                    try:
                        stream._should_run = False
                    except Exception as exc:
                        record_runtime_diagnostic(
                            "market_stream",
                            "Market stream stop flag update failed",
                            StreamControlError(str(exc) or exc.__class__.__name__),
                            source="engine",
                        )
                self.manager.update_market_stream_health(
                    status="Connection limit" if connection_limited else "Connection error",
                    connected=False,
                    stream_id=self.stream_id,
                    last_error=detail,
                )
                self.manager.record_replay_event(
                    "market_stream_error",
                    {"error": detail, "feed": self.feed, "stream_id": self.stream_id},
                )
                for engine in self.manager.connected_engines():
                    engine.log("error", f"Shared market-data websocket connection failed: {detail}")
                if connection_limited:
                    raise ValueError("insufficient subscription: connection limit exceeded") from exc
                raise
            self.manager.update_market_stream_health(
                status="Connected",
                connected=True,
                stream_id=self.stream_id,
                last_message="Market-data websocket authenticated",
                last_message_at=datetime.now().strftime("%H:%M:%S"),
                _last_message_monotonic=time.monotonic(),
                last_error="",
            )

        async def send_subscribe_msg_with_health() -> None:
            try:
                await original_send_subscribe_msg()
            except Exception as exc:
                detail = str(exc) or exc.__class__.__name__
                self.manager.update_market_stream_health(
                    status="Subscription error",
                    connected=False,
                    stream_id=self.stream_id,
                    last_error=detail,
                )
                self.manager.record_replay_event(
                    "market_stream_error",
                    {"error": detail, "feed": self.feed, "stream_id": self.stream_id},
                )
                for engine in self.manager.connected_engines():
                    engine.log("error", f"Shared market-data websocket subscription failed: {detail}")
                raise
            detail = (
                f"Subscription sent trades: {len(self.dashboard_symbols)}, "
                f"bars: {len(self.bar_symbols)}, statuses: {len(self.bar_symbols)}"
            )
            self.manager.update_market_stream_health(
                status="Subscription sent",
                connected=True,
                stream_id=self.stream_id,
                last_message=detail,
                last_message_at=datetime.now().strftime("%H:%M:%S"),
                _last_message_monotonic=time.monotonic(),
                last_error="",
            )
            self.manager.record_replay_event(
                "market_subscription",
                {"detail": detail, "feed": self.feed, "stream_id": self.stream_id},
            )

        stream._start_ws = start_ws_with_health
        stream._send_subscribe_msg = send_subscribe_msg_with_health
        stream._dispatch = dispatch_with_health

        if self.dashboard_symbols:
            stream.subscribe_trades(on_trade, *self.dashboard_symbols)
        if self.bar_symbols:
            stream.subscribe_bars(on_bar, *self.bar_symbols)
            stream.subscribe_trading_statuses(on_status, *self.bar_symbols)
        return stream

    def matches(
        self,
        api_key: str,
        feed: str,
        dashboard_symbols: list[str],
        bar_symbols: list[str],
    ) -> bool:
        return (
            self.api_key == api_key
            and self.feed == str(feed).strip().lower()
            and self.dashboard_symbols == sorted(set(dashboard_symbols))
            and self.bar_symbols == sorted(set(bar_symbols) | set(dashboard_symbols))
        )

    def start(self) -> None:
        self.thread.start()

    def run(self) -> None:
        dashboard_count = len(self.dashboard_symbols)
        bar_count = len(self.bar_symbols)
        detail = f"{self.feed}; {dashboard_count} dashboard symbols; {bar_count} bar symbols"
        reconnect_delay = 2.0

        while not self.stop_event.is_set():
            try:
                self.manager.update_market_stream_health(
                    status="Connecting",
                    connected=False,
                    feed=self.feed,
                    stream_id=self.stream_id,
                    source_account_id=self.source_account_id,
                    source_account_name=self.source_account_name,
                    dashboard_symbols=dashboard_count,
                    bar_symbols=bar_count,
                    last_error="",
                )
                for engine in self.manager.connected_engines():
                    engine.log("info", f"Shared market-data websocket connecting ({detail}).")
                self.stream = self.build_stream()
                self.manager.update_market_stream_health(
                    status="Listening",
                    connected=True,
                    feed=self.feed,
                    stream_id=self.stream_id,
                    source_account_id=self.source_account_id,
                    source_account_name=self.source_account_name,
                    dashboard_symbols=dashboard_count,
                    bar_symbols=bar_count,
                    last_message="Waiting for market data",
                    last_message_at="",
                    _last_message_monotonic=time.monotonic(),
                    last_error="",
                )
                self.stream.run()
                if self.stop_event.is_set():
                    break
                self.manager.update_market_stream_health(
                    status="Disconnected",
                    connected=False,
                    last_error="Stream returned without a stop request",
                )
                self.manager.record_replay_event(
                    "market_stream_error",
                    {
                        "error": "Stream returned without a stop request",
                        "feed": self.feed,
                        "stream_id": self.stream_id,
                    },
                )
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                message = str(exc)
                if is_connection_limit_error(message):
                    friendly = (
                        "Alpaca market-data websocket connection limit exceeded. "
                        "Close another market-data stream using this key/feed, then reconnect."
                    )
                    self.manager.update_market_stream_health(
                        increment_reconnect=True,
                        status="Connection limit",
                        connected=False,
                        feed=self.feed,
                        stream_id=self.stream_id,
                        source_account_id=self.source_account_id,
                        source_account_name=self.source_account_name,
                        dashboard_symbols=dashboard_count,
                        bar_symbols=bar_count,
                        last_error=friendly,
                    )
                    self.manager.record_replay_event(
                        "market_stream_error",
                        {"error": friendly, "feed": self.feed, "stream_id": self.stream_id},
                    )
                    for engine in self.manager.connected_engines():
                        engine.log("error", friendly)
                    self.manager.backfill_shared_bars("market websocket connection limit")
                    break
                self.manager.update_market_stream_health(
                    increment_reconnect=True,
                    status="Reconnecting",
                    connected=False,
                    feed=self.feed,
                    stream_id=self.stream_id,
                    source_account_id=self.source_account_id,
                    source_account_name=self.source_account_name,
                    dashboard_symbols=dashboard_count,
                    bar_symbols=bar_count,
                    last_error=message,
                )
                self.manager.record_replay_event(
                    "market_stream_error",
                    {"error": message, "feed": self.feed, "stream_id": self.stream_id},
                )
                for engine in self.manager.connected_engines():
                    engine.log("error", f"Shared market-data websocket stopped: {exc}")
                self.manager.backfill_shared_bars(f"websocket reconnect after {message}")
            finally:
                if self.stream is not None:
                    try:
                        self.stream.stop()
                    except Exception as exc:
                        if not is_already_stopped_stream_error(exc):
                            record_runtime_diagnostic(
                                "market_stream",
                                "Market stream stop failed during reconnect cleanup",
                                StreamControlError(str(exc) or exc.__class__.__name__),
                                source="engine",
                            )
                    self.stream = None

            if self.stop_event.wait(reconnect_delay):
                break
            reconnect_delay = min(60.0, reconnect_delay * 2)

    def stop(self) -> None:
        self.stop_event.set()
        try:
            if self.stream is not None:
                self.stream.stop()
        except Exception as exc:
            if not is_already_stopped_stream_error(exc):
                record_runtime_diagnostic(
                    "market_stream",
                    "Market stream stop failed",
                    StreamControlError(str(exc) or exc.__class__.__name__),
                    source="engine",
                )
