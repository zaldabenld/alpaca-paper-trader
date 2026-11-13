"""One scored buy engine: movers and the old gate-based styles are profiles of it, the weighted style
has no yes/no checks, and settings saved before the merge load into the same behaviour."""

from __future__ import annotations

import time as clock_module
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from .helpers import configure_test_environment


configure_test_environment()

from alpaca_desktop import engine as engine_module  # noqa: E402
from alpaca_desktop import movers as M  # noqa: E402
from alpaca_desktop.engine import (  # noqa: E402
    DIRECTION_CHECK_KEYS,
    MARKET_TIMEZONE,
    MOVER_WEIGHT_KEYS,
    OLD_SCORE_WEIGHT_KEYS,
    AppConfig,
    config_from_profile,
    direction_checks,
    uses_climbing_reentry,
    uses_mover_readings,
    uses_old_score,
    uses_reentry_floor,
)

from .test_movers_mode import Broker, filled, hold, movers_engine, readings, refresh  # noqa: E402

D = Decimal

# Account 1's saved settings on 2026-11-13, as the file spelled them: a movers account whose unused
# old-style weights still held their defaults.
SAVED_MOVERS = dict(
    entry_mode="movers", profile="movers---weighted-score", min_entry_score="60", reentry_score_boost="20",
    mover_weight_volume="45", mover_weight_half_hour_move="15", mover_weight_vwap="15", mover_weight_five_min_move="10",
    mover_weight_range="10", mover_weight_session="5", mover_weight_rsi="0", mover_volume_full_at="5",
    mover_weight_spread="40", mover_volume_current=True, score_weight_rsi="5", score_weight_relative_volume="13",
    score_weight_momentum="14", score_weight_vwap="14", score_weight_liquidity_bonus="1.5", buy_rsi_min="42",
    stop_loss_percent="1.25", profit_trail_start_percent="2", profit_trail_drop_percent="1", config_version=1,
)


class LegacySettingsTests(unittest.TestCase):
    def test_a_saved_movers_account_is_the_scored_style_with_the_old_family_off(self) -> None:
        config = AppConfig(**SAVED_MOVERS)
        self.assertEqual(config.entry_mode, "scored")
        self.assertFalse(config.use_trend_checks)
        self.assertEqual(direction_checks(config), (True, True, True))
        self.assertEqual(config.reentry_rule, "climb")
        self.assertTrue(all(getattr(config, key) == 0 for key in OLD_SCORE_WEIGHT_KEYS))   # they never counted
        self.assertEqual((config.mover_weight_volume, config.mover_weight_spread, config.min_entry_score), (D("45"), D("40"), D("60")))
        self.assertTrue(uses_mover_readings(config) and uses_climbing_reentry(config))
        self.assertFalse(uses_old_score(config) or uses_reentry_floor(config))

    def test_a_saved_momentum_account_is_the_scored_style_with_the_mover_family_off(self) -> None:
        for raw in (dict(entry_mode="momentum", mover_weight_volume="45", mover_weight_spread="40"), dict()):
            config = AppConfig(**raw)
            self.assertEqual(config.entry_mode, "scored")
            self.assertTrue(config.use_trend_checks)
            self.assertEqual(direction_checks(config), (False, False, False))
            self.assertEqual(config.reentry_rule, "floor")
            self.assertTrue(all(getattr(config, key) == 0 for key in MOVER_WEIGHT_KEYS))
            self.assertEqual(config.score_weight_momentum, D("14"))
            self.assertFalse(uses_mover_readings(config) or uses_climbing_reentry(config))
            self.assertTrue(uses_old_score(config) and uses_reentry_floor(config))

    def test_loading_twice_changes_nothing_more(self) -> None:
        once = AppConfig(**SAVED_MOVERS)
        twice = AppConfig(**once.model_dump(mode="json"))
        self.assertEqual(once.model_dump(mode="json"), twice.model_dump(mode="json"))
        edited = AppConfig(**(once.model_dump(mode="json") | {"score_weight_rsi": "7", "use_trend_checks": True}))
        self.assertEqual((edited.score_weight_rsi, edited.use_trend_checks), (D("7"), True))   # a later edit sticks

    def test_the_other_styles_are_left_alone(self) -> None:
        for mode in ("orb", "allocation", "inplay"):
            config = AppConfig(entry_mode=mode, mover_weight_volume="45")
            self.assertEqual((config.entry_mode, config.mover_weight_volume), (mode, D("45")))
            self.assertFalse(uses_mover_readings(config) or uses_climbing_reentry(config))
        self.assertTrue(uses_reentry_floor(AppConfig(entry_mode="orb")))

    def test_built_in_profiles_and_saved_custom_profiles_are_scored_profiles(self) -> None:
        for name in ("conservative", "neutral", "aggressive"):
            config = config_from_profile(name)
            self.assertEqual((config.entry_mode, config.use_trend_checks, config.reentry_rule), ("scored", True, "floor"))
            self.assertFalse(uses_mover_readings(config))
        manager = engine_module.TraderManager() if hasattr(engine_module, "TraderManager") else engine_module.manager
        manager.set_custom_profiles({"movers---weighted-score": dict(SAVED_MOVERS, profile_label="Movers - Weighted Score")})
        saved = manager.profile_presets()["movers---weighted-score"]
        self.assertEqual((saved["entry_mode"], saved["use_trend_checks"], saved["reentry_rule"]), ("scored", False, "climb"))
        applied = manager.config_from_profile("movers---weighted-score", AppConfig().model_dump(mode="json"))
        wanted = AppConfig(**SAVED_MOVERS).model_dump(mode="json")
        got = applied.model_dump(mode="json")
        for key in sorted(engine_module.PROFILE_STRATEGY_KEYS):   # applying the profile gives the saved account's strategy
            self.assertEqual(got[key], wanted[key], key)

    def test_unknown_modes_and_rules_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(entry_mode="gated")
        with self.assertRaises(ValueError):
            AppConfig(reentry_rule="cooldown")


