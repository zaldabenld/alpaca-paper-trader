# Full Code Audit - 2026-06-24

Scope: Full audit of the local Alpaca Paper Trader repo after live sizing/P-L display fixes. This log is append-only for this audit pass: each finding is recorded before moving to the next audit area.

Baseline:
- Repo: `C:\Users\solo leveling\Documents\alpaca trading app`
- Branch: `main`
- Current dirty files at audit start: `python_app/alpaca_desktop/engine.py`, `python_app/static/app.js`, `python_app/static/index.html`, untracked `.codex/build-notes/`
- Live backend before audit fixes: `http://127.0.0.1:8765`, PID `1724`, stale source stamp `1782247613039928700:12:403163`
- Current source stamp after local P/L display patch: `1782335558511740000:12:404109`
- Restart attempt failed because Windows denied stopping PID `1724`, including forced `taskkill /F`.

## Findings

### AUDIT-001 - Live backend can remain stale and protected from restart
Severity: High
Status: Open
Evidence:
- `python_app/run.py` detected stale source and attempted restart.
- Log: `Could not stop stale Alpaca Paper Trader backend pid 1724: [WinError 5] Access is denied`
- Forced `taskkill /F /PID 1724 /T` also returned `Access is denied`.
Impact:
- Code can be patched and verified locally while the running app still serves old backend code, making fixes look applied when they are not live.
- This directly caused confusion during the latest Daily P/L display fix.
Likely root cause:
- The live backend process is running under a process context this Codex shell cannot terminate, or it is parented/launched in a way that denies termination from this shell.
Fix direction:
- Add an explicit in-app/admin-safe restart path or launcher-owned process control that can replace the backend reliably.
- Add source-stamp mismatch warning in the UI/API health surface so stale runtime is visible immediately.

### AUDIT-002 - Daily P/L and Realized P/L surfaces are ambiguous
Severity: High
Status: Patched locally, not live because AUDIT-001 blocks restart
Evidence:
- Detailed `/api/state?account_id=...` showed nonzero daily dollar P/L:
  - Account 3: `$-0.04`
  - Account 2: `$-0.52`
  - Account 4: `$-0.53`
- Account-level `realized_pl_display` showed `$0.00`.
- Trade history rows contained realized sell P/L from prior market day, while `daily_realized_pl_summary()` filters by local current date.
Impact:
- User can reasonably interpret the visible zero card as "P/L for the day is zero" even when equity-based daily P/L is nonzero.
- The UI did not show daily P/L percent, making small dollar movements appear flat, especially on Account 4.
Likely root cause:
- `self.account` emitted `daily_pl` and `daily_pl_display` but no `daily_pl_pct` fields.
- UI had a `Daily P/L` dollar card and a separate `Realized P/L` card without enough context.
Fix direction:
- Emit `daily_pl_pct`, `daily_pl_pct_display`, and account-basis fields from backend.
- Render selected account and account-card Daily P/L as amount plus percent.
- Rename realized card to `Realized Today`.

### AUDIT-003 - Realized P/L summary is date-sensitive but the UI does not explain the date boundary
Severity: Medium
Status: Open
Evidence:
- `daily_realized_pl_summary()` filters sell rows where `sort_time` date equals `datetime.now().astimezone().date()`.
- On 2026-06-24, recent trade rows from 2026-06-23 still appear in trade history and have realized P/L, but account-level realized summary is `$0.00`.
Impact:
- After midnight or on closed-market days, the trade table can show realized winners/losers while the account-level realized card reads zero.
- This looks broken unless the UI clearly says "today" and/or provides the applicable trade date/session.
Likely root cause:
- Summary metric and trade table are using different time windows without labeling.
Fix direction:
- Make the realized metric label/session explicit and consider adding a selected session date or "last trading day" option.

