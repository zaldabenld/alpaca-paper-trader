from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop import market_overview as mo
from alpaca_desktop.engine import TraderManager


ET = ZoneInfo("America/New_York")


def snapshot(
    price: float, previous: float, session_stamp: str = "2026-11-05T05:00:00Z", open_price: float | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        latest_trade=SimpleNamespace(price=price),
        daily_bar=SimpleNamespace(timestamp=session_stamp, close=price, open=open_price or price),
        previous_daily_bar=SimpleNamespace(close=previous),
    )


class MarketOverviewLogicTests(unittest.TestCase):
    def test_index_cards_carry_change_from_previous_close_and_the_session_window(self) -> None:
        session = mo.snapshot_session_date(snapshot(681.2, 690.0), ET)
        self.assertEqual(session, date(2026, 11, 5))
        bars = {"SPY": [SimpleNamespace(timestamp="2026-11-05T14:30:00Z", close=689.0)]}
        cards = mo.index_cards({"SPY": snapshot(681.2, 690.0)}, bars, session, ET)
        self.assertEqual([card["symbol"] for card in cards], ["SPY", "QQQ", "DIA", "IWM"])
        spy = cards[0]
        self.assertAlmostEqual(spy["change"], -8.8)
        self.assertAlmostEqual(spy["change_pct"], -1.27536, places=4)
        self.assertEqual(spy["session_start"], "2026-11-05T14:30:00Z")  # 09:30 ET
        self.assertEqual(spy["session_end"], "2026-11-05T21:00:00Z")  # 16:00 ET
        self.assertEqual(spy["points"], [{"t": "2026-11-05T14:30:00Z", "c": 689.0}])
        self.assertIsNone(cards[1]["price"])  # missing snapshot: an empty card, not a crash

    def test_movers_leave_out_the_index_etfs_and_rank_by_percent(self) -> None:
        rows = [
            {"symbol": "SPY", "change_pct_raw": 9.0, "last_price_raw": 680},
            {"symbol": "AAA", "change_pct_raw": 4.0, "last_price_raw": 3},
            {"symbol": "BBB", "change_pct_raw": 12.5, "last_price_raw": 2},
            {"symbol": "CCC", "change_pct_raw": -6.0, "last_price_raw": 5},
            {"symbol": "DDD", "change_pct_raw": -1.0, "last_price_raw": 5},
            {"symbol": "EEE", "change_pct_raw": None, "last_price_raw": 5},
        ]
        movers = mo.top_movers(rows)
        self.assertEqual([item["symbol"] for item in movers["gainers"]], ["BBB", "AAA"])
        self.assertEqual([item["symbol"] for item in movers["losers"]], ["CCC", "DDD"])

    def test_previous_close_nearest_todays_open_wins(self) -> None:
        self.assertEqual(mo.nearer_previous_close(143.0, 451.2, 150.4), 150.4)  # SOXX 3:1 split
        self.assertEqual(mo.nearer_previous_close(0.045, 0.0498, 0.996), 0.0498)  # CDT adjustment not traded yet
        self.assertEqual(mo.nearer_previous_close(None, 10.0, 10.1), 10.1)
        self.assertEqual(mo.nearer_previous_close(5.0, None, 4.9), 4.9)
        self.assertIsNone(mo.nearer_previous_close(5.0, None, None))

    def test_news_symbols_start_with_the_indexes_and_skip_placeholders(self) -> None:
        self.assertEqual(
            mo.news_symbols(["046CVR015", "SH", ""], ["SH", "APP"]),
            ["SPY", "QQQ", "DIA", "IWM", "SH", "APP"],
        )

    def test_news_items_read_the_news_set(self) -> None:
        article = SimpleNamespace(
            id=7, headline=" Stocks slide ", source="benzinga", url="https://example.com/a",
            symbols=["spy"], created_at="2026-11-05T20:01:00Z",
        )
        items = mo.news_items(SimpleNamespace(data={"news": [article, SimpleNamespace(id=8, headline="")]}))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["headline"], "Stocks slide")
        self.assertEqual(items[0]["symbols"], ["SPY"])
        self.assertEqual(items[0]["created_at"], "2026-11-05T20:01:00Z")


