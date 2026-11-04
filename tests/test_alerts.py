from __future__ import annotations

import time
import unittest

from .helpers import configure_test_environment

configure_test_environment()

from alpaca_desktop.alerts import DesktopNotifier


class DesktopNotifierTests(unittest.TestCase):
    def test_notify_sends_args_through_sender(self) -> None:
        sent: list[list[str]] = []
        notifier = DesktopNotifier(sender=sent.append, enabled=True)
        self.assertTrue(notifier.notify("T", "B"))
        notifier.flush()
        self.assertEqual(
            sent,
            [["notify-send", "-a", "Alpaca Paper Trader", "-u", "normal", "--", "T", "B"]],
        )

    def test_dedupe_suppresses_second_alert_with_same_key(self) -> None:
        sent: list[list[str]] = []
        notifier = DesktopNotifier(sender=sent.append, enabled=True)
        self.assertTrue(notifier.notify("T", "one", key="dup", ttl_seconds=60))
        self.assertFalse(notifier.notify("T", "two", key="dup", ttl_seconds=60))
        notifier.flush()
        self.assertEqual(len(sent), 1)

    def test_rate_limit_then_summary_precedes_next_alert(self) -> None:
        now = [1000.0]
        bodies: list[str] = []
        notifier = DesktopNotifier(
            sender=lambda args: bodies.append(args[-1]),
            enabled=True,
            max_per_minute=2,
            clock=lambda: now[0],
        )
        self.assertTrue(notifier.notify("T", "first"))
        self.assertTrue(notifier.notify("T", "second"))
        self.assertFalse(notifier.notify("T", "third"))
        now[0] += 61
        self.assertTrue(notifier.notify("T", "fourth"))
        notifier.flush()
        self.assertEqual(
            bodies,
            [
                "first",
                "second",
                "1 more alerts were suppressed (rate limit).",
                "fourth",
            ],
        )

    def test_disabled_notifier_never_calls_sender(self) -> None:
        sent: list[list[str]] = []
        notifier = DesktopNotifier(sender=sent.append, enabled=False)
        self.assertFalse(notifier.notify("T", "B"))
        notifier.flush()
        self.assertEqual(sent, [])

    def test_raising_sender_is_swallowed(self) -> None:
        def boom(args: list[str]) -> None:
            raise RuntimeError("sender exploded")

        notifier = DesktopNotifier(sender=boom, enabled=True)
        self.assertTrue(notifier.notify("T", "B"))
        notifier.flush()  # must not raise

    def test_slow_sender_does_not_block_notify(self) -> None:
        def slow(args: list[str]) -> None:
            time.sleep(0.5)

        notifier = DesktopNotifier(sender=slow, enabled=True)
        started = time.monotonic()
        self.assertTrue(notifier.notify("T", "B"))
        self.assertLess(time.monotonic() - started, 0.1)


if __name__ == "__main__":
    unittest.main()
