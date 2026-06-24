from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol

from .runtime_diagnostics import OrderExecutionError


@dataclass(frozen=True)
class StrategyEvaluationContext:
    account: dict[str, Any]
    position: dict[str, Any] | None
    open_position_count: int
    open_orders: list[dict[str, Any]]
    total_exposure: Decimal
    entries_allowed: bool = True
    entry_guard_detail: str = ""
    opening_guard_detail: str = ""
    allow_entries: bool = True


class AccountStateBoundary(Protocol):
    def snapshot(self) -> dict[str, Any]:
        ...


class MarketDataBoundary(Protocol):
    def historical_bars(self, symbols: list[str], required_bars: int, feed: str) -> dict[str, list[Any]]:
        ...

    def latest_order_price(self, symbol: str, fallback: Decimal) -> Decimal:
        ...


class OrderExecutionBoundary(Protocol):
    def submit_order(self, order: Any) -> Any:
        ...

    def cancel_order_by_id(self, order_id: str) -> None:
        ...


class ReplayBoundary(Protocol):
    def record_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class ClockBoundary(Protocol):
    def now(self) -> datetime:
        ...

    def monotonic(self) -> float:
        ...


class StrategyBoundary(Protocol):
    def scan_symbols(self, position_symbols: list[str] | None = None) -> list[str]:
        ...

    def snapshot(self, symbol: str) -> Any:
        ...

    def entry_candidate(self, symbol: str, rank: int, context: StrategyEvaluationContext) -> dict[str, Any] | None:
        ...

    def apply_strategy(self, symbol: str, context: StrategyEvaluationContext) -> tuple[list[tuple[str, str]], bool, dict[str, Any] | None]:
        ...


@dataclass(frozen=True)
class EngineBacktesterBoundary:
    account_state: AccountStateBoundary
    market_data: MarketDataBoundary
    orders: OrderExecutionBoundary
    replay: ReplayBoundary
    clock: ClockBoundary
    strategy: StrategyBoundary


class LiveAccountStateBoundary:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def snapshot(self) -> dict[str, Any]:
        with self._engine.lock:
            return {
                "account_id": self._engine.account_id,
                "name": self._engine.name,
                "account": dict(self._engine.account),
                "positions": [dict(item) for item in self._engine.positions],
                "orders": [dict(item) for item in self._engine.orders],
                "trade_history": [dict(item) for item in self._engine.trade_history],
                "market_clock": dict(self._engine.market_clock),
                "config": self._engine.config.model_dump(mode="json"),
            }


class LiveMarketDataBoundary:
    def __init__(
        self,
        engine: Any,
        fetch_historical_bars: Callable[[Any, list[str], int, str], dict[str, list[Any]]],
    ) -> None:
        self._engine = engine
        self._fetch_historical_bars = fetch_historical_bars

    def historical_bars(self, symbols: list[str], required_bars: int, feed: str) -> dict[str, list[Any]]:
        return self._fetch_historical_bars(
            self._engine.require_data_client(),
            [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()],
            int(required_bars),
            str(feed or self._engine.config.feed),
        )

    def latest_order_price(self, symbol: str, fallback: Decimal) -> Decimal:
        return self._engine.current_trade_price(symbol, fallback)


class LiveOrderExecutionBoundary:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def submit_order(self, order: Any) -> Any:
        try:
            return self._engine.require_trading_client().submit_order(order)
        except Exception as exc:
            raise OrderExecutionError(str(exc) or exc.__class__.__name__) from exc

    def cancel_order_by_id(self, order_id: str) -> None:
        try:
            self._engine.require_trading_client().cancel_order_by_id(order_id)
        except Exception as exc:
            raise OrderExecutionError(str(exc) or exc.__class__.__name__) from exc


class LiveReplayBoundary:
    def __init__(self, engine: Any, append_event: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self._engine = engine
        self._append_event = append_event

    def record_event(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        recorder = getattr(self._engine, "replay_recorder", None)
        if callable(recorder):
            recorder(kind, payload)
            return {"kind": kind, "payload": dict(payload)}
        return self._append_event(kind, payload)


class LiveClockBoundary:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class LiveStrategyBoundary:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def scan_symbols(self, position_symbols: list[str] | None = None) -> list[str]:
        return self._engine.scan_symbols(set(position_symbols or []))

    def snapshot(self, symbol: str) -> Any:
        return self._engine.snapshot(symbol)

    def entry_candidate(self, symbol: str, rank: int, context: StrategyEvaluationContext) -> dict[str, Any] | None:
        return self._engine.entry_candidate(
            symbol,
            rank,
            context.account,
            context.position,
            context.open_position_count,
            context.open_orders,
            context.entries_allowed,
        )

    def apply_strategy(
        self,
        symbol: str,
        context: StrategyEvaluationContext,
    ) -> tuple[list[tuple[str, str]], bool, dict[str, Any] | None]:
        return self._engine.apply_strategy(
            symbol,
            context.account,
            context.position,
            context.open_position_count,
            context.open_orders,
            context.total_exposure,
            context.entries_allowed,
            context.entry_guard_detail,
            context.opening_guard_detail,
            context.allow_entries,
        )
