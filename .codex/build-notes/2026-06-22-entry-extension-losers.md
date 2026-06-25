# 2026-06-22 Entry Extension Losers

Tags: alpaca-build-note, weekly-strategy-rollup, day-tape-20260622, entry-extension, min-pullback, vwap-extension, hot-rsi-smi

Scope: Read-only review of `tape-20260622.jsonl` for end-of-week strategy comparison. No Alpaca API calls, backend restarts, credential changes, sizing changes, or code changes were made during the review.

## Tape Health

- Events: 553,377
- Strategy scans: 12,796
- Order intents: 70
- Parse errors: 0
- Stream errors: 0
- Strategy scans were effectively confined to the June 22 regular session; only one scan landed just after 20:00 UTC.

## Finding

All 14 same-day pending entries closed red by the regular-session close. The symbols were HPE, F, TSLA, HPQ, and SQQQ across the active profile/capacity buckets.

The common pattern was not thin volume. These entries had acceptable relative volume and positive momentum, but they were bought into early-session extension before a meaningful pullback.

Entry traits:

- Session change was already strong, roughly +1.41% to +2.10%.
- Session pullback was tiny: F and HPQ 0.00%, TSLA 0.01%, SQQQ 0.20%, HPE 0.56%.
- Hot names were often near the top of the allowed RSI/SMI range: TSLA and HPQ had RSI about 64.6-67.5 and SMI about 95-96.
- None of the same-day entries reached the current 2.5% take-profit. TSLA peaked near +2.0%; most peaked around +0.3% to +1.0% before rolling over.

## Candidate Tweaks To Test

Start with stock-selection layer only, keeping sizing/capacity fixed.

1. Add a minimum pullback requirement before entry. The current hard gate blocks too much pullback, but not too little pullback. A `session_pullback >= 0.15%` gate would have blocked F, TSLA, and HPQ. A `session_pullback >= 0.25%` gate would also have blocked SQQQ.
2. Tighten max VWAP distance. A `max_vwap_distance <= 1.00%` filter would have blocked TSLA, HPQ, and SQQQ.
3. Tighten buy RSI max. A `buy_rsi_max <= 60` filter would have blocked HPE, TSLA, HPQ, and SQQQ.
4. Combined hypothesis for replay: reject early entries when `session_pullback < 0.15%`, or `vwap_distance > 1.00%`, or `rsi > 60`. On the June 22 tape this would have rejected all 14 red same-day entries.

## Code Pointers For Later

- Entry quality gate: `python_app/alpaca_desktop/engine.py`, `entry_quality_hold_reason`
- Entry score: `python_app/alpaca_desktop/engine.py`, `entry_score`
- Strategy snapshot fields: `python_app/alpaca_desktop/strategy.py`, `StrategySnapshot.as_row`

Note: trailing-profit controls are not currently a simple dashboard tweak. `AppConfig.model_post_init` forces `profit_trail_start_percent`, `profit_trail_drop_percent`, and `stop_loss_grace_minutes` back to zero.