### AUDIT-004 - Core backend and frontend are large monoliths with high patch-collision risk
Severity: High
Status: Open
Evidence:
- `python_app/alpaca_desktop/engine.py` is 4,856 lines.
- `python_app/static/app.js` is 1,716 lines.
- The same backend file owns account config, live Alpaca IO, strategy scanning, sizing, order submission, exits, trade-history formatting, P/L summaries, replay events, and manager orchestration.
- The same frontend file owns account form state, config serialization, profile handling, metrics rendering, dashboard rendering, table rendering/sorting, account cards, lookup, and action buttons.
Impact:
- Fixes land in shared code paths without narrow ownership boundaries.
- Regressions are hard to isolate because display, persistence, runtime, and trading behavior are coupled.
- This is a direct contributor to repeated "bandaid" patches.
Fix direction:
- Split into focused modules before merging more features:
  - backend account config/persistence
  - metrics/P-L calculations
  - strategy decision engine
  - order/exit management
  - API DTO/state builders
  - frontend state/config forms
  - frontend metrics/account cards
  - frontend table rendering

### AUDIT-005 - No dedicated automated test suite exists for critical account metrics and config behavior
Severity: High
Status: Open
Evidence:
- Repo inventory has no `tests/` directory and no test manifest.
- Current checks are compile/import smoke checks and ad hoc inline Python/JS syntax checks.
- Recent regressions affected trade sizing and P/L display, both of which should have been covered by deterministic tests.
Impact:
- A fix can pass compile and still break account metrics, UI text, or saved-config semantics.
- Every change requires manual live verification, which is fragile and slow.
Fix direction:
- Add a minimal deterministic test suite before broad refactors:
  - `AppConfig` sizing-mode normalization
  - daily P/L and daily P/L percent calculations
  - realized-today summary date handling
  - state/summary payload shape
  - frontend config serialization helpers and display-format helpers

### AUDIT-006 - Broad exception handling hides root causes in critical paths
Severity: High
Status: Open
Evidence:
- Static scan found broad `except Exception` handlers across:
  - `python_app/run.py`
  - `python_app/alpaca_desktop/engine.py`
  - `python_app/alpaca_desktop/server.py`
  - `python_app/alpaca_desktop/storage.py`
  - `python_app/alpaca_desktop/day_tape.py`
- Several handlers use `pass` or continue with degraded state.
- The launcher restart failure surfaced only in a log file and the app continued reusing the stale backend.
Impact:
- Real failures can be converted into stale state, zero/default displays, or silent data gaps.
- Operators see symptoms late instead of seeing the failing subsystem directly.
Fix direction:
- Replace broad catches in critical runtime, persistence, account refresh, and order paths with typed exceptions and structured health/error fields.
- Any fallback should emit a visible health event and be covered by tests.

### AUDIT-007 - Frontend uses uncoordinated polling loops that can race with user edits and render stale data
Severity: High
Status: Open
Evidence:
- `python_app/static/app.js` has:
  - `setInterval(loadState, 2000)`
  - `setInterval(loadDashboard, 5000)`
- State loading also occurs after account selection, apply parameters, reconnect stream, refresh buttons, and account-card clicks.
- Earlier UI symptoms were inconsistent with backend state until a reload/fresh tab.
Impact:
- Poll responses can arrive out of order and overwrite newer UI state.
- Account config form changes can be overwritten by background state refresh.
- The page can show stale or mixed account data under load or after backend restart.
Fix direction:
- Centralize frontend data fetching through a request coordinator with abort/sequence IDs.
- Separate read-only dashboard polling from editable account/config form state.
- Add visible stale-data/source-stamp health indicators.

### AUDIT-008 - Stale-instance recovery only handles wrong-port failures, not stale code on the expected port
Severity: High
Status: Open
Evidence:
- `python_app/static/app.js::recoverStaleInstance()` returns immediately when `window.location.port === preferredAppPort`.
- The latest failure had the app responding on `127.0.0.1:8765` while running an old source stamp.
- `python_app/run.py` can detect source-stamp mismatch, but the UI does not compare source stamps.
Impact:
- The app can be reachable, refreshed, and apparently healthy while still serving old backend code.
- UI/operator has no visible warning that code changes are not live.
Fix direction:
- Expose current backend `source_stamp`, PID, start time, and repo/source stamp through `/api/health`.
- Have the UI compare the served static/app stamp and backend stamp, then show a blocking stale-runtime warning when they differ.

