# Operating Notes

## Change Control

- Fix one user-visible issue at a time unless the user explicitly approves a broader scope.
- Use a Codex worktree for every bug fix, strategy change, replay/backtester change, websocket change, or risky refactor before touching the stable checkout.
- Define the acceptance proof before editing, including the authoritative source for the user-visible symptom.
- Acceptance proof must compare the app behavior to the authoritative source, not only to app-derived fields or cached UI state.
- Do not expand into adjacent contract, strategy, replay, launcher, or UI work without explicit approval.
- Do not restart or cut over the live backend until the focused fix passes in isolation and the restart path preserves the intended trading state.
- If the current task is blocked in one area, keep working on other approved parts of the same goal that are not blocked.

## Fractional-First Requirement

This app is designed for small Alpaca paper accounts where whole-share sizing is often not feasible. Fractional trading is a core product requirement, not an optional convenience.

- Do not force fractional entries into whole-share entries to simplify exit handling.
- Do not choose bracket/GTC-only approaches if they break fractional trading.
- If an Alpaca order feature conflicts with fractional shares, build the app logic around fractional shares instead.
- Equity fractional market, limit, stop, and stop-limit orders are DAY-only on Alpaca, so the app must manage fractional DAY exit orders and recreate missing protection while it is running.
- Alpaca holds the full fractional quantity for an open stop order, so a second full-quantity take-profit limit can be rejected as unavailable. Keep the stop live for loss protection, then when the profit threshold is reached, cancel the app stop and submit a fractional DAY limit sell to realize the gain.

## Strategy Reset

Use **Purge Selected** when strategy changes require a clean run:

- Stops auto trading for the selected account.
- Cancels open orders.
- Submits fractional market liquidation orders for current positions.
- Clears in-memory strategy state, entry/exit guards, and protective-order retry holds.
- Preserves trade history, ledger rows, replay events, logs, saved credentials, and saved profiles.

## Restart Behavior During Paper Testing

- `launch-alpaca-paper-trader.sh --install-service` installs a systemd user service that starts the backend at boot (the user has linger enabled, so no login is needed). Accounts with **Auto-connect** and **Auto-start trading** on then trade from the open without anyone opening the window. The desktop launcher uses the same service when it is installed for that checkout. To switch from an existing standalone instance, stop it and reopen the desktop app. The stop-protection timer still covers the case where the backend is not running.
- A backend configured for the n8n watchdog waits for the first successful heartbeat before making order changes. During an outage after the first reply, it keeps the last received halt state. The app header shows the watchdog status and whether it blocks order changes.

- Do not disable trading on restart unless the user explicitly asks to pause/stop trading or a change is dangerous to run immediately.
- When restarting the local app during active paper testing, preserve the previous trading state and restart selected accounts that were running before the restart.
- Do not launch with the auto-start override during normal trade-data collection.
- `scripts/live_cutover.py --execute` must not proceed past backup when saved accounts have `auto_start_trading` enabled unless the user explicitly approves `--allow-auto-start`.

## Entry Sizing and Duplicate Prevention

- A single strategy scan must not submit more than one entry for the same symbol.
- Account refresh/strategy execution must stay serialized per account so manual Start, background refresh, and post-purge refresh cannot overlap and double-submit entries.
- Entry sizing must honor one block-size calculation before quantity is calculated: max trade dollars, max trade percent of equity, total exposure percent divided across max open positions, and current buying power.
- Total exposure must be spread across the configured max open positions. For example, a 50% exposure cap with 10 max positions means about 5% equity per position, even if max trade is set higher.
- Do not spend leftover exposure scraps as new positions. If the account cannot afford the full current block, skip that symbol and wait for the next scan.
- Market-buy quantity should use a conservative buy reference price so wide spreads do not inflate share quantity.

## Core Strategy Logic

