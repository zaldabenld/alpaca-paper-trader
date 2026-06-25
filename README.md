# Alpaca Paper Trader

A local Windows desktop app for Alpaca paper trading. The supported app is a Python/FastAPI desktop-launched web UI using Alpaca's official SDK. The original PowerShell/WPF app is legacy reference material and is not launched as a fallback.

- `alpaca-py` for paper Trading API account, orders, positions, clock, and stock bars
- `alpaca.data.live.StockDataStream` for one app-level market-data websocket
- A dashboard landing page with market status, top-25-by-volume discovery, ticker lookup snapshots, and halt-status monitoring
- A configurable RSI/momentum/SMI/relative-volume/volatility strategy with paper-order execution, dry-run mode, fractional-first manual exit orders, close-guard entries, max trade size, total exposure, and max open positions
- Multiple paper accounts, each with its own credentials, profile, strategy state, REST trading client, logs, and trading controls
- Shared market-data websocket health, reconnect/backfill handling, order-intent logging, position protection status, and replay/debug events

This app is paper-only by design. Live account keys will not work against the paper endpoint.

## Installed Dependencies

Python 3.12 was installed user-local with `winget`. The project virtualenv is `.venv`.

To reinstall dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Tests

Run the isolated regression harness from a repo worktree:

```powershell
.\.venv\Scripts\python.exe scripts\run_regression_tests.py
```

The runner forces `LOCALAPPDATA` to `.runtime\localappdata`, disables auto-connect/auto-start, and does not require real Alpaca credentials. It includes runtime-currentness tests plus baseline tests for account metrics, sizing/config behavior, settings load/save behavior, and shared market-stream symbol selection. If a future audit adds a desired contract before the implementation is ready, the harness can mark it as an expected failure with the audit ID.

## Launch

Run:

```powershell
.\Create-DesktopShortcut.ps1
```

Then open **Alpaca Paper Trader** from your desktop.

You can also run `Launch Alpaca Paper Trader.cmd` directly from this folder. If the Python virtualenv is missing or dependencies fail to import, this launcher stops with an explicit error instead of opening the legacy PowerShell trader.

The desktop shortcut uses a no-window launcher and opens the already-running app if one exists, which helps avoid accidental duplicate websocket sessions.

To verify the existing desktop shortcut/VBS path without launching the app:

```powershell
.\.venv\Scripts\python.exe scripts\verify_desktop_shortcut.py
```

After an approved relaunch, run the sanitized live contract verifier:

```powershell
.\.venv\Scripts\python.exe scripts\verify_live_contract.py
```

It checks the desktop shortcut, current backend health, `instance.json`, account count, Daily P/L portfolio-history source fields, sizing-mode conflicts, top-volume source/cache, and runtime diagnostics without printing account IDs, account names, API keys, or secrets.

To verify rendered UI metric cards against `/api/state` without printing account identifiers:

```powershell
.\.venv\Scripts\python.exe scripts\verify_ui_display.py
```

To summarize the current contract status by acceptance category:

```powershell
.\.venv\Scripts\python.exe scripts\contract_status.py
```

For the full acceptance summary, including paper-only safety, market-data stream health, app-data preservation, audit/build-note evidence, account-switching/autosave guards, strategy selection/ranking invariants, layout evidence, regressions, and a bounded read-only day-tape backtest:

```powershell
.\.venv\Scripts\python.exe scripts\contract_status.py --include-regression --include-backtest
```

The aggregate backtest uses the latest bounded tape window by default so post-restart evidence is not hidden behind older same-day events. Use `--backtest-from-start` only for historical diagnostics.

For an approved live cutover, preview the coordinated backup/stop/shortcut-launch/verify sequence:

```powershell
.\.venv\Scripts\python.exe scripts\live_cutover.py
```

After approval, run the same command with `--execute`. Execute mode now checks saved `auto_start_trading` settings before stopping anything; if any saved account would auto-start paper trading, it aborts unless `--allow-auto-start` is supplied after that behavior is explicitly approved or `--disable-auto-start-for-launch` is used to set `ALPACA_TRADER_DISABLE_AUTO_START=1` only for this relaunch without changing saved account settings. The execute path backs up app data first, stops only this repo's `python_app\run.py` launcher processes, starts the desktop shortcut, then waits for `verify_live_contract.py` and `verify_ui_display.py` to pass. Its final aggregate status also includes layout evidence, focused strategy-selection contract tests, the isolated regression harness, and a bounded read-only `day_tape_backtest.py` replay category. If the live app, layout, strategy contract, and regression checks pass but the only remaining aggregate failure is missing fresh `alpaca_most_actives_volume` tape, the cutover reports deployment success while leaving full acceptance pending until a market-hours tape records the new source.

`Launch Legacy PowerShell Trader.cmd` is retained only as an unsupported legacy reference launcher.

Before an approved live restart or deployment, preview the local app-data backup:

```powershell
.\.venv\Scripts\python.exe scripts\pre_live_backup.py
```

