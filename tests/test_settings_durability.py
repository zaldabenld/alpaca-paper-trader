"""A save must only change the settings it actually sends.

Regression for 2026-11-11: the inverse trend hold was switched on through the API, and the next
account save from a page that had not picked the change up put it back to its old value.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from .helpers import REPO_ROOT, configure_test_environment


configure_test_environment()

from alpaca_desktop.engine import AccountPayload, AppConfig, TraderEngine, TraderManager  # noqa: E402


APP_JS = REPO_ROOT / "python_app" / "static" / "app.js"


def engine_with(**overrides) -> TraderEngine:
    engine = TraderEngine("acct")
    engine.config = AppConfig(**overrides)
    return engine


def payload_from_client(config: dict) -> AccountPayload:
    """Build the payload the way FastAPI does: from the JSON body the client sent."""
    return AccountPayload.model_validate({"account_id": "acct", "name": "Account 1", "config": config})


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    end = source.index("\n}\n", start)
    return source[start:end]


class UnsentSettingsAreKeptTests(unittest.TestCase):
    def test_a_save_that_omits_a_setting_keeps_its_current_value(self) -> None:
        engine = engine_with(inverse_trend_hold=True, universe_mode="daily_rvol", flatten_before_close_minutes=10)
        sent = AppConfig().model_dump(mode="json")
        for key in ("inverse_trend_hold", "universe_mode", "flatten_before_close_minutes"):
            sent.pop(key)

        engine.configure_payload(payload_from_client(sent))

        self.assertTrue(engine.config.inverse_trend_hold)
        self.assertEqual(engine.config.universe_mode, "daily_rvol")
        self.assertEqual(engine.config.flatten_before_close_minutes, 10)

    def test_settings_that_were_sent_still_change(self) -> None:
        engine = engine_with(inverse_trend_hold=True, stop_loss_percent=Decimal("1.25"))
        sent = engine.config.model_dump(mode="json")
        sent.pop("inverse_trend_hold")
        sent["stop_loss_percent"] = "2"

        engine.configure_payload(payload_from_client(sent))

        self.assertEqual(engine.config.stop_loss_percent, Decimal("2"))
        self.assertTrue(engine.config.inverse_trend_hold)

    def test_a_setting_sent_as_off_is_turned_off(self) -> None:
        engine = engine_with(inverse_trend_hold=True)
        sent = engine.config.model_dump(mode="json")
        sent["inverse_trend_hold"] = False

        engine.configure_payload(payload_from_client(sent))

        self.assertFalse(engine.config.inverse_trend_hold)

    def test_a_full_save_round_trips_unchanged(self) -> None:
        engine = engine_with(inverse_trend_hold=True, universe_mode="daily_rvol", take_profit_percent=Decimal("0"))
        before = engine.config.model_dump()

        engine.configure_payload(payload_from_client(engine.config.model_dump(mode="json")))

        self.assertEqual(engine.config.model_dump(), before)

    def test_a_partial_save_leaves_every_other_setting_exactly_as_it_was(self) -> None:
        engine = engine_with(
            inverse_trend_hold=True,
            profit_trail_start_percent=Decimal("3"),
            profit_trail_drop_percent=Decimal("1"),
            entry_close_guard_minutes=180,
        )
        before = engine.config.model_dump()

        engine.configure_payload(payload_from_client({"stop_loss_percent": "2"}))

        after = engine.config.model_dump()
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {"stop_loss_percent"})

    def test_a_config_built_in_code_replaces_the_whole_config(self) -> None:
        engine = engine_with(inverse_trend_hold=True)

        engine.configure_payload(AccountPayload(account_id="acct", name="Account 1", config=AppConfig()))

        self.assertFalse(engine.config.inverse_trend_hold)

    def test_copying_a_payload_keeps_the_sent_keys(self) -> None:
        # /api/connect copies the payload before handing it to the engine.
        engine = engine_with(inverse_trend_hold=True)
        payload = payload_from_client({"stop_loss_percent": "2"}).model_copy(update={"account_id": "acct"})

        self.assertTrue(engine.payload_config(payload).inverse_trend_hold)

    def test_a_new_account_takes_the_payload_as_sent(self) -> None:
        manager = TraderManager()
        payload = AccountPayload.model_validate({"name": "New", "config": {"stop_loss_percent": "2"}})

        engine = manager.upsert_payload(payload)
        engine.configure_payload(payload)

        self.assertEqual(engine.config.stop_loss_percent, Decimal("2"))
        self.assertFalse(engine.config.inverse_trend_hold)


class ViewingNeverSavesTests(unittest.TestCase):
    """Only Apply Changes and Save Account may write an account's settings."""

    def setUp(self) -> None:
        self.source = APP_JS.read_text(encoding="utf-8")

    def test_switching_accounts_does_not_save(self) -> None:
        body = function_body(self.source, "async function switchToAccount(nextAccountId)")
        self.assertNotIn("saveCurrentAccountDraft", body)
        self.assertNotIn('postJson("/api/accounts"', body)
        self.assertNotIn('postJson("/api/apply-parameters"', body)

    def test_account_settings_are_only_written_by_explicit_save_actions(self) -> None:
        # /api/accounts: Save Account. /api/apply-parameters: Apply Changes.
        self.assertEqual(self.source.count('postJson("/api/accounts"'), 1)
        self.assertEqual(self.source.count('postJson("/api/apply-parameters"'), 1)
        self.assertEqual(self.source.count("saveCurrentAccountDraft("), 2)  # the definition and Save Account

    def test_live_settings_are_shown_in_the_form(self) -> None:
        self.assertIn("function syncFormFromServer(selected)", self.source)
        self.assertIn("syncFormFromServer(selected);", self.source)

    def test_pending_edits_are_not_overwritten_or_silently_dropped(self) -> None:
        self.assertIn("dirtyConfigKeys.has(key)", self.source)
        self.assertIn("function hasPendingEdits()", self.source)
        body = function_body(self.source, "async function switchToAccount(nextAccountId)")
        self.assertIn("hasPendingEdits()", body)
        self.assertIn("window.confirm(", body)


if __name__ == "__main__":
    unittest.main()
