from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path
from typing import Any

from alpaca.common.enums import Sort
from alpaca.data.enums import Adjustment, DataFeed, MostActivesBy
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.screener import ScreenerClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import (
    MostActivesRequest,
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
    StockSnapshotRequest,
    StockTradesRequest,
)
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetPortfolioHistoryRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
)
from pydantic import BaseModel, Field, field_validator

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
from .strategy import StrategyState, clean_symbols, decimal_value, money, number, order_quantity


DASHBOARD_TOP_LIMIT = 25
STOCK_SNAPSHOT_BATCH_SIZE = 100
TOP_VOLUME_CACHE_SECONDS = 60
PORTFOLIO_HISTORY_CACHE_SECONDS = 15
TOP_VOLUME_FORCE_COOLDOWN_SECONDS = 30
TOP_VOLUME_SOURCE = "alpaca_most_actives_volume"
LOOKUP_CACHE_SECONDS = 60
BUILT_IN_PROFILE_KEYS = ("conservative", "neutral", "aggressive")
REPLAY_EVENT_LIMIT = 400
HISTORICAL_BARS_CACHE_SECONDS = 3
HISTORICAL_BARS_PER_SYMBOL = 500
HISTORICAL_BARS_REQUEST_LIMIT = 10000
MARKET_STREAM_SYMBOL_LIMIT = 30
MARKET_STREAM_CONNECTION_LIMIT_RETRY_SECONDS = 120
MIN_EXIT_PRICE_OFFSET = Decimal("0.01")
PRICE_INCREMENT = Decimal("0.01")
SUB_DOLLAR_PRICE_INCREMENT = Decimal("0.0001")
MIN_ENTRY_NOTIONAL = Decimal("1.00")
TRADE_SIZE_MODES = {"percent", "notional", "exposure_slot"}
MAX_ENTRY_REFERENCE_PREMIUM_PERCENT = Decimal("2.0")
ASSET_CHECK_CACHE_SECONDS = 6 * 60 * 60
ORDER_FLOW_MIN_CLASSIFIED_VOLUME = Decimal("1000")
ORDER_SUBMIT_HOLD_SECONDS = 2 * 60
ORDER_REJECT_HOLD_SECONDS = 30 * 60
PROTECTIVE_ORDER_REJECT_HOLD_SECONDS = 5 * 60
NON_FRACTIONABLE_HOLD_SECONDS = 6 * 60 * 60
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AlpacaPaperTrader"
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
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
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
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
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
        "smi_period": 10,
        "min_smi": "40",
        "atr_period": 14,
        "min_buy_volume_ratio": "0.50",
        "reentry_score_boost": "10",
        "inverse_etf_mode": "allow",
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
    "smi_period",
    "min_smi",
    "atr_period",
    "min_buy_volume_ratio",
    "reentry_score_boost",
    "inverse_etf_mode",
    "volume_period",
    "volume_multiplier",
    "min_avg_volume",
    "take_profit_percent",
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
    smi_period: int = 10
    min_smi: Decimal = Decimal("40")
    atr_period: int = 14
    min_buy_volume_ratio: Decimal = Decimal("0.50")
    reentry_score_boost: Decimal = Decimal("10")
    inverse_etf_mode: str = "allow"
    volume_period: int = 20
    volume_multiplier: Decimal = Decimal("1.0")
    min_avg_volume: Decimal = Decimal("0")
    take_profit_percent: Decimal = Decimal("2.5")
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

    @field_validator("cooldown_minutes", "entry_open_guard_minutes", "entry_close_guard_minutes", "stop_loss_grace_minutes")
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
        "min_buy_volume_ratio",
        "reentry_score_boost",
        "take_profit_percent",
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
        self.min_buy_volume_ratio = min(self.min_buy_volume_ratio, Decimal("1"))
        if self.volume_multiplier < 0:
            raise ValueError("Volume multiplier cannot be negative.")
        if self.min_avg_volume < 0:
            raise ValueError("Minimum average volume cannot be negative.")
        self.max_position_notional = Decimal("0")
        self.max_position_percent = Decimal("0")
        self.daily_loss_limit = Decimal("0")
        self.daily_loss_limit_percent = Decimal("0")
        self.risk_per_trade_percent = Decimal("0")
        self.profit_trail_start_percent = Decimal("0")
        self.profit_trail_drop_percent = Decimal("0")
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