class ScoredSwitchTests(unittest.TestCase):
    def test_each_direction_check_is_its_own_switch(self) -> None:
        falling = readings(relative_volume="5", session_change="2", vwap_distance="1", five_min_move="-0.3")
        self.assertEqual(M.direction_hold_reason(falling), "Hold (movers: fell 0.30% in the last 5 minutes)")
        self.assertEqual(M.direction_hold_reason(falling, True, True, False), "")
        under = readings(session_change="-1", vwap_distance="-0.5", five_min_move="0.1")
        self.assertEqual(M.direction_hold_reason(under, False, True, True), "Hold (movers: 0.50% under VWAP)")
        self.assertEqual(M.direction_hold_reason(under, False, False, False), "")
        unknown = readings(session_change=None, vwap_distance="1", five_min_move="0.1")
        self.assertEqual(M.direction_hold_reason(unknown, True, True, True), "Hold (movers: price history warming up)")
        self.assertEqual(M.direction_hold_reason(unknown, False, True, True), "")   # a check that is off needs no reading

    def test_a_movers_profile_with_a_check_switched_off_buys_through_it(self) -> None:
        engine = movers_engine()
        self.assertEqual(hold(engine), "")
        fell = M.Readings(**{**engine.mover_readings("HOT", engine.snapshot("HOT")).__dict__, "five_min_move": D("-0.4")})
        with patch.object(engine, "mover_readings", return_value=fell):
            self.assertEqual(hold(engine), "Hold (movers: fell 0.40% in the last 5 minutes)")
            engine.config = engine.config.model_copy(update={"require_not_falling": False})
            self.assertEqual(hold(engine), "")

    def test_the_old_style_checks_run_first_when_a_movers_profile_switches_them_on(self) -> None:
        engine = movers_engine()
        self.assertEqual(hold(engine), "")
        engine.config = engine.config.model_copy(update={"use_trend_checks": True, "buy_rsi_max": D("65")})
        self.assertRegex(hold(engine), r"^Hold \(RSI 100\.0 above 65")    # the fixture's RSI is pinned at 100

    def test_the_old_style_score_adds_to_the_mover_score_when_its_weights_are_on(self) -> None:
        engine = movers_engine()
        self.assertEqual(hold(engine), "")
        mover_only = engine.strategy_state.entry_score["HOT"]
        engine.config = engine.config.model_copy(update={"score_weight_session_change": D("16")})
        self.assertTrue(uses_old_score(engine.config))
        self.assertEqual(hold(engine), "")
        both = engine.strategy_state.entry_score["HOT"]
        old = engine.entry_score(engine.snapshot("HOT"), engine.config, engine.order_flow_ratio("HOT"))
        self.assertGreater(old, 0)
        self.assertEqual(both, mover_only + old)
        self.assertIn("old-style score", engine.mover_scores["HOT"].describe())

    def test_the_volume_worker_and_quotes_follow_the_settings_not_a_mode(self) -> None:
        broker = Broker()
        engine = movers_engine(broker, bars=150)
        with patch.object(engine, "movers_pass", return_value="") as movers_pass:
            refresh(engine)
            movers_pass.assert_called_once()
        plain = movers_engine(Broker(), bars=150)
        plain.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"], dry_run=False)   # old-style only
        with patch.object(plain, "movers_pass", return_value="") as movers_pass:
            refresh(plain)
            movers_pass.assert_not_called()
        quote = {"HOT": SimpleNamespace(symbol="HOT", bid_price="1.24", ask_price="1.25")}
        for target, remembered in ((engine, True), (plain, False)):
            target.data_client = SimpleNamespace(get_stock_latest_trade=lambda request: {}, get_stock_latest_quote=lambda request: quote)
            with patch("alpaca_desktop.engine.append_market_trade"), patch("alpaca_desktop.engine.append_market_quote"):
                target.current_trade_price("HOT", D("1.24"))
            self.assertEqual("HOT" in target.mover_quotes, remembered)


