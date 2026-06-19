# Alpaca Paper Trader

A local Windows desktop app for Alpaca paper trading. The primary app is now a Python/FastAPI desktop-launched web UI using Alpaca's official SDK. The original PowerShell/WPF app remains available as a fallback.

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

## Launch

Run:

```powershell
.\Create-DesktopShortcut.ps1
```

Then open **Alpaca Paper Trader** from your desktop.

You can also run `Launch Alpaca Paper Trader.cmd` directly from this folder.

The desktop shortcut uses a no-window launcher and opens the already-running app if one exists, which helps avoid accidental duplicate websocket sessions.

The legacy no-dependency app can be opened with `Launch Legacy PowerShell Trader.cmd`.

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

The **Dashboard** is the landing page. Once any account is connected, it shows Alpaca market status, the cached top-25 S&P 500 stocks by daily volume, a ticker lookup panel, and a trade-halt monitor for the subscribed dashboard symbols. The top-volume table can be sorted by clicking its column headers.

The top-volume list is ranked from S&P 500 stock snapshots and cached for 10 minutes to avoid unnecessary REST calls. After the list is seeded, the app subscribes to those 25 symbols over websocket for bars, quotes, trades, and trading-status updates. If SPY/QQQ show a broad intraday downturn, a small inverse ETF overlay can be added to the scan and stream universe. Buy/sell volume is classified live from trade price versus the latest quote; trades that cannot be classified land in **Other Vol**. Ticker lookup snapshots are fetched only when you press **Fetch** and are cached briefly.

By default, each account trades the dashboard top-25 S&P 500 volume symbols. During a broad SPY/QQQ selloff, the app can also scan a bounded inverse ETF watchlist (`SQQQ`, `SPXU`, `SDS`, `SH`, `TZA`) so the strategy has bearish-market candidates without replacing the S&P stock universe. The manual ticker list on the Accounts page is used as a fallback, or as the active universe when **Trade S&P 500 top 25** is unchecked.

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

The shared market-data websocket is intentionally app-level: one stream subscribes to the dashboard/top-volume symbols and each connected account consumes the same bar/quote/trade/status updates independently. The Dashboard shows stream status, symbol counts, last message age, reconnect count, and the latest stream/backfill error if one happens.

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
- It has an inverse ETF mode so inverse funds can be excluded from the normal bullish profile, allowed manually, used by an inverse-only profile, or temporarily scanned during a broad SPY/QQQ downturn.
- It uses market orders against the Alpaca paper endpoint.
- It keeps entries fractional and manages exits with fractional DAY stop/limit orders using the configured take-profit and stop-loss percentages.
- It classifies open orders as pending entries, strategy exits, protective exits, or manual/unknown orders so protective stop/limit orders do not count as new entries.
- It keeps an order-intent ledger so dry-run, submitted, and errored strategy orders can be matched back to the strategy reason and generated client order ID.
- It shows a position protection dashboard for held positions, including whether Alpaca currently has protective exits, strategy exits, or unknown/manual orders open.
- It can pause new entries inside the configured close-guard window before market close while still allowing existing-position exits.
- It sizes entries as one block using max trade dollars, max trade percent of equity, total exposure percent divided by max open positions, and buying power. It does not spend leftover scraps as tiny cleanup trades.
- Built-in profiles can be edited; once settings differ from the selected profile, the UI marks them as **Custom** and lets you save them as a reusable custom profile.

The **Replay** tab shows recent debug events and the JSONL replay file path under your Windows local app data folder. The replay log records market bars, trading-status events, stream/backfill events, and strategy order intents without writing API keys or secrets.

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

That fast-forward pass is the event-flow foundation. A fake broker/profit simulator can be layered on top of it once the tape has enough real market days.

Expected storage depends on market activity, how many symbols are streaming, and how many market-hours scan snapshots are recorded. The old replay logs are small, but a full day tape with trades and market-hours scan snapshots can be much larger. Recent local tapes have been roughly 1.5-2.6 GB per full trading day before closed-market scan suppression, so the 14-day default can still require tens of GB on active days. Run the summary command above after each new market day and lower `ALPACA_TRADER_DAY_TAPE_RETENTION_DAYS` if disk usage matters more than keeping a longer replay window.

The volume fields are also the foundation for a later automatic symbol source that can replace the manual ticker list with the top daily volume names.

No strategy guarantees profit. Paper test it before trusting any automation.

## Market Data Feed

The default feed is `iex`, which is usually available to free Alpaca accounts. If your account has SIP access, switch the feed to `sip`. If authentication fails for a data feed, switch back to `iex` or `delayed_sip`.

If Alpaca reports `connection limit exceeded`, another app or browser session is already using the market-data websocket for that key/feed. Close the other stream or wait for Alpaca to release it, then reconnect.