class AccountPayload(BaseModel):
    account_id: str | None = None
    name: str = "Paper Account"
    api_key: str = ""
    secret_key: str = ""
    remember: bool = True
    auto_connect: bool = True
    auto_start_trading: bool = False
    config: AppConfig


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


def config_from_profile(
    profile: str,
    current: dict[str, Any] | None = None,
    profiles: dict[str, dict[str, Any]] | None = None,
) -> AppConfig:
    profile_key = sanitize_profile_key(profile) or "neutral"
    catalog = profiles or PROFILE_PRESETS
    if profile_key not in catalog and current:
        return retune_strategy_config(AppConfig(**(current | {"profile": profile_key})))
    preset = dict(catalog.get(profile_key, catalog.get("neutral", PROFILE_PRESETS["neutral"])))
    if current:
        base = dict(current)
        for key in PROFILE_STRATEGY_KEYS:
            if key in preset:
                base[key] = preset[key]
        base["profile"] = profile_key
        return retune_strategy_config(AppConfig(**base))
    base = dict(preset)
    base["profile"] = profile_key
    return retune_strategy_config(AppConfig(**base))


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


def is_connection_limit_error(message: str) -> bool:
    return "connection limit exceeded" in str(message or "").lower()


def is_already_stopped_stream_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "nonetype" in message and "is_running" in message


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


def fetch_stock_bars_chunked(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    required_bars: int,
    feed: str,
) -> dict[str, list[Any]]:
    per_symbol_limit = historical_bars_per_symbol(required_bars)
    data: dict[str, list[Any]] = {str(symbol).upper(): [] for symbol in symbols}
    for batch in chunked_symbols_for_bar_limit(sorted(set(symbols)), per_symbol_limit):
        bars = data_client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Minute,
                limit=historical_bars_limit(len(batch), required_bars),
                feed=DataFeed(feed),
                adjustment=Adjustment.RAW,
                sort=Sort.ASC,
            )
        )
        for symbol, symbol_bars in bars.data.items():
            data[str(symbol).upper()] = list(symbol_bars)
    return data