class ReentryRuleTests(unittest.TestCase):
    losing = [filled("b1", "buy", "11.40", 30), filled("s1", "sell", "11.20", 25)]

    def test_floor_rule_on_a_mover_profile_uses_the_score_floor_not_the_count(self) -> None:
        engine = movers_engine(reentry_score_boost="20")
        engine.config = engine.config.model_copy(update={"reentry_rule": "floor"})
        engine.sync_loss_reentry_floors_from_closed_orders(self.losing)
        self.assertEqual(engine.reentry_losses_today, {})
        self.assertIn("HOT", engine.reentry_score_floors)
        engine.reentry_score_floors["HOT"] = D("99")
        with patch.object(engine, "asset_tradeability_hold_reason", return_value=""):
            self.assertIsNone(engine.entry_candidate("HOT", 0, {"equity": "1000"}, None, 0, [], True))
        self.assertEqual(engine.strategy_state.last_action["HOT"], "Hold (re-entry needs 99.0)")

    def test_climb_rule_on_an_old_style_profile_counts_losing_exits(self) -> None:
        engine = movers_engine()
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"], dry_run=False, reentry_rule="climb",
                                  reentry_score_boost="20", min_entry_score="40", use_trend_checks=False)
        engine.sync_loss_reentry_floors_from_closed_orders(self.losing)
        self.assertEqual({symbol: len(trips) for symbol, trips in engine.reentry_losses_today.items()}, {"HOT": 1})
        self.assertEqual(engine.reentry_score_floors, {})
        self.assertEqual(engine.climbing_reentry_hold_reason("HOT", D("55"), engine.config),
                         "Hold (re-entry needs 60 after 1 losing exit today; score 55)")
        self.assertEqual(engine.climbing_reentry_hold_reason("HOT", D("60"), engine.config), "")


