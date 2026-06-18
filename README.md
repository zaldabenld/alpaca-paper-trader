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
- It can tune recent momentum, long momentum, session trend, VWAP distance, max entry price, session/recent pullback, and late-momentum gates so paper runs can match offline replay candidates.
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
- It can pause new entries inside the configured close-guard window before market close while still allowing existing-position exits, and an optional exit guard can flatten app-managed positions near close for paper validation of intraday-only candidates.
- It sizes entries as one block using max trade dollars, max trade percent of equity, total exposure percent divided by max open positions, and buying power. It does not spend leftover scraps as tiny cleanup trades.
- Built-in profiles can be edited; once settings differ from the selected profile, the UI marks them as **Custom** and lets you save them as a reusable custom profile.

The **Replay** tab shows recent debug events and the JSONL replay file path under your Windows local app data folder. The replay log records market bars, trading-status events, stream/backfill events, and strategy order intents without writing API keys or secrets.

## Backtest Day Tape

The app also writes a local day tape for offline backtesting:

```text
%LOCALAPPDATA%\AlpacaPaperTrader\day-tape\tape-YYYYMMDD.jsonl
```

The day tape records data the app is already using: market bars, trades, quotes, trading-status events, top-volume dashboard snapshots, ticker lookups, order intents, stream/backfill events, and sanitized strategy scan snapshots with account balances, positions, open/closed orders, strategy rows, and live config. It does not record API keys or secret keys, and it does not make extra Alpaca API calls.

By default, day-tape files are kept for 14 days. Set `ALPACA_TRADER_DAY_TAPE_RETENTION_DAYS` to change retention, or set `ALPACA_TRADER_DISABLE_DAY_TAPE=1` to disable tape writing.

To summarize local tape size:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_summary.py
```

To review strategy behavior and tape quality for the latest day:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_review.py --days 1
```

The reviewer calls out strategy buckets that stayed flat all day, dominant hold reasons,
top-volume universe issues such as too many sub-$5 symbols, stream/top-volume errors,
parse errors, order-intent counts, and concrete follow-ups for the next tuning pass.

To fast-forward a week of tape without touching Alpaca:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_fast_forward.py --days 7
```

That fast-forward pass is the event-flow foundation. Use the fake broker simulator below once the tape has enough real market days.

To replay submitted order intents through a local fake broker and estimate P&L without touching Alpaca:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_simulator.py --days 2 --end-date 20260617
```

The simulator fills submitted market orders at the latest tape price, triggers sell stops at or below the recorded stop price, triggers sell limits at or above the recorded limit price, expires DAY exits when the recorded market clock closes, and reports realized P&L, unrealized P&L, win rate, expectancy, profit factor, exposure, drawdown, and drift versus the latest actual account snapshot. Use `--end-date YYYYMMDD` to exclude a current partial tape.

To sweep entry/exit rule candidates from recorded strategy indicators with an out-of-sample validation day:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_strategy_sweep.py --days 3 --validation-days 1
```

Use `--end-date YYYYMMDD` to lock research to completed tape days when a new partial tape has started, `--validation-date YYYYMMDD` to hold out a specific selected day, `--json-output .\reports\sweep.json` to persist the full result table, and `--fold-report-top 3` to print day-by-day metrics for the top candidates. `--candidate-mode research` derives entry thresholds from score-qualified training winners, `--exit-mode adaptive` tests trailing/profit-lock exits, `--candidate-contains NAME` narrows stress tests to a known candidate, `--max-hold-minutes N` tests an offline-only time exit, and `--liquidate-on-close` tests closing positions when the recorded market clock closes. The sweep starts each bucket flat from its first recorded equity, fixes replay capacity/sizing at 20 slots by default, recomputes candidate entries from recorded strategy rows, uses minute-bar high/low/close prices for conservative stop/target fills, and labels a candidate stable only when both train and validation windows have enough trades, positive P&L, acceptable profit factor, low drawdown, and no open positions.

To rank candidates across every selected tape day as its own fold:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_cross_validate.py --days 3 --end-date 20260617 --candidate-mode broad --exit-mode adaptive --liquidate-on-close --no-liquidate-at-end
```

The cross-validator reuses the same simulator, runs each selected tape file as a separate fold, and reports candidates that stay profitable, flat, and above the configured profit-factor/drawdown gates on every fold. Strategy replays default to `--simulation-max-positions 20 --simulation-sizing-positions 20` so candidate comparisons tune entry/exit logic instead of changing position capacity or trade size. The recommendation report also emits an `app_config_patch` for the top candidate so the paper engine can be set to the same entry and exit gates used offline.