### AUDIT-009 - Account state responses can render after the selected account has changed
Severity: High
Status: Open
Evidence:
- `loadState()` computes a suffix from the global `selectedAccountId`, fetches `/api/state`, then unconditionally calls `renderState(state)`.
- Account-card click and account-select change also mutate `selectedAccountId`, save drafts, call `/api/select-account`, and call `loadState()`.
- Background `setInterval(loadState, 2000)` can run concurrently with user-driven account changes.
Impact:
- An older `/api/state?account_id=...` response can render after a newer account selection.
- Metrics, positions, and config form can show mixed/stale account data.
Fix direction:
- Add a monotonically increasing request sequence or `AbortController` per state/dashboard request.
- In `renderState()`, reject responses whose selected account no longer matches the request context unless they are full global refreshes.

### AUDIT-010 - Backend trade sizing mode still relies on implicit defaults and caller behavior
Severity: High
Status: Open
Evidence:
- `AppConfig.max_trade_percent` defaults to `7.0`.
- `AppConfig.model_post_init()` treats a positive `max_trade_notional` plus positive/default `max_trade_percent` as a conflict and usually normalizes to percent mode for preset profiles.
- A dollar-only config is preserved only when the caller explicitly sends `max_trade_percent: 0`.
- The frontend currently does this, but backend API consumers, migrations, or partial config payloads can still be normalized unexpectedly.
- Direct check:
  - `AppConfig(profile='neutral', max_trade_notional='20')` -> `max_trade_notional=0`, `max_trade_percent=7.0`
  - `AppConfig(profile='neutral', max_trade_notional='20', max_trade_percent='0')` -> `max_trade_notional=20`, `max_trade_percent=0`
Impact:
- The same logical request, "use a $20 trade cap", behaves differently depending on whether the percent field is omitted or sent as zero.
- This is the same class of implicit-config behavior that caused Account 4 confusion.
Fix direction:
- Replace the two-field implicit mode with an explicit `trade_size_mode` enum (`percent`, `notional`, `exposure_slot`) plus one active value.
- Add migration code that is deterministic, logged, and test-covered.
- Reject conflicting payloads instead of silently guessing, except in a one-time labeled migration path.

### AUDIT-011 - Entry sizing blocks instead of downsizing when remaining exposure room is below planned slot size
Severity: Medium
Status: Open
Evidence:
- `planned_entry_notional_cap()` computes a planned slot cap from trade cap and exposure budget divided by max positions.
- `trade_notional()` then does:
  - `exposure_room = exposure_budget - total_exposure`
  - `if exposure_room < planned_cap: return Decimal("0")`
- It does not attempt `min(planned_cap, exposure_room)` when exposure room remains above the minimum entry notional.
Impact:
- Near the exposure cap, the app can refuse entries that still fit within the configured exposure limit.
- This can look like the app is "acting up" or undertrading even when there is allowed capacity left.
Fix direction:
- Compute a final candidate notional as `min(planned_cap, buying_power, exposure_room)` and only block when that final value is below minimum entry notional.
- Add tests for exposure-room edge cases.

### AUDIT-012 - Saved account load can silently drop invalid accounts
Severity: High
Status: Open
Evidence:
- `server.py::load_saved_settings_to_manager()` wraps each saved account parse in `try/except Exception: continue`.
- If one account has invalid config, bad encrypted credentials, or malformed saved data, that account is skipped with no visible health error.
Impact:
- An account can disappear from the running manager without a clear reason.
- Bad migrations can look like account/config drift rather than an actionable load error.
Fix direction:
- Preserve account shells even when config/credential parsing fails, attach a visible `settings_load_error`, and keep the raw account id/name.
- Add settings-load diagnostics to `/api/health` and the UI.
- Add tests for malformed account entries and credential decrypt failures.

### AUDIT-013 - Settings file corruption is silently treated as no settings
Severity: High
Status: Open
Evidence:
- `storage.py::load_settings()` catches all exceptions from reading/parsing `python-settings.json` and returns `{}`.
- `save_settings()` writes directly to the settings path without atomic temp-file replacement.
Impact:
- A corrupted, partially-written, or unreadable settings file can make the app boot as if no settings exist.
- The operator gets no visible "settings failed to load" warning.
- Direct writes increase the chance of corruption if the process is interrupted during save.
Fix direction:
- Load failures should return an explicit error object or raise a typed settings error that is surfaced in `/api/health`.
- Saves should be atomic: write temp file, flush, then replace.
- Keep timestamped backups before overwriting settings.

