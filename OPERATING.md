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
- Entry eligibility is intentionally narrow: price data ready, no existing long position, no pending/manual conflicting order, entries allowed by market/open/close guards, bullish short/long trend, RSI inside the configured buy range, positive configured-period momentum, positive longer/session momentum, positive session change from the day's first bar, price above session VWAP, SMI above the configured floor, relative volume passing the configured threshold, no active halt/status block, a fractionable/tradable Alpaca asset, and optional buy-flow confirmation when classified stream volume is available.
- Entry scoring combines RSI fit, relative volume, short momentum, longer/session momentum, session change, VWAP distance, SMI, ATR/volatility swing, and buy-flow ratio. A symbol must clear the configured minimum score before any buy order can be submitted.
- High trade volume must never override direction. A short-window bounce in an all-day loser is not a valid entry unless the broader session trend and VWAP relationship have also turned positive.
- Same-symbol re-entry is score based: after any strategy/protective exit is submitted or filled, that symbol must return with the configured score boost before it can be bought again. This is intended to stop same-day churn without adding blind PDT/cooldown logic.
- Filled exits, including broker/protective stop fills and take-profit/winner exits, also create the re-entry score boost.
- Inverse ETFs are controlled by the profile's inverse ETF mode: allow inverse ETFs only when Alpaca returns them in the current top-25 volume universe, exclude inverse ETF entries, or explicitly use the bounded inverse-only set. Do not add a separate SPY/QQQ downturn blocker; inverse ETFs must pass the same direction, VWAP, volume, score, and tradeability checks as other candidates.
- PDT guards, day-entry locks, day-exit locks, daily-loss stops, and risk-per-trade sizing must not be added back into the entry path for this version.
- Existing long positions are skipped by the entry path and handled only by the exit manager.