To run manual weighted-selection simulations and append every result to a durable log:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_simulation_hub.py --init-template
.\.venv\Scripts\python.exe scripts\strategy_simulation_hub.py --config reports\manual\manual-strategy-template.json
```

The hub reads thresholds, feature weights, exits, slippage values, and fixed simulation assumptions from the JSON config. It recomputes the candidate score from recorded tape features when `score_weights` are present, then writes a full report under `reports\manual\` and appends summary rows to `reports\manual\simulation-runs.jsonl` and `reports\manual\simulation-runs.csv`. By default it uses completed day tapes only, excludes the current partial day unless `--allow-partial` is passed, and keeps simulations fixed at 20 max positions with 20-position exposure sizing. This is the preferred surface for comparing whether momentum, session trend, VWAP distance, SMI, volume, RSI fit, flow, volatility, or pullback penalties are moving P/L.

The default weighted template follows the current research direction: momentum and same-session direction are primary ranking signals, relative volume and VWAP/SMI are confirmation, RSI range is a smaller trend-consistency check, and pullback/extension features are penalties. Inverse ETF mode labeled **Downturn only** still waits for a broad SPY/QQQ downturn before adding the bounded inverse ETF list, rather than excluding those ETFs from bearish-market tests.

To use a local dashboard for manual replay runs:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_simulation_dashboard.py --port 8787 --open
```

The dashboard is localhost-only and runs replay jobs in the background through `strategy_simulation_hub.py`. It does not connect to Alpaca, change credentials, or alter saved account settings. Pick the strategy and exit from the selected config, or leave both set to all to test every candidate/exit combination in that file. Use the **Bar Screen** preset for fast candidate shortlisting, then the **Trade Validate** preset for trade-price replay at 5/10/15 bps. Dashboard job logs are stored in `reports\manual\dashboard-jobs\`.

To audit selected candidate reports for risk-adjusted paper-test readiness:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_risk_audit.py --candidate-report "reports\cv-max20.json::candidate_name" --portfolio-report reports\portfolio.json --target-slippage-bps 10 --markdown-output reports\strategy-risk-audit.md
```

The risk audit summarizes target-slippage P&L, fold consistency, drawdown, expectancy per buy, slippage survival, and evidence flags for thin samples. Use it after each new completed day before treating a candidate as more than provisional.

To rank candidate reports with one transparent profit-vs-risk score:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_candidate_scorecard.py --report "reports\cv-max20.json::aggressive max20" --report "reports\cv-max16.json::aggressive max16" --target-slippage-bps 10 --markdown-output reports\strategy-candidate-scorecard.md
```

The scorecard multiplies target-slippage P/L by fold consistency, sample-size credit, slippage cushion, capped profit factor, drawdown penalty, and hard gate pass/fail. It is an evaluation score only, not a trading parameter.

To audit whether a profitable candidate is too concentrated in one trade, one day, or same-day close liquidation:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_fragility_audit.py --diagnostics "reports\diag-max20.json::aggressive max20" --diagnostics "reports\diag-max16.json::aggressive max16" --include-portfolio --extra-bps-list 5,10 --markdown-output reports\strategy-fragility-audit.md
```

The fragility audit uses trade diagnostics ledgers and reports leave-best-trade-out P&L, leave-best-day-out P&L, close-liquidation contribution, and extra per-side bps cost stress. A candidate can be profitable and still remain only provisional if one trade or one day explains most of the result.

To quantify the statistical weakness of a small positive sample:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_confidence_audit.py --diagnostics "reports\diag-max20.json::aggressive max20" --diagnostics "reports\diag-max16.json::aggressive max16" --include-portfolio --iterations 10000 --markdown-output reports\strategy-confidence-audit.md
```

The confidence audit bootstraps observed trade exits and completed-day fold P/L. It reports positive-resample probability and lower-tail P/L. A candidate can pass replay but still show weak confidence when the trade sample is tiny or the lower tail crosses zero.

To quantify whether a selected candidate survives the number of parameter trials used to find it:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_selection_significance.py --candidate-report "reports\cv-max20.json::candidate_name::aggressive max20" --candidate-report "reports\cv-max16.json::candidate_name::aggressive max16" --portfolio-report "reports\portfolio.json::combined aggressive portfolio" --family-report reports\cv-max20.json --family-report reports\cv-max16.json --target-slippage-bps 10 --markdown-output reports\strategy-selection-significance.md
```

The selection significance audit uses an exact completed-day fold sign test and multiplies the raw p-value by the candidate/slippage trials in the search family. With only three completed tapes, even three positive folds are not statistical proof; this audit keeps profitable replay rows in the paper-test lane until more days arrive.