### AUDIT-014 - VBS launcher validates only that an instance is alive, not that it is current
Severity: High
Status: Open
Evidence:
- `Launch Alpaca Paper Trader.vbs::ActiveUrl()` reads `instance.json`, calls `/api/state`, and opens the URL if it responds.
- It does not compare source stamp, PID start time, or source path.
- The recent stale backend was alive on `127.0.0.1:8765`, so this launcher would reopen stale code.
Impact:
- Desktop launch can reinforce stale-runtime bugs by opening an old backend instead of forcing/recovering the updated app.
Fix direction:
- Move source-stamp/current-runtime checks into a formal `/api/health` endpoint and have the launcher consume it.
- If stale, show a visible error with PID and manual close instructions, or use a reliable restart path.

### AUDIT-015 - Accounts view requires more horizontal width than the layout breakpoint allows
Severity: High
Status: Open
Evidence:
- `python_app/static/styles.css` keeps the Accounts view in a two-column layout until `max-width: 980px`.
- The desktop layout combines a sidebar of `minmax(300px, 320px)`, an 18px gap, 36px layout padding, and a workspace whose `.metrics` grid requires six columns of at least 130px plus five 12px gaps.
- That means the page can require roughly 1,214px before accounting for table contents, while the responsive breakpoint does not collapse the layout until 980px.
- Several tables intentionally use `white-space: nowrap`, so the actual required width can be even larger.
Impact:
- Medium-width desktop windows can overflow horizontally.
- The user can be forced to pan the whole document with arrow keys instead of getting a stable app layout with local table scrolling.
- This matches the reported window resizing issue.
Fix direction:
- Collapse the account sidebar/workspace layout at a wider breakpoint or use container-based layout rules.
- Let metric cards wrap earlier, and keep horizontal scrolling inside table panels instead of the whole page.
- Add a Playwright or browser smoke check for narrow desktop widths such as 1024px and 1100px.

### AUDIT-016 - Daily P/L fields are overloaded between raw and display values
Severity: High
Status: Open
Evidence:
- In `python_app/alpaca_desktop/engine.py`, the selected account payload sets `account.daily_pl` to a raw decimal string and `account.daily_pl_display` to formatted currency.
- In `TraderEngine.summary()`, the account-card summary sets `daily_pl` to the formatted currency string and `daily_pl_raw` to the raw decimal string.
- In `python_app/static/app.js`, `dailyPlDisplay()` expects selected-account display fields, while `accountCardDailyPl()` expects summary display fields.
Impact:
- The same JSON key has different meanings depending on where it appears in the state response.
- UI patches can easily read the wrong field and show `$0.00`, omit the percent, or apply the wrong positive/negative class.
- This makes the P/L surface brittle and harder to test.
Fix direction:
- Standardize API contracts: raw numeric fields should consistently end in `_raw`, display strings should consistently end in `_display`, and percent display should consistently use `_pct_display`.
- Update the frontend helpers to consume only the standardized keys.
- Add contract tests for selected account payloads and account-card summaries.

### AUDIT-017 - Inverse ETF behavior has stale downturn code and stale documentation
Severity: Medium
Status: Open
Evidence:
- `TraderEngine.active_downturn_inverse_symbols()` now adds the bounded inverse ETF list whenever top-volume mode is active, or when `inverse_etf_mode` is `inverse_only`.
- `market_downturn_active()` and `downturn_inverse_allowed()` still exist but are not referenced by the current entry path.
- `README.md` and `readme.md` still describe inverse ETFs as temporarily scanned during broad SPY/QQQ downturns.
- `OPERATING.md` also still describes a bounded SPY/QQQ downturn overlay, while the current project instruction says not to add a separate inverse ETF downturn blocker and to let inverse ETFs pass the same selection parameters as any other symbol.
- The UI control is labeled only `Allow` / `Inverse only`, so the operator cannot tell from the UI that inverse ETFs are always added in top-volume mode.
Impact:
- The code and docs describe different strategy behavior.
- Future fixes can accidentally revive the old downturn blocker even though the current strategy constraint says inverse ETFs should pass or fail through the same selection parameters as other symbols.
Fix direction:
- Delete unused downturn-gate code or quarantine it behind a clearly labeled diagnostic.
- Update the README and UI label/help text to match the current strategy contract.
- Add a regression test proving inverse ETF eligibility is based on the normal entry-quality path, not a separate downturn predicate.

