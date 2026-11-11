from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module
from alpaca_desktop.engine import AccountPayload, AccountSettings, AppConfig, TraderEngine


def legacy_matching_config(**extra: Any) -> dict[str, Any]:
    """A saved config whose values match an old default set the retune rewrites (min score 30)."""
    payload = {"symbols": ["SPY"], "profile": "neutral"}
    payload.update({key: str(value) if isinstance(value, Decimal) else value
                    for key, value in engine_module.PREVIOUS_RISKBOX_SIGNAL_DEFAULTS.items()})
    payload.update(extra)
    return payload


class ConfigMigrationTests(unittest.TestCase):
    def test_fixture_really_triggers_the_legacy_retune(self) -> None:
        config = AppConfig(**legacy_matching_config())
        self.assertNotEqual(engine_module.retune_strategy_config(config).model_dump(), config.model_dump())

    def test_unversioned_saved_config_is_migrated_once_with_notes(self) -> None:
        engine = TraderEngine("legacy")
        engine.configure_saved(AccountSettings(account_id="legacy", name="Legacy",
                                               config=AppConfig.model_validate(legacy_matching_config())))
        self.assertTrue(engine.config_migration_notes)
        self.assertEqual(engine.config.config_version, engine_module.CONFIG_VERSION)
        # what gets saved next time is versioned, so a reload does not migrate again
        reloaded = TraderEngine("legacy")
        reloaded.configure_saved(AccountSettings(account_id="legacy", name="Legacy",
                                                 config=AppConfig.model_validate(engine.config.model_dump(mode="json"))))
        self.assertEqual(reloaded.config_migration_notes, [])
        self.assertEqual(reloaded.config.model_dump(), engine.config.model_dump())

    def test_versioned_user_edit_matching_an_old_default_is_kept(self) -> None:
        saved = legacy_matching_config(config_version=engine_module.CONFIG_VERSION)
        engine = TraderEngine("edited")
        engine.configure_saved(AccountSettings(account_id="edited", name="Edited", config=AppConfig.model_validate(saved)))
        self.assertEqual(engine.config_migration_notes, [])
        self.assertEqual(engine.config.min_entry_score, AppConfig.model_validate(saved).min_entry_score)

    def test_ui_save_is_never_retuned(self) -> None:
        config = AppConfig(**legacy_matching_config())
        engine = TraderEngine("ui")
        engine.configure_payload(AccountPayload(account_id="ui", name="UI", config=config))
        self.assertEqual(engine.config.model_dump(), config.model_dump())

    def test_profile_switch_does_not_retune(self) -> None:
        current = legacy_matching_config()
        switched = engine_module.config_from_profile("custom-x", current, dict(engine_module.PROFILE_PRESETS))
        self.assertEqual(switched.min_entry_score, AppConfig(**current).min_entry_score)


if __name__ == "__main__":
    unittest.main()