To explain why a selected parameter set differs from a nearby failed candidate:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_parameter_evidence.py --selected-diagnostics "reports\diag-max20.json::aggressive max20" --selected-diagnostics "reports\diag-max16.json::aggressive max16" --comparison-diagnostics "reports\diag-max16-failed-neighbor.json::failed neighbor" --markdown-output reports\strategy-parameter-evidence.md
```

The parameter evidence report compares trade-level entry features, selected-gate margins, and rejected comparison trades. Use it to document whether a threshold is supported by replay evidence or is still just a thin-sample assumption.

To run leave-one-day-out walk-forward selection, where each held-out tape day is tested using only candidates selected from the other days:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_walk_forward.py --days 3 --end-date 20260617 --candidate-mode pricebox --exit-mode fixed --bucket-contains "profile=aggressive, max_trade=50, max_positions=20" --slippage-bps 10 --price-source trades --liquidate-on-close --no-liquidate-at-end
```

Use walk-forward output to reject candidates that only look good after seeing every fold. A family that passes cross-validation but fails walk-forward should stay in research, not paper-test rollout.

To combine risk, walk-forward, and neighborhood reports into one promotion decision:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_promotion_gate.py --risk-report reports\strategy-risk-audit.md --walk-forward-report reports\walk-forward-max20.json --neighborhood-report reports\strategy-neighborhood-audit.json --fragility-report reports\strategy-fragility-audit.json --confidence-report reports\strategy-confidence-audit.json --target-slippage-bps 10 --markdown-output reports\promotion-gate.md
```

The promotion gate outputs `research only`, `config not aligned`, `paper-test provisional`, or `paper-test`. Thin day/trade counts, concentration flags, and weak confidence can still allow provisional paper testing, but any hard replay, fragility, confidence, or app-compatibility failure keeps the candidate in research, and any supplied config-alignment failure blocks readiness.

To regenerate the full current aggressive session-pricebox evidence bundle after a new completed tape day:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_validation_pipeline.py --end-date YYYYMMDD --days 4
```

Use `--dry-run` first to print the commands without running the heavy replay steps. The pipeline currently validates the `$300` / SMI50 / `0.30%` session-change candidate at a 15-second scan stress cadence. It requires `--end-date` so a partial current-day tape is not included by accident. It also includes a profit-vs-risk scorecard, trade diagnostics, failed-neighbor parameter evidence, fragility, confidence, app-compatibility, and config-alignment checks before the final promotion gate.

By default, the pipeline rejects today's tape because it can still be partial. Pass `--allow-partial` only for explicit research runs; promotion decisions should use completed prior dates.

To check whether a selected candidate is an isolated parameter hit or has nearby family support:

```powershell
.\.venv\Scripts\python.exe scripts\strategy_neighborhood_audit.py --report "reports\cv-max20-neighborhood.json::candidate_name" --markdown-output reports\strategy-neighborhood-audit.md
```

`day_tape_cross_validate.py --candidate-list` accepts a comma-separated list and can also be repeated, which is useful when testing a hand-picked neighborhood around one candidate.

Use `--price-source trades` to stress candidates against trade/quote-derived prices instead of minute bars, and `--min-stop-hold-minutes N` to test whether a short base-stop grace reduces immediate tick-noise exits. For focused failure analysis, emit the trade ledger for one candidate:

```powershell
.\.venv\Scripts\python.exe scripts\day_tape_trade_diagnostics.py --path "$env:LOCALAPPDATA\AlpacaPaperTrader\day-tape\tape-20260617.jsonl" --bucket-contains "profile=aggressive, max_trade=50, max_positions=20" --candidate "strict_trend_score_35|trail_1.5_0.75" --price-source trades --slippage-bps 5 --liquidate-on-close
```

Expected storage depends on scan frequency, market activity, and how many symbols are streaming. The old replay logs are small, but a full day tape with trades and quotes can be much larger. Budget roughly 5-10 GB for two weeks at first; after one full market day, run the summary command above and use the real number.

The volume fields are also the foundation for a later automatic symbol source that can replace the manual ticker list with the top daily volume names.

No strategy guarantees profit. Paper test it before trusting any automation.

## Market Data Feed

The default feed is `iex`, which is usually available to free Alpaca accounts. If your account has SIP access, switch the feed to `sip`. If authentication fails for a data feed, switch back to `iex` or `delayed_sip`.

If Alpaca reports `connection limit exceeded`, another app or browser session is already using the market-data websocket for that key/feed. Close the other stream or wait for Alpaca to release it, then reconnect.