### AUDIT-018 - Shared market websocket subscribes only the first eligible account's symbols
Severity: High
Status: Open
Evidence:
- `TraderManager.market_data_symbols()` builds `ordered_engines` for all connected engines that use the market stream.
- It then loops through that list and returns as soon as the first engine has dashboard symbols.
- The returned `dashboard_symbols` and `bar_symbols` are the same first-account list, capped at `MARKET_STREAM_SYMBOL_LIMIT`.
- Other connected accounts' distinct symbol sets are not merged into the websocket subscription.
Impact:
- In a multi-account setup, accounts that are not the chosen stream source may miss live bar/quote/trade updates for symbols unique to their configuration.
- Their strategy snapshots can depend on slower historical refresh/backfill behavior while the UI implies one shared stream is covering all accounts.
- This can make accounts that are "wired the same" look inconsistent if one account has config drift or a different active universe.
Fix direction:
- Define a shared-stream subscription contract: either a true union across accounts within the symbol limit, or an explicit single-source dashboard mode that is labeled in the UI.
- Add a regression test with two connected accounts and different symbols to prove the subscribed bar symbols are correct.
- Surface stream source and subscribed symbol count per account in dashboard health.

### AUDIT-019 - Shared market websocket does not include held-position symbols
Severity: High
Status: Open
Evidence:
- `TraderEngine.scan_symbols()` includes `position_symbols_for_market_data()`, so the refresh path can evaluate held positions even when they are no longer in the entry universe.
- `TraderManager.market_data_symbols()` uses `engine.trading_symbols()` instead of `engine.scan_symbols()`.
- Therefore the shared websocket can omit symbols currently held by an account if those symbols fall out of the dashboard top-volume list or manual entry list.
Impact:
- Existing positions may not receive live bar updates through the shared stream.
- Exit/protection logic can become more dependent on periodic REST refreshes, making exits less timely and behavior less consistent across accounts.
Fix direction:
- Build stream bar symbols from each account's scan universe, including held positions, while keeping dashboard trade/quote symbols bounded and explicit.
- Add a regression test where a held symbol is not in the entry universe and verify it is still subscribed for bars.
- Separate "dashboard symbols" from "strategy/position bar symbols" in health output.

### AUDIT-020 - A legacy PowerShell trader remains in the launch path
Severity: High
Status: Open
Evidence:
- `Launch Alpaca Paper Trader.cmd` runs the Python app only if `.venv\Scripts\pythonw.exe` or `.venv\Scripts\python.exe` exists.
- If the virtualenv is missing, the same launcher falls back to `powershell.exe ... src\App.ps1`.
- `Launch Legacy PowerShell Trader.cmd` directly launches `src\App.ps1`.
- `README.md` and `readme.md` describe the PowerShell app as an available fallback.
Impact:
- There are two launchable trading applications in the repository with different code paths, UI behavior, config handling, and likely strategy behavior.
- An environment or shortcut issue can put the operator into the legacy app without a clear warning, making bugs appear fixed in one implementation but not the other.
- This undermines any claim that the Python app is the single live surface to harden before merging the backtester.
Fix direction:
- Remove the legacy fallback from the main launcher.
- Keep the PowerShell app only under an explicitly archived/legacy path, or delete it after preserving any needed reference material.
- Update README/OPERATING docs so the Python app is the only supported trading surface.
- Add a launcher smoke check that fails clearly if the Python virtualenv is missing.

