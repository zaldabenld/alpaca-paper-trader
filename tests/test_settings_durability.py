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

        self.assertEqual(engine.config.model_dump(), AppConfig(stop_loss_percent=Decimal("2")).model_dump())

    def test_switching_to_dollar_sizing_without_sending_the_percent_cap(self) -> None:
        engine = engine_with(trade_size_mode="percent", max_trade_percent=Decimal("5"), inverse_trend_hold=True)

        engine.configure_payload(payload_from_client({"trade_size_mode": "notional", "max_trade_notional": "100"}))

        self.assertEqual(engine.config.trade_size_mode, "notional")
        self.assertEqual(engine.config.max_trade_notional, Decimal("100"))
        self.assertEqual(engine.config.max_trade_percent, Decimal("0"))
        self.assertTrue(engine.config.inverse_trend_hold)

    def test_sending_only_a_percent_cap_to_a_dollar_sized_account(self) -> None:
        engine = engine_with(trade_size_mode="notional", max_trade_notional=Decimal("25"), max_trade_percent=Decimal("0"))

        engine.configure_payload(payload_from_client({"max_trade_percent": "5"}))

        self.assertEqual(engine.config.trade_size_mode, "percent")
        self.assertEqual(engine.config.max_trade_percent, Decimal("5"))
        self.assertEqual(engine.config.max_trade_notional, Decimal("0"))

    def test_a_save_without_size_settings_keeps_the_sizing(self) -> None:
        engine = engine_with(trade_size_mode="notional", max_trade_notional=Decimal("25"), max_trade_percent=Decimal("0"))

        engine.configure_payload(payload_from_client({"stop_loss_percent": "2"}))

        self.assertEqual(engine.config.trade_size_mode, "notional")
        self.assertEqual(engine.config.max_trade_notional, Decimal("25"))
        self.assertEqual(engine.config.max_trade_percent, Decimal("0"))


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

    def test_live_settings_are_mirrored_into_the_form_on_every_state(self) -> None:
        render = function_body(self.source, "function renderState(state, context)")
        self.assertIn("syncFormFromServer(selected);", render)
        sync = function_body(self.source, "function syncFormFromServer(selected)")
        # Pending edits win over the live value; everything else is written from the live config.
        self.assertIn("changedKeys.filter((key) => !dirtyConfigKeys.has(key))", sync)
        self.assertIn("applyConfig(config, new Set(incoming));", sync)
        self.assertIn("applyConfig(config);", sync)
        self.assertNotIn("markConfigPending", sync)
        self.assertNotIn("postJson", sync)

    def test_unapplied_edits_are_confirmed_before_an_account_switch_drops_them(self) -> None:
        self.assertIn("function hasPendingEdits()", self.source)
        body = function_body(self.source, "async function switchToAccount(nextAccountId)")
        self.assertLess(body.index("hasPendingEdits()"), body.index("withAccountTransition"))
        self.assertIn("window.confirm(", body)

    def test_a_plain_reload_of_settings_keeps_the_page_on_its_own_account(self) -> None:
        # Refresh and Start re-read the saved accounts. That must not move a new-account draft or
        # another window's account under the form, or undo an unapplied profile pick.
        body = function_body(self.source, "async function loadSettings(options = {})")
        self.assertIn(
            "const keepSelection = !applySelected && (isDraftAccount || Boolean(findSavedAccount(selectedAccountId)));",
            body,
        )
        self.assertIn("if (!keepSelection) {", body)
        self.assertEqual(self.source.count("selectedAccountId = payload.selected_account_id"), 1)

    def test_every_settings_field_marks_its_edit_as_pending(self) -> None:
        self.assertIn('fields.symbols.addEventListener("input", () => handleConfigFieldChange("symbols"));', self.source)
        self.assertIn(
            'fields.inverseEtfSymbols.addEventListener("input", () => handleConfigFieldChange("inverse_etf_symbols"));',
            self.source,
        )
        self.assertIn('field.addEventListener("input", () => handleConfigFieldChange(key));', self.source)

    def test_a_preset_only_marks_the_settings_it_changed(self) -> None:
        body = function_body(self.source, "function applyConfigAsPendingEdit(config)")
        self.assertIn("!sameSettingValue(before[key], after[key])", body)
        self.assertNotIn("markConfigPending(Object.keys(", self.source)

    def test_edits_made_while_a_save_is_in_flight_stay_pending(self) -> None:
        self.assertEqual(self.source.count("clearPendingEditsSince(editsAtSave);"), 2)

if __name__ == "__main__":
    unittest.main()
