from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from .helpers import configure_test_environment

configure_test_environment()

from alpaca_desktop import heartbeat as hb
from alpaca_desktop.engine import TraderEngine
from alpaca_desktop.runtime_diagnostics import OrderExecutionError


class FakePoster:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[tuple[str, dict[str, str], dict]] = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, json.loads(body)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class HeartbeatTests(unittest.TestCase):
    def test_disabled_without_url_or_token(self) -> None:
        poster = FakePoster()
        beat = hb.N8nHeartbeat("", "tok", poster=poster)
        self.assertFalse(beat.enabled)
        self.assertIsNone(beat.beat_once())
        beat.start()
        self.assertIsNone(beat._thread)
        self.assertFalse(beat.halted)
        self.assertEqual(poster.calls, [])

    def test_env_configures_singleton_shape(self) -> None:
        with mock.patch.dict(os.environ, {"N8N_HEARTBEAT_URL": " https://x/webhook/alpaca-heartbeat ", "N8N_CONTROL_TOKEN": "t"}):
            beat = hb.N8nHeartbeat()
        self.assertTrue(beat.enabled)
        self.assertEqual(beat.url, "https://x/webhook/alpaca-heartbeat")

    def test_reply_sets_and_clears_halt_and_sends_token(self) -> None:
        poster = FakePoster({"ok": True, "halt": True}, {"ok": True, "halt": False})
        beat = hb.N8nHeartbeat("https://n8n/webhook/alpaca-heartbeat", "secret", poster=poster)
        self.assertTrue(beat.beat_once())
        self.assertTrue(beat.halted)
        self.assertFalse(beat.beat_once())
        self.assertFalse(beat.halted)
        url, headers, body = poster.calls[0]
        self.assertEqual(headers["X-Control-Token"], "secret")
        self.assertEqual(body, {"source": "app"})

    def test_failure_keeps_last_known_state(self) -> None:
        poster = FakePoster({"ok": True, "halt": True}, OSError("down"), {"ok": False, "error": "unauthorized"})
        beat = hb.N8nHeartbeat("https://n8n/h", "secret", poster=poster)
        beat.beat_once()
        self.assertIsNone(beat.beat_once())
        self.assertTrue(beat.halted)
        self.assertIsNone(beat.beat_once())  # reply without a boolean halt is an error, not "clear"
        self.assertTrue(beat.halted)
        self.assertIn("unexpected", beat.last_error)

    def test_probe_source(self) -> None:
        poster = FakePoster({"ok": True, "halt": False})
        beat = hb.N8nHeartbeat("https://n8n/h", "secret", poster=poster)
        beat.beat_once(source="probe")
        self.assertEqual(poster.calls[0][2], {"source": "probe"})


class EngineHaltTests(unittest.TestCase):
    def test_submit_order_request_refuses_while_halted(self) -> None:
        engine = TraderEngine("halted")
        with mock.patch.object(hb.HEARTBEAT, "_halted") as flag, \
                mock.patch.object(TraderEngine, "backtester_boundary") as boundary:
            flag.is_set.return_value = True
            with self.assertRaises(OrderExecutionError) as caught:
                engine.submit_order_request(object())
            self.assertIsInstance(caught.exception, hb.TradingHaltedError)
            boundary.assert_not_called()

    def test_submit_order_request_unchanged_when_not_halted(self) -> None:
        engine = TraderEngine("not-halted")
        self.assertFalse(hb.trading_halted())
        with mock.patch.object(TraderEngine, "backtester_boundary") as boundary:
            boundary.return_value.orders.submit_order.return_value = "sent"
            self.assertEqual(engine.submit_order_request("order"), "sent")
            boundary.return_value.orders.submit_order.assert_called_once_with("order")


if __name__ == "__main__":
    unittest.main()