### AUDIT-021 - Day-tape replay is analysis-only, not a backtester integration seam
Severity: High
Status: Open
Evidence:
- `scripts/day_tape_review.py` summarizes recorded event counts, holds, candidates, and warnings from JSONL day tapes.
- `scripts/day_tape_summary.py` only summarizes file-level counts.
- `scripts/day_tape_fast_forward.py` replays timing/counts and prints `Mode: event-flow fast-forward. The fake broker/profit simulator is the next layer.`
- None of the scripts execute the live strategy engine against a replay broker or produce simulated P/L.
Impact:
- The current replay tooling is useful for diagnostics, but it is not ready to merge as a robust backtester.
- Strategy changes can still diverge between live code, day-tape review scripts, and future backtest logic unless the engine has a tested replay boundary.
Fix direction:
- Define a backtester seam around market data, account state, order submission, fills, and clock behavior.
- Reuse the live strategy/account engine as much as possible instead of creating a parallel strategy implementation.
- Add deterministic fixture tapes and expected trade/P/L outputs before merging backtester UI.

## Ordered Remediation Plan

Rules for every step:
- Work in a new Codex worktree/branch, not the stable checkout.
- Keep `%LOCALAPPDATA%\AlpacaPaperTrader` untouched unless the user explicitly approves live remediation.
- Preserve credentials and never print account identifiers, API keys, secret keys, tokens, or DPAPI blobs.
- Add or update tests before changing risky behavior when practical.
- After each step, run compile/static checks and repeat the full audit list to confirm no previous finding regressed.
- Do not launch the next step until the current step is reviewed.

### Step 1 - Make Runtime Currentness Bulletproof
Target findings:
- `AUDIT-001`, `AUDIT-008`, `AUDIT-014`, `AUDIT-020`

Definition of done:
- The Python app exposes a health/currentness endpoint with source stamp, PID, source path, and stale/current status.
- `run.py`, the VBS launcher, and frontend recovery logic all use the same health/currentness contract.
- A stale backend on the expected port cannot silently be treated as healthy current code.
- The main launcher no longer falls back into the legacy PowerShell trading app.
- Missing virtualenv/dependency startup failures produce an explicit operator-visible error.
- Narrow tests or smoke checks cover source-stamp mismatch, stale instance reuse/failure, and launcher fallback behavior where feasible.

Coherent prompt for the new chat:
```
You are working on C:\Users\solo leveling\Documents\alpaca trading app in a new Codex worktree. Follow AGENTS.md exactly: this is a paper-trading, credential-adjacent project; do not touch the stable app data or saved credentials; do not start/stop the live backend unless explicitly approved. Your task is Step 1 from .codex/audits/2026-06-24-full-code-audit.md: make runtime currentness bulletproof.

Fix AUDIT-001, AUDIT-008, AUDIT-014, and AUDIT-020. Add a shared health/currentness contract so the backend, Python launcher, VBS launcher, and frontend recovery logic can tell whether the running process is serving the current source. The endpoint should expose source stamp, PID, URL/source path if safe, and current/stale status without exposing credentials or account ids. If a stale backend cannot be stopped from the current user context, the app should show a clear operator-visible stale-runtime warning instead of silently reusing it. Remove the main .cmd fallback into src\App.ps1; legacy PowerShell should not be in the normal app launch path. Keep any archived legacy files only if explicitly labeled as unsupported.

Add narrow tests or smoke checks for source-stamp mismatch/currentness logic and launcher behavior where practical. Run .\.venv\Scripts\python.exe -m compileall -q python_app, node --check python_app\static\app.js, and .\.codex\setup-worktree.ps1 -SmokeOnly with worktree-local LOCALAPPDATA. After the fix, rerun a focused audit against all findings in the audit log and report whether any previous finding regressed. Do not proceed to Step 2.
```

### Step 2 - Add Regression Harness Before Behavior Fixes
Target findings:
- `AUDIT-005`, plus test coverage for `AUDIT-002`, `AUDIT-003`, `AUDIT-010`, `AUDIT-011`, `AUDIT-012`, `AUDIT-013`, `AUDIT-016`, `AUDIT-018`, and `AUDIT-019`