After approval, run the same command with `--execute`. It copies the encrypted settings file, `instance.json`, dashboard cache, replay logs, and day-tape directory into `.runtime\pre-live-deploy-backups\<timestamp>` without printing credential contents.

## First Use

1. Open **Accounts**.
2. Enter your Alpaca paper API key and secret.
3. Leave **Dry run** enabled for the first session.
4. Choose a profile: **Conservative**, **Neutral**, or **Aggressive**.
5. Click **Connect**.
6. Configure the trading universe, market data feed, risk limits, and strategy parameters.
7. Click **Start Selected**.

If **Store encrypted for auto-connect** is checked, credentials are stored with Windows DPAPI for the current Windows user and the account connects automatically the next time the app starts. The browser UI does not receive saved key values back from the server; credential fields stay blank unless you enter replacement keys. If the box is unchecked, keys are kept only in the running app session.

Use **Connect this account on launch** to control auto-connect per saved account. Existing saved accounts default to connecting on launch unless you turn that off.

The **Dashboard** is the landing page. Once any account is connected, it shows Alpaca market status, the cached Alpaca top-25 most-active stocks by volume, a ticker lookup panel, and a trade-halt monitor for the subscribed dashboard symbols. The top-volume table can be sorted by clicking its column headers.

The top-volume list is pulled from Alpaca's most-actives screener and enriched with Alpaca snapshots, then refreshed on a short one-minute operational cache before account strategy scans. After the list is seeded, the app subscribes to the source dashboard symbols for trades and to a capped union of every connected market-stream account's scan and held-position symbols for bars and trading statuses. Buy/sell volume is classified live from trade price versus the latest quote; trades that cannot be classified land in **Other Vol**. Ticker lookup snapshots are fetched only when you press **Fetch** and are cached briefly.

By default, each account trades exactly the dashboard Alpaca top-25 volume symbols. In **Allow Alpaca top-25** mode, inverse ETFs are eligible only when Alpaca returns them in that current top-volume set, and they must pass the same direction, VWAP, volume, score, and tradeability checks as any other symbol. **Exclude inverse ETFs** blocks inverse ETF entries, and **Inverse set only** is the explicit override that scans the bounded inverse ETF set (`SQQQ`, `SPXU`, `SDS`, `SH`, `TZA`). The manual ticker list on the Accounts page is used as a fallback, or as the active universe when **Trade Alpaca top 25 volume** is unchecked.

## Operating Rules

See `OPERATING.md` for the short operating checklist that should guide future changes.

- Fractional trading is a core requirement. Small paper accounts must not be forced into whole-share trading just to simplify exit handling.
- Do not convert fractional entries to whole-share entries as an exit-strategy shortcut. If an exit feature conflicts with fractional trading, redesign the exit manager around fractional shares instead.
- For equities, Alpaca fractional market, limit, stop, and stop-limit orders are DAY-only. The app therefore uses app-managed fractional DAY exit orders and recreates missing protection while the app is running.
- Historical data must be preserved during strategy resets. Trade history, ledger rows, replay events, logs, and saved account/profile settings should remain intact unless the user explicitly asks to delete them.
- The **Purge Selected** action is the reset path: it stops auto trading, cancels open orders, submits fractional market liquidation orders for current positions, clears in-memory strategy guards/state, and leaves previous data available for review.

## Profiles and Multiple Accounts

Profiles set the main trading parameters:

- **Conservative**: smaller trade size and tighter exposure, with less brittle signal gates than before so it can still take high-quality candidates.
- **Neutral**: balanced defaults.
- **Aggressive**: larger trade size, wider exposure, looser volume confirmation.

You can still edit every parameter after applying a profile.

To test strategies concurrently:

1. Use **New** to create another account slot.
2. Name it for the setup you want to test, for example `Paper Aggressive`.
3. Enter that Alpaca paper account's keys.
4. Pick a profile and click **Connect**.
5. Click **Start Selected**.
6. Switch back to another connected account and start a different profile there.

Each account runs as a separate trading engine with its own Alpaca REST trading client. Stock market-data is shared through one app-level websocket and broadcast to each account strategy.

The shared market-data websocket is intentionally app-level: one source account owns the websocket, dashboard symbols drive trade-volume updates, and bar/status subscriptions are the capped union of every connected account's active scan symbols plus open-position symbols. Each connected account consumes those updates independently. The Dashboard shows stream status, symbol counts, last message age, reconnect count, and the latest stream/backfill error if one happens.

## Strategy

The included strategy is intentionally conservative and transparent:

