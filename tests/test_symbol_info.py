from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca.trading.models import Asset

from alpaca_desktop import symbol_info as info_logic
from alpaca_desktop.engine import TraderManager, model_dict


NVD = {
    "id": "00000000-0000-0000-0000-000000000000",
    "class": "us_equity",
    "exchange": "NASDAQ",
    "symbol": "NVD",
    "name": "GraniteShares 2x Short NVDA Daily ETF",
    "status": "active",
    "tradable": True,
    "marginable": True,
    "shortable": True,
    "easy_to_borrow": True,
    "fractionable": True,
    "attributes": ["has_options"],
}


class FakeTradingClient:
    def __init__(self, assets: dict[str, dict]) -> None:
        self.assets = assets
        self.calls: list[str] = []

    def get_asset(self, symbol: str) -> dict:
        self.calls.append(symbol)
        if symbol not in self.assets:
            raise RuntimeError("asset not found")
        return self.assets[symbol]


def manager_with(client: FakeTradingClient | None) -> TraderManager:
    manager = TraderManager()
    manager.dashboard_engine = lambda account_id=None: SimpleNamespace(  # type: ignore[method-assign]
        trading_client=client,
        lookup_symbol=lambda symbol: {"symbol": symbol.upper(), "feed": "iex"},
    )
    return manager


class AssetSummaryTests(unittest.TestCase):
    def test_summary_names_the_company_exchange_and_flags_without_ids(self) -> None:
        info = info_logic.asset_summary("NVD", NVD)
        self.assertTrue(info["found"])
        self.assertEqual(info["name"], "GraniteShares 2x Short NVDA Daily ETF")
        self.assertEqual(info["summary"], "Nasdaq · US equity")
        self.assertEqual(info["tags"], ["Fractionable", "Shortable", "Marginable", "Has options"])
        self.assertNotIn("id", info)

    def test_summary_reads_the_broker_sdk_asset_model(self) -> None:
        info = info_logic.asset_summary("NVD", model_dict(Asset(**NVD)))
        self.assertEqual(info["name"], "GraniteShares 2x Short NVDA Daily ETF")
        self.assertEqual(info["summary"], "Nasdaq · US equity")
        self.assertEqual(info["tags"], ["Fractionable", "Shortable", "Marginable", "Has options"])

    def test_untradable_whole_share_asset_says_so(self) -> None:
        info = info_logic.asset_summary(
            "XYZ", {"name": "Xyz Rights", "exchange": "OTC", "status": "inactive", "tradable": False, "fractionable": False}
        )
        self.assertEqual(info["tags"], ["Inactive", "Not tradable", "Whole shares only"])

    def test_empty_record_is_not_found(self) -> None:
        self.assertFalse(info_logic.asset_summary("XYZ", {})["found"])


class ManagerSymbolInfoTests(unittest.TestCase):
    def test_one_broker_call_per_symbol_then_cached(self) -> None:
        client = FakeTradingClient({"NVD": NVD})
        manager = manager_with(client)
        first = manager.symbol_info(" nvd ")
        second = manager.symbol_info("NVD")
        self.assertEqual(first["name"], "GraniteShares 2x Short NVDA Daily ETF")
        self.assertIs(first, second)
        self.assertEqual(client.calls, ["NVD"])

    def test_unknown_symbol_is_a_quiet_miss_cached_briefly(self) -> None:
        client = FakeTradingClient({})
        manager = manager_with(client)
        with patch("alpaca_desktop.engine.time.monotonic", return_value=1000.0):
            self.assertFalse(manager.symbol_info("ZZZZ")["found"])
            manager.symbol_info("ZZZZ")
        self.assertEqual(client.calls, ["ZZZZ"])
        with patch("alpaca_desktop.engine.time.monotonic", return_value=1000.0 + info_logic.MISSING_CACHE_SECONDS + 1):
            manager.symbol_info("ZZZZ")
        self.assertEqual(client.calls, ["ZZZZ", "ZZZZ"])

    def test_invalid_or_disconnected_never_raises(self) -> None:
        self.assertFalse(manager_with(None).symbol_info("NVD")["found"])
        self.assertFalse(manager_with(FakeTradingClient({})).symbol_info("$$$")["found"])

    def test_lookup_adds_the_asset_without_touching_the_cached_snapshot(self) -> None:
        snapshot = {"symbol": "NVD", "feed": "iex"}
        manager = manager_with(FakeTradingClient({"NVD": NVD}))
        manager.dashboard_engine = lambda account_id=None: SimpleNamespace(  # type: ignore[method-assign]
            trading_client=FakeTradingClient({"NVD": NVD}), lookup_symbol=lambda symbol: snapshot
        )
        payload = manager.lookup_symbol("nvd")
        self.assertEqual(payload["asset"]["name"], "GraniteShares 2x Short NVDA Daily ETF")
        self.assertNotIn("asset", snapshot)


if __name__ == "__main__":
    unittest.main()