class FakeDataClient:
    def __init__(self) -> None:
        self.bar_requests = 0

    def get_stock_snapshot(self, request):
        return {symbol: snapshot(100.0, 99.0) for symbol in request.symbol_or_symbols}

    def get_stock_bars(self, request):
        self.bar_requests += 1
        return SimpleNamespace(data={"SPY": [SimpleNamespace(timestamp="2026-11-05T14:30:00Z", close=99.5)]})


class FakeNewsClient:
    def __init__(self) -> None:
        self.symbols = ""

    def get_news(self, request):
        self.symbols = request.symbols
        return SimpleNamespace(data={"news": [SimpleNamespace(id=1, headline="Hi", source="s", url="", symbols=[], created_at=None)]})


class MarketOverviewEndpointTests(unittest.TestCase):
    def manager_with_source(self) -> tuple[TraderManager, FakeDataClient, FakeNewsClient]:
        manager = TraderManager()
        source = manager.get(manager.selected_account_id)
        source.connected = True
        data_client, news_client = FakeDataClient(), FakeNewsClient()
        source.data_client = data_client  # type: ignore[assignment]
        source.news_client = news_client  # type: ignore[assignment]
        source.top_volume_rows = [{"symbol": "AAA", "change_pct_raw": 5.0, "last_price_raw": 2}]
        source.positions = [{"symbol": "046CVR015"}, {"symbol": "SH"}]
        return manager, data_client, news_client

    def test_overview_combines_indexes_movers_and_news_and_is_cached(self) -> None:
        manager, data_client, news_client = self.manager_with_source()
        payload = manager.market_overview()
        self.assertTrue(payload["connected"])
        self.assertEqual(payload["errors"], [])
        self.assertAlmostEqual(payload["indexes"][0]["change_pct"], 1.0101, places=3)
        self.assertEqual(payload["movers"]["gainers"][0]["symbol"], "AAA")
        self.assertEqual(payload["news"][0]["headline"], "Hi")
        self.assertEqual(news_client.symbols, "SPY,QQQ,DIA,IWM,SH")
        manager.market_overview()
        self.assertEqual(data_client.bar_requests, 1)  # second call within a minute uses the cache

    def test_a_news_failure_keeps_the_index_charts(self) -> None:
        manager, _, news_client = self.manager_with_source()
        with patch.object(news_client, "get_news", side_effect=RuntimeError("down")):
            payload = manager.market_overview()
        self.assertEqual(payload["news"], [])
        self.assertEqual(payload["errors"], ["News unavailable: down"])
        self.assertEqual(payload["indexes"][0]["symbol"], "SPY")

    def test_empty_movers_are_not_cached(self) -> None:
        manager, data_client, _ = self.manager_with_source()
        source = manager.get(manager.selected_account_id)
        source.top_volume_rows = []  # most-active list not loaded yet, as right after a restart
        self.assertEqual(manager.market_overview()["movers"], {"gainers": [], "losers": []})
        source.top_volume_rows = [{"symbol": "AAA", "change_pct_raw": 5.0, "last_price_raw": 2}]
        self.assertEqual(manager.market_overview()["movers"]["gainers"][0]["symbol"], "AAA")
        self.assertEqual(data_client.bar_requests, 2)

    def test_disconnected_overview_is_empty_and_not_cached(self) -> None:
        manager = TraderManager()
        self.assertFalse(manager.market_overview()["connected"])
        self.assertIsNone(manager.market_overview_cache)