- It calculates RSI from recent closes.
- It confirms direction with short/long trend, configured-period momentum, and SMI.
- It compares the current bar volume against average recent bar volume.
- It calculates volatility swing and ATR from recent bars.
- It checks Alpaca asset status so non-tradable or non-fractionable symbols are skipped before an order is attempted.
- It optionally uses classified buy/sell stream volume as confirmation when enough stream data exists.
- It scores the whole active symbol universe with RSI fit, relative volume, positive momentum, SMI, ATR/volatility, and buy-flow ratio.
- It requires the configured minimum entry score before a buy can be submitted.
- It sorts the eligible pool by score and buys the best candidates until max slots or block budget are full.
- It skips symbols already owned or already pending entry.
- It blocks same-symbol churn by requiring a higher score after an exit before that symbol can be re-entered.
- It has an inverse ETF mode so Alpaca-returned inverse ETFs can trade through the normal top-volume path, inverse ETF entries can be excluded, or an explicit inverse-only profile can use the bounded inverse set. There is no separate SPY/QQQ downturn gate; inverse ETFs pass or fail through the normal entry-quality checks.
- It uses market orders against the Alpaca paper endpoint.
- It keeps entries fractional and manages exits with fractional DAY stop/limit orders using the configured take-profit and stop-loss percentages.
- It classifies open orders as pending entries, strategy exits, protective exits, or manual/unknown orders so protective stop/limit orders do not count as new entries.
- It keeps an order-intent ledger so dry-run, submitted, and errored strategy orders can be matched back to the strategy reason and generated client order ID.
- It shows a position protection dashboard for held positions, including whether Alpaca currently has protective exits, strategy exits, or unknown/manual orders open.
- It can pause new entries inside the configured close-guard window before market close while still allowing existing-position exits.
- It sizes entries as one block using max trade dollars, max trade percent of equity, total exposure percent divided by max open positions, and buying power. It does not spend leftover scraps as tiny cleanup trades.
- Built-in profiles can be edited; once settings differ from the selected profile, the UI marks them as **Custom** and lets you save them as a reusable custom profile.

The **Replay** tab shows recent debug events and the JSONL replay file path under your Windows local app data folder. The replay log records market bars, trading-status events, stream/backfill events, and strategy order intents without writing API keys or secrets. It also includes a **Run Backtest** control for the local day tape; that path runs the same app-engine day-tape backtest used by `scripts/day_tape_backtest.py`, shows source/evaluation checks, accepted trades, and rejected-candidate samples, and does not submit orders or call Alpaca.

## Backtest Day Tape

The app also writes a local day tape for offline backtesting:

```text
%LOCALAPPDATA%\AlpacaPaperTrader\day-tape\tape-YYYYMMDD.jsonl
```

The day tape records data the app is already using: market bars, trades, quotes, trading-status events, top-volume dashboard snapshots, ticker lookups, order intents, stream/backfill events, and sanitized strategy scan snapshots with account balances, positions, open/closed orders, strategy rows, and live config. Full strategy scan snapshots are recorded only while Alpaca's market clock is open. It does not record API keys or secret keys, and it does not make extra Alpaca API calls.

By default, day-tape files are kept for 14 days. Set `ALPACA_TRADER_DAY_TAPE_RETENTION_DAYS` to change retention, or set `ALPACA_TRADER_DISABLE_DAY_TAPE=1` to disable tape writing.

To summarize local tape size:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_summary.py
```

To review strategy behavior and tape quality for the latest day:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_review.py --days 1
```

The reviewer groups scans by source profile/top-volume/dry-run labels and keeps sizing/capacity as source metadata, not strategy identity. It calls out source buckets that stayed flat all day, dominant hold reasons,
top-volume universe issues such as too many sub-$5 symbols, stream/top-volume errors,
parse errors, order-intent counts, and concrete follow-ups for the next tuning pass.

To fast-forward a week of tape without touching Alpaca:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_fast_forward.py --days 7
```

That fast-forward pass is the event-flow foundation. To run an offline app-engine backtest against the recorded top-volume universe and live strategy helpers:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_backtest.py --days 1
```

The backtest uses the recorded top-volume snapshots as the candidate universe, feeds recorded bars into the same `TraderEngine` strategy state, evaluates entries through the app-engine boundary, and reports accepted trades, rejected candidates, rejection reasons, and winner/loser indicator averages. It uses a fixed replay sizing harness: `$1000` equity/cash, 20 max positions, 5% per slot, and 100% total exposure. Add `--latest-events --max-events 50000` to inspect the latest bounded window of a large same-day tape. The full contract status requires replay evaluations from tape snapshots labeled `alpaca_most_actives_volume`; older `sp500_snapshot_volume` tape remains useful for diagnostics but does not satisfy the post-fix source contract.

Expected storage depends on market activity, how many symbols are streaming, and how many market-hours scan snapshots are recorded. The old replay logs are small, but a full day tape with trades and market-hours scan snapshots can be much larger. Recent local tapes have been roughly 1.5-2.6 GB per full trading day before closed-market scan suppression, so the 14-day default can still require tens of GB on active days. Run the summary command above after each new market day and lower `ALPACA_TRADER_DAY_TAPE_RETENTION_DAYS` if disk usage matters more than keeping a longer replay window.

No strategy guarantees profit. Paper test it before trusting any automation.

## Market Data Feed

The default feed is `iex`, which is usually available to free Alpaca accounts. If your account has SIP access, switch the feed to `sip`. If authentication fails for a data feed, switch back to `iex` or `delayed_sip`.

If Alpaca reports `connection limit exceeded`, another app or browser session is already using the market-data websocket for that key/feed. Close the other stream or wait for Alpaca to release it, then reconnect.