- The entry scan must analyze the whole active universe, score eligible symbols, sort by score, then buy the best candidates until slots or budget are full.
- Entry eligibility is intentionally narrow. The base conditions are price data ready, no existing long position, no pending/manual conflicting order, entries allowed by market/open/close guards, bullish short/long trend, positive session change from the day's first bar, price above session VWAP, no active halt/status block, and a fractionable/tradable Alpaca asset. The hard gates are: RSI inside the configured buy range (both the min and the max), momentum, recent momentum, and long momentum each at or above their configured floors, SMI at or above `min_smi`, relative volume passing the configured volume multiplier, session and recent pullback at or below their configured caps, the price still rising (`require_rising_price`: the last 1-minute bar closed at or above the one before it and the latest trade is not below that earlier close), and, when classified stream volume is available, a buy-flow ratio at or above `min_buy_volume_ratio`.
- Entry scoring combines RSI fit, relative volume, short momentum, longer/session momentum, session change, VWAP distance, SMI, ATR/volatility swing, and buy-flow ratio. A symbol must clear the configured minimum score before any buy order can be submitted.
- High trade volume must never override direction. A short-window bounce in an all-day loser is not a valid entry unless the broader session trend and VWAP relationship have also turned positive.
- Same-symbol re-entry is score based: after a losing exit or a stop-loss fill (including broker/protective stop fills), that symbol must return with the configured score boost before it can be bought again. Take-profit winners may re-enter through the normal checks. This is intended to stop same-day churn without adding blind PDT/cooldown logic. Movers mode uses the same Re-entry Boost setting on its own score, and it climbs: every losing round trip that day (counted from the broker's fills; a stop that fills in pieces is one loss, a winner adds nothing) adds the boost to Min Score. With Min Score 60 and a boost of 20 a stock needs 80 after one loss and 100 after two, and after a third it is not bought again that day. The count starts over each trading day and is rebuilt from the day's orders after a restart; 0 turns it off. A sale at a gain adds the same boost once, and only until the stock trades above the high it was sold from (the sale price plus `profit_trail_drop_percent`): the trailing stop sold it as falling from its high, so buying it straight back needs a stronger score. It is released by price, not by time: every refresh checks the bars since the sale, so a new high counts whatever the stock scored when it made it. Trend-hold inverse funds are exempt.
- Movers score, what takes points away: `mover_weight_spread` (default 40) comes off in proportion to the bid/ask spread as a share of the stop-loss percent, all of it when the spread is as wide as the stop. The spread is the quote read just before an order (kept ten minutes) and never less than one price tick. It is a weight, not a price or liquidity cut-off; 0 turns it off. With `mover_volume_current` on (default), volume points use the lower of today's volume so far and the last half hour's, each against the stock's usual, so a single block print does not hold full volume points all day.
- Day totals come from the whole session. The broker's regular order read is only the newest 100 closed orders; the app keeps every fill it has seen in the session, and reads the whole session back at its start, after a restart, and whenever an order that was open at the last refresh has closed without showing in that list (Alpaca lists closed orders by when they were submitted, so a stop placed hours earlier can fill out of sight). A failed read is retried each minute. Per-symbol buy counts (`inverse_trend_max_entries`, `max_entries_per_symbol_per_day`), the movers losing-exit count, the trade table's cost basis and Realized P/L all use that full list. The table still shows the newest 100 rows.
- A protective stop that has started filling is left alone until it finishes. Its size no longer matches the position once part of it has filled, and that is not a reason to cancel it.
- Entry pacing spreads out the burst of buys when a guard lifts: `max_entries_per_scan` caps how many new buys one scan may open (default 0 = off; opt-in), and `entry_spacing_seconds` blocks any new buy within that many seconds of the last one sent (default 0 = off; it is a timed lock on the entry path, so it is opt-in).
- Inverse ETFs are controlled by the profile's inverse ETF mode: allow mode scans the profile's bounded inverse set (default `SQQQ`, `SPXU`, `SDS`, `SH`, `TZA`; only known inverse ETFs are accepted) alongside the top-volume universe, exclude inverse ETF entries, or explicitly use the bounded inverse-only set. Do not add a separate SPY/QQQ downturn blocker; inverse ETFs must pass the same direction, VWAP, volume, score, and tradeability checks as other candidates.
- PDT guards, day-entry locks, day-exit locks, daily-loss stops, and risk-per-trade sizing must not be added back into the entry path for this version.
- Existing long positions are skipped by the entry path and handled only by the exit manager.
- The protective stop for a held position starts at the stop-loss percent below entry, moves up to the entry price once the position has gained `breakeven_at_percent`, and trails `profit_trail_drop_percent` below the peak (in 0.25% steps, rounded down to a valid price so the stop is never tighter than the setting) once it has gained `profit_trail_start_percent`. A live stop is replaced only to raise it; a stop at or above entry is never lowered. The peak is in memory, so after a restart it is rebuilt from the live app stop; over a weekend (DAY stops expire) trailing resumes from the current price, which means less protection, never a lowered stop. With `take_profit_percent` at 0 the trailing stop is the only profit exit. A stop that fills above entry counts as a winner for re-entry purposes.