Definition of done:
- A repo-local automated test command exists and is documented.
- Tests run without real Alpaca credentials or stable app data.
- Baseline tests cover config normalization, P/L payload contracts, realized-P/L date/session behavior, settings load/save errors, account-load failures, market-stream symbol selection, and held-position stream inclusion.

### Step 3 - Fix Account Metrics, Sizing Mode, and Settings Durability
Target findings:
- `AUDIT-002`, `AUDIT-003`, `AUDIT-010`, `AUDIT-011`, `AUDIT-012`, `AUDIT-013`, `AUDIT-016`

Definition of done:
- Daily P/L and realized-today metrics have unambiguous API fields and UI labels.
- Trade sizing uses an explicit mode and rejects conflicting percent/dollar payloads outside a labeled migration path.
- Account/settings load failures surface visibly instead of silently dropping accounts or wiping settings.
- Settings saves are atomic with backup/recovery behavior.

### Step 4 - Stabilize Frontend State and Layout
Target findings:
- `AUDIT-007`, `AUDIT-009`, `AUDIT-015`

Definition of done:
- Polling uses request sequencing or aborts so stale responses cannot overwrite selected-account state.
- Account switching cannot race with auto-save or background refresh.
- The UI fits normal desktop window widths without whole-page horizontal panning; wide tables scroll inside their own panels.
- Browser/screenshot checks cover at least 1024px, 1100px, and the default launcher size.

### Step 5 - Correct Market-Data Coverage and Strategy Drift
Target findings:
- `AUDIT-017`, `AUDIT-018`, `AUDIT-019`

Definition of done:
- Shared stream subscriptions are defined as either a tested union or a clearly labeled single-source mode.
- Held-position symbols are included in bar subscriptions.
- Inverse ETF code, docs, and UI agree with the current strategy contract.

### Step 6 - Split Monoliths and Prepare the Backtester Seam
Target findings:
- `AUDIT-004`, `AUDIT-006`, `AUDIT-021`

Definition of done:
- Backend responsibilities are split enough to isolate config, account state, market data, order execution, P/L, and replay/backtest interfaces.
- Broad exception handlers are replaced with typed/logged failures in critical paths.
- Backtester work has a concrete interface that reuses live strategy logic instead of copying strategy rules into a parallel simulator.

### Step 7 - Full Regression Audit and Live Deployment Plan
Target findings:
- All open findings.

Definition of done:
- The audit log is updated with status for every finding.
- All tests/checks pass in an isolated worktree.
- A live deployment plan is prepared that preserves running data collection, credentials, and saved settings.
- No live restart is performed without explicit user approval.

## Step 1 Implementation Notes

### 2026-06-24 - Step 1 confirmation: AUDIT-001
Status: Confirmed
Evidence:
- `python_app/run.py::active_instance_url()` detects `source_stamp` mismatch from `instance.json`, attempts `stop_instance()`, then prints `Stale backend did not stop cleanly; reusing existing instance.` when termination fails.
- This confirms a stale backend can still be silently reused from the operator's browser path if the process cannot be stopped.

### 2026-06-24 - Step 1 confirmation: AUDIT-008
Status: Confirmed
Evidence:
- `python_app/static/app.js::recoverStaleInstance()` returns `false` when the current page is already on port `8765`.
- The same function probes only `/api/state` on the preferred port, so a backend serving old source on the expected port is treated as normal.

### 2026-06-24 - Step 1 confirmation: AUDIT-014
Status: Confirmed
Evidence:
- `Launch Alpaca Paper Trader.vbs::ActiveUrl()` reads `instance.json`, then `IsAlive()` accepts an instance if `GET /api/state` returns any HTTP status under 500.
- The launcher does not validate a health/currentness contract before opening the app URL.

### 2026-06-24 - Step 1 confirmation: AUDIT-020
Status: Confirmed
Evidence:
- `Launch Alpaca Paper Trader.cmd` falls back to `powershell.exe ... src\App.ps1` when neither `.venv\Scripts\pythonw.exe` nor `.venv\Scripts\python.exe` exists.
- That keeps legacy PowerShell in the normal launch path when the Python virtualenv is missing.

