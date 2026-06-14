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
- Do not add PDT guards, day-entry locks, day-exit locks, daily-loss stops, or risk-per-trade sizing back into the entry path for this version.