def fetch_stock_snapshots_chunked(
    data_client: StockHistoricalDataClient,
    symbols: list[str],
    feed: str,
) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    clean_symbols_list = sorted(set(clean_symbols(symbols)))
    for index in range(0, len(clean_symbols_list), STOCK_SNAPSHOT_BATCH_SIZE):
        batch = clean_symbols_list[index : index + STOCK_SNAPSHOT_BATCH_SIZE]
        if not batch:
            continue
        try:
            response = data_client.get_stock_snapshot(
                StockSnapshotRequest(symbol_or_symbols=batch, feed=DataFeed(feed))
            )
        except Exception as exc:
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
            continue
        if isinstance(response, dict):
            for symbol, snapshot in response.items():
                snapshots[str(symbol).upper()] = snapshot
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
        self.trade_stream: Any | None = None
        self.top_volume_rows: list[dict[str, Any]] = []
        self.top_volume_symbols: list[str] = []
        self.top_volume_last_fetch_at = 0.0
        self.top_volume_updated = ""
        self.top_volume_error = ""
        self.latest_trading_statuses: dict[str, dict[str, Any]] = {}
        self.latest_quotes: dict[str, dict[str, Any]] = {}
        self.halted_symbols: dict[str, dict[str, Any]] = {}
        self.lookup_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.asset_tradeability_cache: dict[str, tuple[float, str]] = {}
        self.reentry_score_floors: dict[str, Decimal] = {}
        self.processed_reentry_exit_ids: set[str] = set()
        self.reentry_reset_at: datetime | None = None
        self.entry_lock_dates: dict[str, str] = {}
        self.entry_times: dict[str, datetime] = {}
        self.exit_lock_dates: dict[str, str] = {}
        self.position_peak_prices: dict[str, Decimal] = {}
        self.order_submit_holds: dict[tuple[str, str], datetime] = {}
        self.order_reject_holds: dict[tuple[str, str], datetime] = {}
        self.protective_order_reject_holds: dict[tuple[str, str], datetime] = {}
        self.last_scan_log_at = 0.0
        self.dashboard_cache_last_save = 0.0
        self.daily_pl_history_cache: tuple[float, str, dict[str, Any]] | None = None
        self.last_refresh = ""
        self.last_error = ""
        self.settings_load_error = ""
        self.restore_trade_guards_from_replay()

    def configure_saved(self, settings: AccountSettings) -> None:
        api_key = credential_text(settings.api_key)
        secret_key = credential_text(settings.secret_key)
        validation_error = credential_validation_error(api_key, secret_key) if api_key or secret_key else ""
        with self.lock:
            self.name = settings.name.strip() or "Paper Account"
            self.config = retune_strategy_config(settings.config)
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

    def configure_payload(self, payload: AccountPayload) -> None:
        api_key = credential_text(payload.api_key)
        secret_key = credential_text(payload.secret_key)
        validation_error = credential_validation_error(api_key, secret_key, require_pair=False)
        if validation_error:
            raise RuntimeError(validation_error)
        with self.lock:
            self.name = payload.name.strip() or "Paper Account"
            self.config = retune_strategy_config(payload.config)
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
            elif config.use_top_volume_symbols and self.top_volume_symbols:
                base_symbols = list(self.top_volume_symbols[:DASHBOARD_TOP_LIMIT])
            else:
                base_symbols = list(config.symbols)
        return merged_symbols(base_symbols, self.active_inverse_symbols())

    def active_inverse_symbols(self) -> list[str]:
        with self.lock:
            mode = self.config.inverse_etf_mode
        if mode == "inverse_only":
            return list(TOP_VOLUME_INVERSE_ETF_SYMBOLS)
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

    def scan_symbols(self, position_symbols: Any = None) -> list[str]:
        return merged_symbols(
            self.trading_symbols(),
            position_symbols or self.position_symbols_for_market_data(),
            self.market_proxy_analysis_symbols(),
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
        try:
            self.backtester_boundary().orders.cancel_order_by_id(order_id)
        except OrderExecutionError as exc:
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
            self.config = retune_strategy_config(payload.config)
            self.api_key = api_key
            self.secret_key = secret_key
            self.remember = payload.remember
            self.auto_connect = payload.auto_connect
            self.auto_start_trading = payload.auto_start_trading
            self.trading_client = TradingClient(self.api_key, self.secret_key, paper=True)
            self.data_client = StockHistoricalDataClient(self.api_key, self.secret_key)
            self.screener_client = ScreenerClient(self.api_key, self.secret_key)
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

        account = self.trading_client.get_account()
        with self.lock:
            self.account = model_dict(account)
            self.connected = True
            self.status = "Connected to Alpaca paper API"
            self.last_error = ""
            self.strategy_state = StrategyState()
            self.trading_enabled = False

        self.refresh_top_volume(force=True, restart_stream=False)
        self.refresh(run_strategy=False)
        self.log("success", f"{self.name}: connected to Alpaca paper API.")

    def stop_streams_locked(self) -> None:
        for stream in (self.trade_stream,):
            if stream is not None:
                stream.stop()
        self.trade_stream = None

    def close_api_clients_locked(self) -> None:
        for client in (self.trading_client, self.data_client, self.screener_client):
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
            self.last_scan_log_at = 0.0

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
                entry_symbols = self.trading_symbols()
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
                missing_symbols = [symbol for symbol, symbol_bars in bars_data.items() if not symbol_bars]
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
            entry_symbols = self.trading_symbols()

            self.sync_loss_reentry_floors_from_closed_orders(closed_order_dicts)

            market_clock = self.format_market_clock(clock)
            status_message = ""
            if should_trade and config.market_hours_only and not market_clock["is_open"]:
                should_trade = False
                status_message = "Market closed; auto trading paused by setting"
            opening_guard_detail = self.entry_open_guard_message(clock, config)
            closing_guard_detail = self.entry_close_guard_message(clock, config)
            entry_guard_detail = opening_guard_detail or closing_guard_detail
            entries_allowed = not entry_guard_detail
            if should_trade and entry_guard_detail:
                status_message = f"New entries paused: {entry_guard_detail}"

            position_map = {str(item.get("symbol", "")).upper(): item for item in position_dicts}
            open_positions = [item for item in position_dicts if abs(decimal_value(item.get("qty"))) > Decimal("0")]
            flat_orders = self.flatten_orders(order_dicts)
            position_symbols = {str(item.get("symbol", "")).upper() for item in open_positions}
            if should_trade:
                self.cancel_orphan_protective_orders(flat_orders, position_symbols)
            self.prune_position_trackers(position_symbols)
            pending_entry_symbols = {
                str(order.get("symbol", "")).upper()
                for order in flat_orders
                if self.order_role(order, position_symbols) == "Pending Entry"
            }
            potential_position_count = len(position_symbols | pending_entry_symbols)
            total_exposure = sum(abs(decimal_value(item.get("market_value"))) for item in open_positions)
            available_buying_power = decimal_value(account_dict.get("buying_power"))

            rows = []
            stop_now = False
            if should_trade:
                for symbol in symbols:
                    if symbol not in position_symbols:
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
                for candidate in candidates:
                    symbol = str(candidate["symbol"])
                    if symbol in position_symbols or symbol in pending_entry_symbols:
                        self.strategy_state.last_action[symbol] = "Hold (entry already reserved)"
                        continue
                    if config.max_open_positions > 0 and potential_position_count >= config.max_open_positions:
                        self.strategy_state.last_action[symbol] = "Hold (max positions)"
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
                        reserved_symbol = str(reservation.get("symbol") or symbol).upper()
                        reserved_notional = decimal_value(reservation.get("notional"))
                        if reserved_symbol not in position_symbols and reserved_symbol not in pending_entry_symbols:
                            pending_entry_symbols.add(reserved_symbol)
                            potential_position_count += 1
                        total_exposure += reserved_notional
                        available_buying_power = max(Decimal("0"), available_buying_power - reserved_notional)

            for symbol in symbols:
                if should_trade and symbol not in position_symbols and symbol not in entry_symbols:
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
            session_date = str(market_clock.get("session_date") or datetime.now().astimezone().date().isoformat())
            daily_pl_payload = self.portfolio_history_daily_pl_payload(client, session_date)
            trade_history_rows = self.trade_history_rows(closed_order_dicts)
            realized_account_basis = decimal_value(daily_pl_payload.get("daily_pl_account_basis_raw"))
            if realized_account_basis <= 0:
                realized_account_basis = last_equity if last_equity > 0 else equity
            realized_pl = self.daily_realized_pl_summary(trade_history_rows, realized_account_basis, session_date)

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
                elif status_message:
                    self.status = status_message
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
        except Exception as exc:
            self.record_runtime_exception(
                "account_refresh",
                "Account refresh failed",
                AccountRefreshError(str(exc) or exc.__class__.__name__),
                severity="error",
                log_level="error",
                set_last_error=True,
            )
        finally:
            self.refresh_lock.release()

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

    def entry_open_guard_message(self, clock: Any, config: AppConfig) -> str:
        guard_minutes = int(config.entry_open_guard_minutes or 0)
        if guard_minutes <= 0 or not bool(getattr(clock, "is_open", False)):
            return ""
        next_close = getattr(clock, "next_close", None)
        if not hasattr(next_close, "astimezone"):
            return ""
        session_open = next_close - timedelta(hours=6, minutes=30)
        now = datetime.now(next_close.tzinfo) if getattr(next_close, "tzinfo", None) else datetime.now()
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
        now = datetime.now(next_close.tzinfo) if getattr(next_close, "tzinfo", None) else datetime.now()
        seconds_left = (next_close - now).total_seconds()
        if seconds_left < 0 or seconds_left > guard_minutes * 60:
            return ""
        minutes_left = max(0, int((seconds_left + 59) // 60))
        return f"market closes in {minutes_left} min; entry guard is {guard_minutes} min"

    def entry_quality_hold_reason(self, symbol: str, snapshot: Any, config: AppConfig) -> str:
        limits = entry_profile_limits(config)
        inverse_reason = self.inverse_etf_hold_reason(symbol, config)
        if inverse_reason:
            return inverse_reason
        halt_reason = self.halt_hold_reason(symbol)
        if halt_reason:
            return halt_reason
        if snapshot.rsi is None:
            return "Hold (RSI warming)"
        if snapshot.rsi < config.buy_rsi_min:
            return f"Hold (RSI {snapshot.rsi:.1f})"
        if snapshot.bias == "Waiting":
            return "Hold (trend warming)"
        if snapshot.bias != "Bullish":
            return f"Hold (trend {snapshot.bias})"
        if snapshot.momentum_percent is None:
            return "Hold (momentum warming)"
        if snapshot.momentum_percent < Decimal("0"):
            return f"Hold (momentum {snapshot.momentum_percent:+.2f}%)"
        recent_momentum = getattr(snapshot, "recent_momentum_percent", None)
        if recent_momentum is None:
            return "Hold (recent momentum warming)"
        if recent_momentum < Decimal("0"):
            return f"Hold (recent momentum {recent_momentum:+.2f}%)"
        late_floor = limits["late_momentum_floor"]
        if late_floor > 0 and snapshot.rsi >= config.buy_rsi_max - Decimal("3") and snapshot.momentum_percent < late_floor:
            return f"Hold (late RSI {snapshot.rsi:.1f}, momentum {snapshot.momentum_percent:+.2f}%)"
        if late_floor > 0 and snapshot.smi is not None and snapshot.smi >= Decimal("90") and snapshot.momentum_percent < late_floor:
            return f"Hold (late SMI {snapshot.smi:.1f}, momentum {snapshot.momentum_percent:+.2f}%)"
        if getattr(snapshot, "long_momentum_percent", None) is None:
            return "Hold (long momentum warming)"
        if snapshot.long_momentum_percent < Decimal("0"):
            return f"Hold (long momentum {snapshot.long_momentum_percent:+.2f}%)"
        if getattr(snapshot, "session_change_percent", None) is None:
            return "Hold (session trend warming)"
        if below_entry_floor(snapshot.session_change_percent, limits["min_session_change"]):
            return f"Hold (session trend {snapshot.session_change_percent:+.2f}%)"
        if snapshot.session_change_percent > limits["max_session_extension"]:
            return f"Hold (session extended {snapshot.session_change_percent:+.2f}%)"
        if getattr(snapshot, "vwap_distance_percent", None) is None:
            return "Hold (VWAP warming)"
        if below_entry_floor(snapshot.vwap_distance_percent, limits["min_vwap_distance"]):
            return f"Hold (below VWAP {snapshot.vwap_distance_percent:+.2f}%)"
        if snapshot.vwap_distance_percent > limits["max_vwap_extension"]:
            return f"Hold (extended above VWAP {snapshot.vwap_distance_percent:+.2f}%)"
        if snapshot.smi is None:
            return "Hold (SMI warming)"
        if snapshot.relative_volume is None:
            return "Hold (volume warming)"
        flow_reason = self.order_flow_hold_reason(symbol, config)
        if flow_reason:
            return flow_reason
        asset_reason = self.asset_tradeability_hold_reason(symbol)
        if asset_reason:
            return asset_reason
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
        hard_floor = max(Decimal("0.45"), config.min_buy_volume_ratio - Decimal("0.02"))
        if ratio < hard_floor:
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
        reentry_floor = self.reentry_score_floors.get(symbol)
        if reentry_floor is not None and score < reentry_floor:
            self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
            return None
        self.strategy_state.last_action[symbol] = f"Candidate score {score:.1f}"
        return {"symbol": symbol, "rank": rank, "score": score}

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
        if has_long and config.use_bracket_orders and not pending_strategy_exit:
            protection_events, exit_submitted, protection_active = self.ensure_position_exit_orders(
                symbol,
                position,
                snapshot,
                protective_orders,
            )
            events.extend(protection_events)
            if exit_submitted:
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
            if sell_hold:
                self.strategy_state.last_action[symbol] = sell_hold
                return events, False, None
            cancelled = self.cancel_orders_for_symbol(protective_orders, symbol)
            if cancelled and not self.wait_for_symbol_app_orders_cleared(symbol):
                self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
                return events, False, None
            qty_to_sell = abs(qty)
            if self.is_take_profit_exit_reason(local_exit_reason):
                take_profit_price, _ = self.exit_prices(decimal_value(position.get("avg_entry_price")), config)
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
            if entry_score < config.min_entry_score:
                self.strategy_state.last_action[symbol] = f"Hold (score {entry_score:.1f} < {config.min_entry_score})"
                return events, False, None
            reentry_floor = self.reentry_score_floors.get(symbol)
            if reentry_floor is not None and entry_score < reentry_floor:
                self.strategy_state.last_action[symbol] = f"Hold (re-entry needs {reentry_floor:.1f})"
                return events, False, None
            if config.max_open_positions > 0 and open_position_count >= config.max_open_positions:
                self.strategy_state.last_action[symbol] = "Hold (max positions)"
                return events, False, None

            order_price = self.current_trade_price(symbol, snapshot.price)
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

    def effective_daily_loss_limit(self, config: AppConfig, equity: Decimal) -> Decimal:
        if config.daily_loss_limit_percent > 0 and equity > 0:
            return equity * config.daily_loss_limit_percent / Decimal("100")
        return config.daily_loss_limit if config.daily_loss_limit > 0 else Decimal("0")

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
            stop_loss_offset = max(
                entry_price * config.stop_loss_percent / Decimal("100"),
                self.minimum_exit_offset(entry_price),
            )
            stop_loss = self.round_exit_price(entry_price - stop_loss_offset, ROUND_DOWN)
            if stop_loss <= 0:
                stop_loss = Decimal("0")
        return take_profit, stop_loss

    def ensure_position_exit_orders(
        self,
        symbol: str,
        position: dict[str, Any] | None,
        snapshot: Any,
        protective_orders: list[dict[str, Any]],
    ) -> tuple[list[tuple[str, str]], bool, bool]:
        events: list[tuple[str, str]] = []
        if not position:
            return events, False, bool(protective_orders)

        qty = abs(decimal_value(position.get("qty")))
        entry_price = decimal_value(position.get("avg_entry_price"))
        current_price = decimal_value(position.get("current_price"))
        if current_price <= 0 and snapshot.price is not None:
            current_price = snapshot.price
        if qty <= 0 or entry_price <= 0 or current_price <= 0:
            return events, False, bool(protective_orders)

        take_profit_price, stop_loss_price = self.exit_prices(entry_price, self.config)
        if take_profit_price <= 0 and stop_loss_price <= 0:
            return events, False, bool(protective_orders)

        active_orders = [
            order for order in protective_orders
            if not self.cancel_stale_protective_order(order, qty, take_profit_price, stop_loss_price)
        ]
        take_profit_orders = [
            order for order in active_orders if self.protective_exit_kind(order) == "take_profit"
        ]
        stop_loss_orders = [
            order for order in active_orders if self.protective_exit_kind(order) == "stop_loss"
        ]
        current_gain = percent_change(current_price, entry_price)

        if stop_loss_price > 0 and current_price <= stop_loss_price and not stop_loss_orders:
            cancelled = self.cancel_orders_for_symbol(active_orders, symbol)
            if cancelled and not self.wait_for_symbol_app_orders_cleared(symbol):
                self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
                events.append(("warn", f"Waiting for existing exit order cancellation before selling {symbol}."))
                return events, False, True
            reason = (
                f"local stop-loss {self.config.stop_loss_percent}%"
                f" (gain {current_gain:.2f}%, manual stop missing)"
            )
            events.extend(self.submit_exit_order(symbol, qty, snapshot, reason))
            return events, True, False

        if take_profit_price > 0 and current_price >= take_profit_price and not take_profit_orders:
            cancelled = self.cancel_orders_for_symbol(active_orders, symbol)
            if cancelled and not self.wait_for_symbol_app_orders_cleared(symbol):
                self.strategy_state.last_action[symbol] = "Hold (waiting for exit order cancellation)"
                events.append(("warn", f"Waiting for stop cancellation before placing take-profit limit for {symbol}."))
                return events, False, True
            submitted, submit_events = self.submit_limit_exit_order(
                symbol,
                qty,
                snapshot,
                f"manual take-profit limit {self.config.take_profit_percent}%"
                f" (gain {current_gain:.2f}%)",
                take_profit_price,
            )
            events.extend(submit_events)
            return events, submitted, submitted

        protection_active = bool(active_orders)
        if stop_loss_price > 0 and not stop_loss_orders:
            submitted, submit_events = self.submit_protective_exit_order(
                symbol,
                qty,
                "stop_loss",
                stop_loss_price,
                snapshot,
                f"manual stop-loss {self.config.stop_loss_percent}%",
            )
            events.extend(submit_events)
            protection_active = protection_active or submitted
        if take_profit_price > 0 and not take_profit_orders:
            if stop_loss_price > 0 or stop_loss_orders:
                self.strategy_state.last_action[symbol] = f"Hold (profit target armed at {money(take_profit_price)})"
            else:
                submitted, submit_events = self.submit_protective_exit_order(
                    symbol,
                    qty,
                    "take_profit",
                    take_profit_price,
                    snapshot,
                    f"manual take-profit limit {self.config.take_profit_percent}%",
                )
                events.extend(submit_events)
                protection_active = protection_active or submitted
        return events, False, protection_active

    def cancel_stale_protective_order(
        self,
        order: dict[str, Any],
        qty: Decimal,
        take_profit_price: Decimal,
        stop_loss_price: Decimal,
    ) -> bool:
        if not self.is_app_protective_order(order):
            return False
        order_qty = decimal_value(order.get("qty"))
        if order_qty > 0 and abs(order_qty - qty) > Decimal("0.0001"):
            return self.cancel_open_order(order)
        kind = self.protective_exit_kind(order)
        if kind == "take_profit" and take_profit_price > 0:
            limit_price = decimal_value(order.get("limit_price"))
            if limit_price > 0 and abs(limit_price - take_profit_price) >= self.price_increment_for(take_profit_price):
                return self.cancel_open_order(order)
        if kind == "stop_loss" and stop_loss_price > 0:
            stop_price = decimal_value(order.get("stop_price"))
            if stop_price > 0 and abs(stop_price - stop_loss_price) >= self.price_increment_for(stop_loss_price):
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
    ) -> tuple[bool, list[tuple[str, str]]]:
        events: list[tuple[str, str]] = []
        if self.protective_order_blocked(symbol, kind):
            return False, events
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
            return True, events
        try:
            submitted = self.submit_order_request(order)
        except OrderExecutionError as exc:
            self.hold_rejected_protective_order(symbol, kind)
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
            return False, events
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
        return True, events

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

        if config.take_profit_percent > 0 and current_gain >= config.take_profit_percent and not has_take_profit_order:
            return (
                f"local take-profit {config.take_profit_percent}%"
                f" (gain {current_gain:.2f}%)",
                "",
            )

        if config.stop_loss_percent > 0:
            stop_price = entry_price * (Decimal("1") - config.stop_loss_percent / Decimal("100"))
            if current_price <= stop_price and not has_stop_loss_order:
                return f"local stop-loss {config.stop_loss_percent}% (gain {current_gain:.2f}%)", ""
        return "", ""

    def is_stop_loss_exit_reason(self, reason: str) -> bool:
        return "stop-loss" in str(reason or "").lower()

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
            self.record_reentry_floor(symbol, snapshot, reason)
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
        self.record_reentry_floor(symbol, snapshot, reason)
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
            self.record_reentry_floor(symbol, snapshot, reason)
        else:
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
            self.record_reentry_floor(symbol, snapshot, reason)
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

    def hold_rejected_protective_order(self, symbol: str, kind: str) -> None:
        clean_symbol = symbol.strip().upper()
        clean_kind = kind.strip().lower()
        if not clean_symbol or not clean_kind:
            return
        until = datetime.now(timezone.utc) + timedelta(seconds=PROTECTIVE_ORDER_REJECT_HOLD_SECONDS)
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

    def record_reentry_floor(self, symbol: str, snapshot: Any, reason: str = "") -> None:
        boost = self.config.reentry_score_boost
        if boost <= 0:
            return
        clean_symbol = symbol.strip().upper()
        if not clean_symbol:
            return
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
        with self.lock:
            self.order_intents.append(event)
            self.order_intents = self.order_intents[-REPLAY_EVENT_LIMIT:]
        if callable(self.replay_recorder):
            self.replay_recorder("order_intent", event)
        else:
            append_replay_event("order_intent", event)

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
        if client_id.startswith("apt-exit-"):
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

    def cancel_orders_for_symbol(self, orders: list[dict[str, Any]], symbol: str) -> int:
        clean_symbol = symbol.strip().upper()
        cancelled = 0
        for order in orders:
            if str(order.get("symbol") or "").upper() != clean_symbol:
                continue
            if not self.is_app_protective_order(order):
                continue
            if self.cancel_open_order(order):
                cancelled += 1
        return cancelled

    def wait_for_symbol_app_orders_cleared(self, symbol: str, timeout_seconds: float = 3.0) -> bool:
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
                if str(order.get("symbol") or "").upper() == clean_symbol and self.is_app_protective_order(order)
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

    def trade_history_rows(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return rows[:100]

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
                with self.lock:
                    self.reentry_score_floors.pop(symbol, None)
                continue

            if side != "sell":
                continue

            cost_basis = self.consume_trade_lots(lots.setdefault(symbol, []), filled_qty)
            realized_pl: Decimal | None = None
            if cost_basis > 0 and filled_value > 0:
                realized_pl = filled_value - cost_basis

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

    def closed_sell_needs_reentry_floor(
        self,
        item: dict[str, Any],
        reason: str,
        realized_pl: Decimal | None,
    ) -> bool:
        if str(item.get("side") or "").lower() != "sell":
            return False
        if realized_pl is not None:
            return True
        if self.is_stop_loss_exit_reason(reason):
            return True
        if self.is_take_profit_exit_reason(reason):
            return True
        role = self.order_role(item, {str(item.get("symbol") or "").upper()})
        return role in {"Strategy Exit", "Protective Exit", "Exit/Protective"}

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
            elif self.config.use_bracket_orders and self.is_fractional_quantity(decimal_value(position.get("qty"))):
                status = "Local percent fallback"
            elif self.config.use_bracket_orders:
                status = "Unprotected"
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
            if status == "Local percent fallback":
                details.append(f"fractional qty cannot use Alpaca {self.config.exit_time_in_force.upper()} bracket")
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
                "trade_history": self.trade_history,
                "order_intents": self.order_intents[-200:],
                "strategy": self.strategy_rows,
                "market_clock": self.market_clock,
                "logs": self.logs[-200:],
                "config": self.config.model_dump(mode="json"),
                "trading_symbols": trading_symbols,
                "symbol_source": symbol_source,
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
            engine.config = retune_strategy_config(config)
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
        return self.dashboard_engine(account_id).lookup_symbol(symbol)

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
        dashboard_symbols: list[str] = []
        if source in engines:
            for symbol in source.trading_symbols():
                clean = str(symbol or "").strip().upper()
                if clean and clean not in dashboard_symbols:
                    dashboard_symbols.append(clean)
                if len(dashboard_symbols) >= MARKET_STREAM_SYMBOL_LIMIT:
                    break

        bar_symbols: list[str] = []

        def append_bar_symbol(symbol: Any) -> None:
            clean = str(symbol or "").strip().upper()
            if clean and clean not in bar_symbols and len(bar_symbols) < MARKET_STREAM_SYMBOL_LIMIT:
                bar_symbols.append(clean)

        for symbol in dashboard_symbols:
            append_bar_symbol(symbol)
        for engine in ordered_engines:
            for symbol in engine.scan_symbols():
                append_bar_symbol(symbol)
            if len(bar_symbols) >= MARKET_STREAM_SYMBOL_LIMIT:
                break
        return dashboard_symbols, bar_symbols

    def ensure_market_data_stream(self, force: bool = False) -> None:
        with self.market_stream_control_lock:
            self._ensure_market_data_stream_locked(force=force)

    def _ensure_market_data_stream_locked(self, force: bool = False) -> None:
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
            if stream_usable and active_source_valid and not force:
                return
            if stream_usable and active_source_valid and stable_status and (health.get("connected") or fresh):
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
                detail = f"{text} ({code})" if code else text
                self.manager.update_market_stream_health(
                    status="Stream error",
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
