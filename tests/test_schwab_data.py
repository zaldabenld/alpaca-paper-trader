from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module  # noqa: E402
from alpaca_desktop import schwab_data, storage  # noqa: E402
from alpaca_desktop.engine import TraderEngine  # noqa: E402


class FakeHttp:
    def __init__(self, responses: list[tuple[int, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


class Clock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def quote(last: float, bid: float, ask: float, volume: int, close: float, change: float) -> dict[str, Any]:
    return {
        "realtime": True,
        "quoteType": "NBBO",
        "quote": {
            "lastPrice": last,
            "bidPrice": bid,
            "askPrice": ask,
            "totalVolume": volume,
            "closePrice": close,
            "netPercentChange": change,
            "tradeTime": 1763565000000,
            "quoteTime": 1763565000500,
            "securityStatus": "Normal",
        },
    }


class SchwabDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.app_dir = Path(self.temp.name) / "AlpacaPaperTrader"
        self.app_dir_patch = patch.object(storage, "APP_DIR", self.app_dir)
        self.app_dir_patch.start()

    def tearDown(self) -> None:
        self.app_dir_patch.stop()
        self.temp.cleanup()

    def logged_in_client(self, http: FakeHttp, clock: Clock) -> schwab_data.SchwabClient:
        client = schwab_data.SchwabClient(http=http, now=clock)
        http.responses.insert(0, (200, {"access_token": "access-1", "refresh_token": "refresh-1", "expires_in": 1800}))
        client.login("key", "secret", "https://127.0.0.1", "https://127.0.0.1/?code=C0DE%40&session=abc")
        return client

    def test_login_sends_decoded_code_with_basic_auth_and_saves_no_plain_tokens(self) -> None:
        http = FakeHttp([])
        self.logged_in_client(http, Clock(1000.0))

        method, url, headers, body = http.calls[0]
        self.assertEqual((method, url), ("POST", schwab_data.TOKEN_URL))
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        form = dict(item.split("=", 1) for item in (body or b"").decode().split("&"))
        self.assertEqual(form["grant_type"], "authorization_code")
        self.assertEqual(form["code"], "C0DE%40")  # "C0DE@" form-encoded once, not twice
        self.assertEqual(form["redirect_uri"], "https%3A%2F%2F127.0.0.1")

        saved = schwab_data.credentials_path().read_text(encoding="utf-8")
        for secret in ("access-1", "refresh-1", '"secret"', '"key"'):
            self.assertNotIn(secret, saved)

    def test_access_token_refreshes_when_expired_and_keeps_login_date(self) -> None:
        clock = Clock(1000.0)
        http = FakeHttp([])
        client = self.logged_in_client(http, clock)
        self.assertEqual(client.access_token(), "access-1")
        self.assertEqual(len(http.calls), 1)

        clock.value = 1000.0 + 1800 - 60
        http.responses.append((200, {"access_token": "access-2", "refresh_token": "refresh-1", "expires_in": 1800}))
        self.assertEqual(client.access_token(), "access-2")
        form = (http.calls[1][3] or b"").decode()
        self.assertIn("grant_type=refresh_token", form)
        self.assertEqual(client.load()["refresh_issued_at"], 1000.0)

    def test_rejected_refresh_means_login_needed(self) -> None:
        clock = Clock(1000.0)
        http = FakeHttp([])
        client = self.logged_in_client(http, clock)
        clock.value += 3600
        http.responses.append((400, {"error": "invalid_grant"}))
        with self.assertRaises(schwab_data.SchwabLoginNeeded):
            client.access_token()

    def test_quotes_are_batched(self) -> None:
        http = FakeHttp([])
        client = self.logged_in_client(http, Clock(1000.0))
        symbols = [f"S{index}" for index in range(schwab_data.QUOTE_BATCH_SIZE + 5)]
        http.responses += [(200, {"S0": {}}), (200, {"S50": {}})]
        result = client.get_quotes(symbols)
        quote_calls = [call for call in http.calls if call[1].startswith(schwab_data.QUOTES_URL)]
        self.assertEqual(len(quote_calls), 2)
        self.assertEqual(quote_calls[0][2]["Authorization"], "Bearer access-1")
        self.assertEqual(set(result), {"S0", "S50"})

    def test_compare_record_differences(self) -> None:
        rows = [
            {
                "symbol": "AAA",
                "last": 10.10,
                "bid": 10.0,
                "ask": 10.2,
                "feed_volume": 50_000,
                "screener_volume": 1_000_000,
                "prev_close": 9.5,
                "change_pct": 6.3158,
                "trade_time": "2026-11-19T15:00:00Z",
            },
            {"symbol": "GONE", "last": 1.0},
        ]
        quotes = {"AAA": quote(10.0, 9.99, 10.01, 1_000_000, 9.5, 5.2632)}
        record = schwab_data.build_compare_record(rows, quotes, "iex", datetime(2026, 11, 19, 15, tzinfo=timezone.utc))

        aaa = record["symbols"][0]
        self.assertAlmostEqual(aaa["diff"]["last_pct"], 1.0)
        self.assertAlmostEqual(aaa["diff"]["mid_pct"], 1.0)
        self.assertAlmostEqual(aaa["diff"]["iex_volume_share"], 0.05)
        self.assertAlmostEqual(aaa["diff"]["screener_volume_ratio"], 1.0)
        self.assertAlmostEqual(aaa["diff"]["change_pct_points"], 1.0526)
        self.assertTrue(aaa["schwab"]["realtime"])
        self.assertEqual(record["summary"]["missing_at_schwab"], ["GONE"])
        self.assertEqual(record["summary"]["median_iex_volume_share"], 0.05)

    def test_worker_skips_without_login_and_writes_when_logged_in(self) -> None:
        logs: list[tuple[str, str]] = []
        rows = [{"symbol": "AAA", "last": 10.0, "feed_volume": 100}]

        worker = schwab_data.CompareWorker(schwab_data.SchwabClient(http=FakeHttp([])))
        self.assertFalse(worker.submit(rows, "iex", lambda *item: logs.append(item)))

        http = FakeHttp([])
        client = self.logged_in_client(http, Clock(10**10))
        http.responses.append((200, {"AAA": quote(10.0, 9.99, 10.01, 1000, 9.0, 11.1)}))
        worker = schwab_data.CompareWorker(client)
        with patch.object(schwab_data.threading, "Thread") as thread_class:
            self.assertTrue(worker.submit(rows, "iex", lambda *item: logs.append(item)))
            target = thread_class.call_args.kwargs["target"]
            args = thread_class.call_args.kwargs["args"]
            self.assertFalse(worker.submit(rows, "iex", lambda *item: logs.append(item)))  # one at a time
        target(*args)

        files = list(schwab_data.compare_dir().glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        record = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(record["symbols"][0]["diff"]["iex_volume_share"], 0.1)
        self.assertEqual(logs[0][0], "info")
        self.assertFalse(worker.submit(rows, "iex", lambda *item: logs.append(item)))  # once a minute


class SchwabEngineHookTests(unittest.TestCase):
    def run_refresh(self, market_open: bool) -> list[Any]:
        class FakeScreenerClient:
            def get_most_actives(self, request: Any) -> dict[str, Any]:
                return {"most_actives": [{"symbol": "AAA", "volume": 1500, "trade_count": 15}]}

        engine = TraderEngine("schwab-hook")
        engine.connected = True
        engine.screener_client = FakeScreenerClient()  # type: ignore[assignment]
        engine.data_client = object()  # type: ignore[assignment]
        engine.market_clock = {**engine.market_clock, "is_open": market_open}
        snapshots = {
            "AAA": SimpleNamespace(
                latest_trade=SimpleNamespace(price="23.45"),
                latest_quote=SimpleNamespace(bid_price="23.44", ask_price="23.46"),
                daily_bar=SimpleNamespace(close="23.40", volume=900),
            )
        }
        with (
            patch.object(engine_module, "fetch_stock_snapshots_chunked", return_value=snapshots),
            patch.object(schwab_data.COMPARE, "submit") as submit,
        ):
            engine.refresh_top_volume(force=True, restart_stream=False)
        return submit.call_args_list

    def test_comparison_only_runs_while_market_is_open(self) -> None:
        self.assertEqual(self.run_refresh(market_open=False), [])
        calls = self.run_refresh(market_open=True)
        self.assertEqual(len(calls), 1)
        rows, feed = calls[0].args[0], calls[0].args[1]
        self.assertEqual(feed, "iex")
        self.assertEqual(rows[0]["symbol"], "AAA")
        self.assertEqual(rows[0]["bid"], "23.44")
        self.assertEqual(rows[0]["feed_volume"], 900)
        self.assertEqual(rows[0]["screener_volume"], 1500)


if __name__ == "__main__":
    unittest.main()