class WeightedStyleTests(unittest.TestCase):
    """Account 3: the mover readings with no yes/no checks. A reading below zero takes points away
    on the scale it would have earned them, so heavy volume can outweigh a stock that is slipping."""

    def weighted(self, **config: Any) -> Any:
        engine = movers_engine(**config)
        engine.config = engine.config.model_copy(update={"entry_mode": "weighted"})
        return engine

    def test_the_four_direction_readings_count_both_ways(self) -> None:
        two_sided = M.Weights(two_sided=True)
        one_sided = M.Weights()
        slipping = readings(relative_volume="5", half_hour_move="-1", vwap_distance="-1.5", five_min_move="-0.35",
                            session_change="-2.5", daily_range="8")
        self.assertEqual(M.score(slipping, one_sided).total, D("55.0"))                       # volume 45 + range 10
        scored = M.score(slipping, two_sided)
        self.assertEqual(scored.total, D("55.0") - D("7.5") - D("7.5") - D("5") - D("2.5"))   # half of each weight off
        self.assertIn("under VWAP -8", scored.describe())
        crashing = readings(relative_volume="5", half_hour_move="-9", vwap_distance="-9", five_min_move="-9", session_change="-9", daily_range="8")
        self.assertEqual(M.score(crashing, two_sided).total, D("10.0"))                       # never more than the weights
        rising = readings(relative_volume="5", half_hour_move="2", vwap_distance="3", five_min_move="0.7", session_change="5", daily_range="8")
        self.assertEqual(M.score(rising, two_sided).total, M.score(rising, one_sided).total)  # going up scores the same

    def test_a_stock_that_fails_a_going_up_check_is_scored_not_held(self) -> None:
        scored_engine = movers_engine()
        weighted = self.weighted()
        base = scored_engine.mover_readings("HOT", scored_engine.snapshot("HOT"))
        dipped = M.Readings(**{**base.__dict__, "five_min_move": D("-0.07")})
        with patch.object(scored_engine, "mover_readings", return_value=dipped):
            self.assertEqual(hold(scored_engine), "Hold (movers: fell 0.07% in the last 5 minutes)")
        with patch.object(weighted, "mover_readings", return_value=dipped):
            self.assertEqual(hold(weighted), "")                                            # one point off, still a buy
            self.assertEqual(weighted.strategy_state.entry_score["HOT"], M.score(dipped, weighted.mover_weights(weighted.config)).total)
        sinking = M.Readings(**{**base.__dict__, "half_hour_move": D("-2"), "vwap_distance": D("-3"),
                                "five_min_move": D("-0.7"), "session_change": D("-5")})
        with patch.object(weighted, "mover_readings", return_value=sinking):
            self.assertRegex(hold(weighted), r"^Hold \(score \d+ of 60: ")                  # held by its score, not a veto

    def test_no_switch_can_add_a_yes_no_check_to_the_weighted_style(self) -> None:
        weighted = self.weighted()
        weighted.config = weighted.config.model_copy(update={
            "use_trend_checks": True, "buy_rsi_max": D("65"), "require_up_on_session": True,
            "require_above_vwap": True, "require_not_falling": True, "score_weight_session_change": D("16"),
        })
        self.assertEqual(direction_checks(weighted.config), (False, False, False))
        self.assertFalse(uses_old_score(weighted.config))
        base = weighted.mover_readings("HOT", weighted.snapshot("HOT"))
        dipped = M.Readings(**{**base.__dict__, "five_min_move": D("-0.07")})
        with patch.object(weighted, "mover_readings", return_value=dipped):
            self.assertEqual(hold(weighted), "")          # RSI 100 against a 65 ceiling, a dip: neither is a no here

    def test_a_reading_that_is_not_in_yet_costs_nothing_and_holds_nothing(self) -> None:
        weighted = self.weighted()
        base = weighted.mover_readings("HOT", weighted.snapshot("HOT"))
        unknown = M.Readings(**{**base.__dict__, "session_change": None})
        with patch.object(weighted, "mover_readings", return_value=unknown):
            self.assertNotIn("warming", hold(weighted))

    def test_the_re_entry_score_still_climbs(self) -> None:
        weighted = self.weighted(reentry_score_boost="20")
        self.assertTrue(uses_climbing_reentry(weighted.config))
        weighted.sync_loss_reentry_floors_from_closed_orders([
            filled("b1", "buy", "11.40", 30), filled("s1", "sell", "11.20", 25),
            filled("b2", "buy", "11.45", 20), filled("s2", "sell", "11.30", 15),
        ])
        self.assertEqual(weighted.movers_reentry_bar("HOT", weighted.config), (D("100"), 2))
        self.assertIn("re-entry needs 100 after 2 losing exits today", hold(weighted))

    def test_refresh_buys_a_dipping_stock_the_scored_style_holds(self) -> None:
        for mode, bought in (("weighted", [("HOT", "buy")]), ("scored", [])):
            with self.subTest(mode=mode):
                broker = Broker()
                engine = movers_engine(broker, bars=150)
                engine.config = engine.config.model_copy(update={"entry_mode": mode})
                base = engine.mover_readings("HOT", engine.snapshot("HOT"))
                dipped = M.Readings(**{**base.__dict__, "five_min_move": D("-0.07")})
                with patch.object(engine, "mover_readings", return_value=dipped):
                    refresh(engine)
                self.assertEqual([(order.symbol, order.side.value) for order in broker.submitted], bought)

    def test_a_weighted_account_built_from_nothing_gets_the_mover_weights(self) -> None:
        config = AppConfig(entry_mode="weighted")
        self.assertEqual((config.mover_weight_volume, config.mover_weight_vwap, config.mover_weight_spread), (D("45"), D("15"), D("40")))
        self.assertTrue(uses_mover_readings(config))
        self.assertTrue(M.Weights(two_sided=True) != M.Weights())
        engine = movers_engine()
        engine.config = config
        self.assertTrue(engine.mover_weights(config).two_sided)


if __name__ == "__main__":
    unittest.main()


