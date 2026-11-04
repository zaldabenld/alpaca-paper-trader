from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.strategy import StrategyState, normalize_bar_timestamp


NOW = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)  # 14:00 ET, mid-session
SESSION_OPEN = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)  # 04:00 ET pre-market


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class FakeBarsClient:
    """Mimics Alpaca multi-symbol bars: symbol-ordered pages, total (not per-symbol) limit,
    and a default start of the current day when no start is given."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.requests: list[Any] = []

    def get_stock_bars(self, request: Any) -> Any:
        self.requests.append(request)
        start = as_utc(request.start) if request.start else self.now.replace(hour=0, minute=0)
        start = max(start, SESSION_OPEN)
        rows: list[tuple[str, Any]] = []
        for symbol in sorted(request.symbol_or_symbols):
            moment = start.replace(second=0, microsecond=0)
            if moment < start:
                moment += timedelta(minutes=1)
            while moment <= self.now:
                rows.append((symbol, SimpleNamespace(timestamp=moment, close=100, volume=10, high=101, low=99)))
                moment += timedelta(minutes=1)
        data: dict[str, list[Any]] = {}
        for symbol, bar in rows[: request.limit]:
            data.setdefault(symbol, []).append(bar)
        return SimpleNamespace(data=data)


class HistoricalBarFetchTests(unittest.TestCase):
    symbols = [f"S{index:02d}" for index in range(27)]

    def test_fake_client_reproduces_total_limit_truncation_without_start(self) -> None:
        client = FakeBarsClient(NOW)
        request = SimpleNamespace(symbol_or_symbols=self.symbols[:20], start=None, limit=10000)
        data = client.get_stock_bars(request).data
        self.assertLess(len(data), 20)

    def test_every_symbol_gets_current_bars_in_the_afternoon(self) -> None:
        client = FakeBarsClient(NOW)
        data = engine_module.fetch_stock_bars_chunked(client, self.symbols, 63, "iex", now=NOW)

        per_symbol_limit = engine_module.historical_bars_per_symbol(63)
        self.assertEqual(set(data), set(self.symbols))
        for symbol, bars in data.items():
            self.assertTrue(bars, symbol)
            self.assertEqual(as_utc(bars[-1].timestamp), NOW, symbol)
            self.assertLessEqual(len(bars), per_symbol_limit, symbol)
        for request in client.requests:
            self.assertIsNotNone(request.start)
            self.assertLessEqual(per_symbol_limit * len(request.symbol_or_symbols), request.limit)

    def test_start_window_caps_each_symbol_at_per_symbol_limit(self) -> None:
        start = engine_module.historical_bars_start(NOW, 500)
        self.assertEqual(NOW - start, timedelta(minutes=499))


class RejectingBarsClient(FakeBarsClient):
    """Fails the whole request, like Alpaca, when any symbol is not a market-data symbol."""

    rejected = "046CVR015"

    def get_stock_bars(self, request: Any) -> Any:
        if self.rejected in request.symbol_or_symbols:
            self.requests.append(request)
            raise RuntimeError('{"message":"invalid symbol: 046CVR015"}')
        return super().get_stock_bars(request)


class InvalidSymbolTests(unittest.TestCase):
    def setUp(self) -> None:
        engine_module.INVALID_MARKET_DATA_SYMBOLS.clear()

    def tearDown(self) -> None:
        engine_module.INVALID_MARKET_DATA_SYMBOLS.clear()

    def test_cvr_position_is_dropped_instead_of_failing_the_batch(self) -> None:
        client = RejectingBarsClient(NOW)
        data = engine_module.fetch_stock_bars_chunked(client, ["SPY", "046CVR015", "AAPL"], 63, "iex", now=NOW)

        self.assertTrue(data["SPY"])
        self.assertTrue(data["AAPL"])
        self.assertEqual(data["046CVR015"], [])
        self.assertIn("046CVR015", engine_module.INVALID_MARKET_DATA_SYMBOLS)

    def test_known_invalid_symbol_is_not_requested_again(self) -> None:
        client = RejectingBarsClient(NOW)
        engine_module.fetch_stock_bars_chunked(client, ["SPY", "046CVR015"], 63, "iex", now=NOW)
        client.requests.clear()
        engine_module.fetch_stock_bars_chunked(client, ["SPY", "046CVR015"], 63, "iex", now=NOW)

        self.assertEqual(len(client.requests), 1)
        self.assertNotIn("046CVR015", client.requests[0].symbol_or_symbols)

    def test_other_errors_still_raise(self) -> None:
        class BrokenClient:
            def get_stock_bars(self, request: Any) -> Any:
                raise RuntimeError('{"message":"forbidden"}')

        with self.assertRaises(RuntimeError):
            engine_module.fetch_stock_bars_chunked(BrokenClient(), ["SPY"], 63, "iex", now=NOW)

    def test_invalid_symbol_not_in_batch_still_raises(self) -> None:
        class OtherClient:
            def get_stock_bars(self, request: Any) -> Any:
                raise RuntimeError('{"message":"invalid symbol: ZZZZ"}')

        with self.assertRaises(RuntimeError):
            engine_module.fetch_stock_bars_chunked(OtherClient(), ["SPY"], 63, "iex", now=NOW)


class StrategyHistoryTests(unittest.TestCase):
    def test_refetching_the_same_window_does_not_duplicate_bars(self) -> None:
        state = StrategyState()
        window = [NOW - timedelta(minutes=offset) for offset in range(30, 0, -1)]
        for _ in range(3):
            for moment in window:
                state.add_bar("spy", 100, moment, 10, 101, 99)
        history = state.histories["SPY"]
        self.assertEqual(len(history), 30)
        self.assertEqual([point.timestamp for point in history], sorted(point.timestamp for point in history))

    def test_stream_and_rest_timestamps_for_the_same_minute_merge(self) -> None:
        state = StrategyState()
        state.add_bar("SPY", 100, NOW, 10, 101, 99)
        state.add_bar("SPY", 102, NOW.isoformat().replace("+00:00", "Z"), 12, 103, 99)
        history = state.histories["SPY"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].close, Decimal("102"))

    def test_late_older_bar_is_inserted_in_time_order(self) -> None:
        state = StrategyState()
        state.add_bar("SPY", 100, NOW - timedelta(minutes=2))
        state.add_bar("SPY", 101, NOW)
        state.add_bar("SPY", 102, NOW - timedelta(minutes=1))
        self.assertEqual([point.close for point in state.histories["SPY"]], [Decimal("100"), Decimal("102"), Decimal("101")])

    def test_history_stays_capped_at_max_bars(self) -> None:
        state = StrategyState()
        for offset in range(10, 0, -1):
            state.add_bar("SPY", 100 + offset, NOW - timedelta(minutes=offset), max_bars=5)
        state.add_bar("SPY", 50, NOW - timedelta(minutes=20), max_bars=5)
        history = state.histories["SPY"]
        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1].timestamp, normalize_bar_timestamp(NOW - timedelta(minutes=1)))

    def test_timestamp_normalization(self) -> None:
        expected = "2026-11-04T19:00:00+00:00"
        self.assertEqual(normalize_bar_timestamp(NOW), expected)
        self.assertEqual(normalize_bar_timestamp("2026-11-04T19:00:00Z"), expected)
        self.assertEqual(normalize_bar_timestamp("2026-11-04T14:00:00-05:00"), expected)
        self.assertEqual(normalize_bar_timestamp(datetime(2026, 11, 4, 19, 0)), expected)


if __name__ == "__main__":
    unittest.main()
