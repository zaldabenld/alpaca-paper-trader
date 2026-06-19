# Agent Instructions

This is a local Windows Alpaca paper-trading app. Treat it as a trading and credential-adjacent project even when it is running in paper mode.

## Safety Rules

- Never start live trading. This app is intended for Alpaca paper trading only.
- Never start, restart, or stop the local backend while the user is actively collecting trade data unless the user explicitly approves it.
- Never change saved Alpaca credentials or Windows local app data without explicit approval.
- Never print, copy, commit, or otherwise expose API keys, secret keys, tokens, DPAPI-protected credential blobs, or account identifiers.
- Ask before changing account sizing, max trade dollars, max notional exposure, total exposure, max open positions, auto-connect, or auto-start behavior.
- Use replay, smoke, synthetic, or dry-run checks before any market-connected test.

## Worktree Rules

- The local checkout is the stable/live checkout.
- Use Codex worktrees for experiments, bug fixes, strategy math changes, websocket work, and risky refactors.
- Do not use the stable local checkout for experimental strategy changes.
- Keep one branch/worktree per task, with branch names like `codex/alpaca-vwap-direction-filter`.
- If a worktree needs app data, set `LOCALAPPDATA` to a worktree-local path such as `$PWD\.runtime\localappdata`.
- Do not reuse the real `%LOCALAPPDATA%\AlpacaPaperTrader` settings from worktrees.

## Project Commands

- Set up a worktree environment: `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1`
- Run an import smoke check: `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly`
- Compile Python sources: `.\.venv\Scripts\python.exe -m compileall -q python_app`
- Launch isolated for manual testing only: set `$env:LOCALAPPDATA="$PWD\.runtime\localappdata"` and run `.\.venv\Scripts\python.exe python_app\run.py --no-browser --port 0`

## Strategy Constraints

- Preserve fractional-first behavior.
- Do not convert fractional entries to whole-share entries as an exit shortcut.
- Preserve historical data during strategy resets unless the user explicitly asks to delete it.
- Keep strategy execution serialized per account to avoid duplicate entries.
- High trade volume must not override direction, session trend, or VWAP requirements.
- Stock selection must be independent of share price, account size, buying power, max trade dollars, exposure, and max open positions. Those values may only control quantity, sizing, and capacity after the trade engine has ranked candidates.
- Do not add or tune min/max share-price gates, max-entry-price filters, account-size filters, or max-position filters as strategy variables unless the user explicitly asks for a separate diagnostic.
- Simulator strategy searches may only vary the stock-selection layer: movement, trend/session direction, VWAP/extension, pullback, volume/liquidity/flow, volatility/chop, SMI/RSI confirmation, inverse ETF regime behavior, and exits.
- Do not add a separate inverse ETF downturn blocker. Inverse ETFs should be eligible when they pass the same stock-selection parameters as any other symbol; that eligibility is the downturn signal for this strategy.
- Keep the simulator sizing/capacity layer as a base default for strategy comparisons. Default replay assumptions are one consolidated market-feed bucket, one standard replay account, `$1000` starting equity, `$1000` starting cash, 20 max positions, 20 sizing slots, 5% per slot, and 100% total exposure; account size, buying power, trade dollars, exposure, max positions, and share price are test-harness/sizing inputs, not knobs to optimize for what to buy.
- Scan cadence (`poll_seconds`) is an operational refresh setting, not a strategy/profile comparison variable. Keep built-in profiles on the same 5-second default unless the user explicitly requests a separate API-limit or infrastructure diagnostic.
- Day-tape `strategy_scan` snapshots should only be recorded while Alpaca's market clock is open; closed-market refreshes must not keep writing full scan snapshots unless the user explicitly asks for that diagnostic.
- Historical account/profile buckets are source data only. Do not report them as separate strategy simulations unless the user explicitly asks for a labeled diagnostic after trade-engine testing.
- If a sizing, exposure, max-position, or share-price experiment is ever needed, run it as a clearly labeled separate diagnostic after the selected strategy is fixed.
- Do not add PDT guards, day-entry locks, day-exit locks, daily-loss stops, or risk-per-trade sizing back into the entry path for this version.