class SettingsMergeTests(unittest.TestCase):
    """The settings API merges what a client sent with the account's current settings. A client that
    still names a style the old way has to get that whole style, not half of it."""

    def merged(self, current: AppConfig, sent: dict[str, Any]) -> AppConfig:
        engine = movers_engine()
        engine.config = current
        return engine.payload_config(engine_module.AccountPayload(name="Account", config=sent))

    def test_a_partial_save_naming_movers_gets_the_whole_movers_style(self) -> None:
        config = self.merged(AppConfig(), {"entry_mode": "movers"})
        self.assertEqual((config.entry_mode, config.use_trend_checks, config.reentry_rule), ("scored", False, "climb"))
        self.assertEqual(direction_checks(config), (True, True, True))
        self.assertEqual((config.mover_weight_volume, config.mover_weight_spread), (D("45"), D("40")))
        self.assertFalse(uses_old_score(config))

    def test_an_old_page_saving_momentum_over_a_movers_account_gets_the_whole_old_style(self) -> None:
        old_page = AppConfig().model_dump(mode="json")
        for key in ("use_trend_checks", "reentry_rule", *DIRECTION_CHECK_KEYS):
            old_page.pop(key)                                   # a page from before the merge does not know these
        old_page.update(entry_mode="momentum", mover_weight_volume="45")
        config = self.merged(AppConfig(**SAVED_MOVERS), old_page)
        self.assertEqual((config.entry_mode, config.use_trend_checks, config.reentry_rule), ("scored", True, "floor"))
        self.assertEqual(direction_checks(config), (False, False, False))
        self.assertFalse(uses_mover_readings(config))
        self.assertTrue(uses_old_score(config))

    def test_moving_an_account_to_the_weighted_style_gives_it_weights_to_buy_on(self) -> None:
        config = self.merged(AppConfig(), {"entry_mode": "weighted"})
        self.assertEqual((config.entry_mode, config.mover_weight_volume, config.mover_weight_spread), ("weighted", D("45"), D("40")))
        tuned = AppConfig(**(SAVED_MOVERS | {"mover_weight_volume": "30"}))
        kept = self.merged(tuned, {"entry_mode": "weighted"})
        self.assertEqual((kept.entry_mode, kept.mover_weight_volume, kept.min_entry_score), ("weighted", D("30"), D("60")))

    def test_a_partial_save_of_one_setting_changes_only_that_setting(self) -> None:
        current = AppConfig(**SAVED_MOVERS)
        config = self.merged(current, {"mover_weight_spread": "25"})
        want = current.model_dump(mode="json") | {"mover_weight_spread": "25"}
        self.assertEqual(config.model_dump(mode="json"), want)

    def test_an_older_account_in_another_style_does_not_carry_mover_weights_into_scored(self) -> None:
        # Hold and day-trade accounts saved before the merge hold the old mover defaults, unused.
        for mode in ("allocation", "inplay", "orb"):
            saved = AppConfig(entry_mode=mode, mover_weight_volume="45", mover_weight_spread="40", config_version=1)
            self.assertEqual((saved.entry_mode, saved.mover_weight_volume, saved.config_version), (mode, D("0"), 2))
            switched = self.merged(saved, {"entry_mode": "scored"})
            self.assertFalse(uses_mover_readings(switched), mode)
        fresh = AppConfig(entry_mode="orb", mover_weight_volume="45")          # set on purpose, after the merge
        self.assertEqual(fresh.mover_weight_volume, D("45"))

    def test_an_unversioned_file_still_gets_its_one_time_retune(self) -> None:
        config = AppConfig(entry_mode="movers")
        self.assertNotIn("config_version", config.model_fields_set)


class MixedRuleTests(unittest.TestCase):
    def test_the_floor_on_a_mover_profile_is_set_from_the_score_it_buys_on(self) -> None:
        engine = movers_engine(reentry_score_boost="10")
        engine.config = engine.config.model_copy(update={"reentry_rule": "floor"})
        self.assertEqual(hold(engine), "")
        score = engine.strategy_state.entry_score["HOT"]
        self.assertGreater(score, D("60"))
        engine.record_reentry_floor("HOT", engine.snapshot("HOT"))
        self.assertEqual(engine.reentry_score_floors["HOT"], min(D("100"), score + D("10")))

    def test_the_climb_rule_keeps_its_new_high_part_without_the_mover_readings(self) -> None:
        engine = movers_engine()
        engine.config = AppConfig(use_top_volume_symbols=False, symbols=["HOT"], dry_run=False, reentry_rule="climb",
                                  reentry_score_boost="20", min_entry_score="40", use_trend_checks=False)
        engine.reentry_new_highs["HOT"] = ("s1", D("11.50"))
        self.assertEqual(engine.climbing_reentry_hold_reason("HOT", D("55"), engine.config, D("11.20")),
                         "Hold (re-entry needs 60 after a sale at a gain, until it trades above $11.50; score 55)")
        self.assertEqual(engine.climbing_reentry_hold_reason("HOT", D("60"), engine.config, D("11.20")), "")
        self.assertEqual(engine.climbing_reentry_hold_reason("HOT", D("45"), engine.config, D("11.60")), "")   # new high
        self.assertEqual(engine.reentry_new_highs, {})