### 2026-06-24 - Step 1 status update: AUDIT-001
Status: Fixed in `codex/alpaca-runtime-currentness`
Evidence:
- Added `python_app/alpaca_desktop/currentness.py` as the shared source-stamp/currentness contract.
- `python_app/run.py` now probes `/api/health`, requires matching `current`, `source_stamp`, and `source_path`, and refuses to reuse stale or different-source backends.
- If stale termination fails, `run.py` prints an explicit stale-runtime warning and starts a separate current instance instead of silently reusing the stale process.

### 2026-06-24 - Step 1 status update: AUDIT-008
Status: Fixed in `codex/alpaca-runtime-currentness`
Evidence:
- `python_app/static/app.js` now checks `/api/health` during startup and before state/dashboard polling.
- `recoverStaleInstance()` no longer returns early just because the browser is already on port `8765`; it requires preferred-port health to report `current: true`.
- Added a visible stale-runtime banner in `python_app/static/index.html` and `python_app/static/styles.css`.

### 2026-06-24 - Step 1 status update: AUDIT-014
Status: Fixed in `codex/alpaca-runtime-currentness`
Evidence:
- `Launch Alpaca Paper Trader.vbs` now uses `/api/health`, verifies `current: true`, and verifies the backend `source_path` matches this launcher folder's `python_app`.
- A stale or missing-health backend triggers an operator-visible warning with URL, PID if available, status, and source path, and is not reopened.
- The VBS launcher runs a hidden Python `--smoke` startup check and opens the command launcher if the virtualenv/dependencies fail.

### 2026-06-24 - Step 1 status update: AUDIT-020
Status: Fixed in `codex/alpaca-runtime-currentness`
Evidence:
- `Launch Alpaca Paper Trader.cmd` no longer references or launches `src\App.ps1`.
- Missing `.venv\Scripts\python.exe` now produces an explicit operator-visible virtualenv error and exits.
- `README.md` now describes the Python app as the supported launch surface and labels the legacy PowerShell launcher as unsupported reference material.

### 2026-06-24 - Step 1 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\test_runtime_currentness.py` passed: 5 tests.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
Regression review:
- AUDIT-001: Fixed; stale/current process reuse now depends on `/api/health` and matching source path/stamp.
- AUDIT-002: No regression observed; P/L calculation and rendering keys were not changed.
- AUDIT-003: No regression observed; realized-P/L date-boundary logic was not changed.
- AUDIT-004: No regression observed; no monolith split was attempted in Step 1.
- AUDIT-005: Improved narrowly for Step 1 only by adding `scripts/test_runtime_currentness.py`; broader test-suite finding remains open for Step 2.
- AUDIT-006: No regression observed; broad exception handling outside the launcher/currentness path was not changed.
- AUDIT-007: No regression observed; polling coordination was not refactored beyond adding health checks.
- AUDIT-008: Fixed; frontend recovery and polling now use `/api/health` and show stale-runtime warnings.
- AUDIT-009: No regression observed; selected-account response sequencing was not changed.
- AUDIT-010: No regression observed; sizing-mode/config normalization was not changed.
- AUDIT-011: No regression observed; exposure-room sizing behavior was not changed.
- AUDIT-012: No regression observed; saved-account load behavior was not changed.
- AUDIT-013: No regression observed; settings load/save behavior was not changed.
- AUDIT-014: Fixed; VBS launcher now validates `/api/health` currentness before opening a saved instance.
- AUDIT-015: No regression observed; layout breakpoints and table sizing were not changed except the new top-level runtime warning banner.
- AUDIT-016: No regression observed; P/L API contract fields were not changed.
- AUDIT-017: No regression observed; inverse ETF code and strategy docs were not changed in Step 1.
- AUDIT-018: No regression observed; shared market websocket symbol selection was not changed.
- AUDIT-019: No regression observed; held-position stream subscription behavior was not changed.
- AUDIT-020: Fixed; the main `.cmd` launcher no longer falls back to the legacy PowerShell trader and now errors visibly on missing Python virtualenv.
- AUDIT-021: No regression observed; day-tape/replay scripts were not changed except for adding an independent runtime-currentness regression script.