class MostActiveChangeTests(unittest.TestCase):
    def test_most_active_rows_carry_percent_change_from_the_snapshot(self) -> None:
        engine = engine_module.TraderEngine("movers")
        engine.connected = True
        engine.data_client = object()  # type: ignore[assignment]
        engine.screener_client = object()  # type: ignore[assignment]
        with (
            patch.object(engine_module, "fetch_most_active_symbols", return_value=[{"symbol": "AAA", "daily_volume_raw": 10}]),
            patch.object(engine_module, "fetch_stock_snapshots_chunked", return_value={"AAA": snapshot(11.0, 10.0)}),
            patch.object(engine_module, "load_dashboard_cache_rows", return_value={}),
            patch.object(engine, "ensure_market_stream", create=True),
        ):
            engine.refresh_top_volume(force=True, restart_stream=False)
        row = engine.top_volume_rows[0]
        self.assertAlmostEqual(row["change_pct_raw"], 10.0)
        self.assertEqual(row["previous_close_raw"], 10.0)

    def test_a_split_does_not_read_as_a_crash(self) -> None:
        # SOXX split 3:1 on 2026-11-05: raw previous close 451.20, split-adjusted 150.40.
        engine = engine_module.TraderEngine("split")
        engine.connected = True
        engine.data_client = object()  # type: ignore[assignment]
        engine.screener_client = object()  # type: ignore[assignment]
        daily = {"SOXX": [
            SimpleNamespace(timestamp="2026-11-03T05:00:00Z", close=152.0),
            SimpleNamespace(timestamp="2026-11-04T05:00:00Z", close=150.4),
            SimpleNamespace(timestamp="2026-11-05T05:00:00Z", open=143.0, close=130.9),  # today is not "previous"
        ]}
        with (
            patch.object(engine_module, "fetch_most_active_symbols", return_value=[{"symbol": "SOXX", "daily_volume_raw": 10}]),
            patch.object(engine_module, "fetch_stock_snapshots_chunked", return_value={"SOXX": snapshot(130.9, 451.2, open_price=143.0)}),
            patch.object(engine_module, "fetch_daily_bars_chunked", return_value=daily) as daily_bars,
            patch.object(engine_module, "load_dashboard_cache_rows", return_value={}),
        ):
            engine.refresh_top_volume(force=True, restart_stream=False)
            engine.top_volume_last_fetch_at = 0
            engine.refresh_top_volume(force=True, restart_stream=False)
        row = engine.top_volume_rows[0]
        self.assertEqual(row["previous_close_raw"], 150.4)
        self.assertAlmostEqual(row["change_pct_raw"], -12.97, places=2)
        self.assertEqual(daily_bars.call_count, 1)  # cached for the rest of the session

    def test_an_adjustment_not_yet_seen_in_trading_is_ignored(self) -> None:
        # CDT on 2026-11-05: adjusted bars carried a 1:20 reverse split, but it still traded near $0.04.
        engine = engine_module.TraderEngine("reverse-split")
        engine.connected = True
        engine.data_client = object()  # type: ignore[assignment]
        engine.screener_client = object()  # type: ignore[assignment]
        daily = {"CDT": [
            SimpleNamespace(timestamp="2026-11-04T05:00:00Z", open=1.0, close=0.996),
            SimpleNamespace(timestamp="2026-11-05T05:00:00Z", open=0.9, close=0.866),
        ]}
        with (
            patch.object(engine_module, "fetch_most_active_symbols", return_value=[{"symbol": "CDT", "daily_volume_raw": 10}]),
            patch.object(engine_module, "fetch_stock_snapshots_chunked", return_value={"CDT": snapshot(0.0433, 0.0498, open_price=0.045)}),
            patch.object(engine_module, "fetch_daily_bars_chunked", return_value=daily),
            patch.object(engine_module, "load_dashboard_cache_rows", return_value={}),
        ):
            engine.refresh_top_volume(force=True, restart_stream=False)
        row = engine.top_volume_rows[0]
        self.assertAlmostEqual(row["previous_close_raw"], 0.0498)
        self.assertAlmostEqual(row["change_pct_raw"], -13.05, places=1)


if __name__ == "__main__":
    unittest.main()
