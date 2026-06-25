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

## Step 2 Coordinator Notes

### 2026-06-24 - Coordinator finding: STEP2-COORD-001 wrong checkout edits
Status: Confirmed
Evidence:
- Step 2 child thread `019efb99-1f5f-77f3-a49f-ccaf537f74f4` was created from the saved project context with instructions to work in `C:\Users\solo leveling\Documents\alpaca-regression-harness`.
- Coordinator polling found `C:\Users\solo leveling\Documents\alpaca-regression-harness` still clean while `C:\Users\solo leveling\Documents\alpaca trading app` had new Step 2 harness changes: modified `.codex/README.md` and `README.md`, plus untracked `scripts/run_regression_tests.py` and `tests/`.
- This violated the worktree-only boundary and repeated the prior failure mode where a child session followed the saved project cwd instead of the requested worktree path.
Action:
- Interrupt or steer the child before accepting any Step 2 work.
- Recover only confirmed child-created harness changes into the Step 2 worktree, and do not revert unrelated stable checkout changes.
- For future child sessions, do not rely on a prompt-only worktree redirect when a thread starts in the saved project context.

### 2026-06-24 - Coordinator finding: STEP2-COORD-002 handoff moved stable dirty state
Status: Confirmed
Evidence:
- To interrupt the wrong-checkout Step 2 child, the coordinator used `handoff_thread` on thread `019efb99-1f5f-77f3-a49f-ccaf537f74f4`.
- The handoff completed to `C:\Users\solo leveling\.codex\worktrees\adf2\alpaca trading app` on branch `codex/add-regression-harness`.
- After handoff, the stable checkout `C:\Users\solo leveling\Documents\alpaca trading app` became clean, while the temporary Codex worktree contained the pre-existing stable dirty files: `python_app/alpaca_desktop/engine.py`, `python_app/static/app.js`, `python_app/static/index.html`, `.codex/audits/`, and `.codex/build-notes/`.
Impact:
- The coordinator interruption changed stable checkout state while trying to stop a child-session drift.
Action:
- Restore the pre-existing stable dirty state from the handoff stash/worktree without reintroducing the misplaced Step 2 harness files into stable.
- Move forward only after stable, the intended Step 2 worktree, and the temporary handoff worktree are inventoried.

## Step 2 Baseline Confirmation Notes

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-005
Status: Confirmed
Evidence:
- Repo-local inventory before Step 2 had no `tests/` directory and no consolidated automated test runner.
- Existing automated coverage was limited to `scripts/test_runtime_currentness.py`, added in Step 1 for AUDIT-001/AUDIT-008/AUDIT-014/AUDIT-020 only.
Step 2 harness note:
- A repo-local regression command will be added before behavior fixes.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-002
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/engine.py::refresh()` stores selected-account `daily_pl` and `daily_pl_display`, but no daily P/L percent fields.
- `python_app/static/app.js::renderState()` renders only `account.daily_pl_display` for the selected account Daily P/L metric.
- Realized P/L still renders as a separate `realized_pl`/`realized_pl_pct_display` metric, which can visually disagree with equity-based daily P/L.
Step 2 harness note:
- Baseline tests will cover the current selected-account daily P/L payload shape and mark the missing daily P/L percent contract as expected-failing.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-003
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/engine.py::daily_realized_pl_summary()` derives `today` from `datetime.now().astimezone().date()`.
- The function includes only sell rows whose `sort_time` resolves to that local date, with no explicit session date in the returned payload.
Step 2 harness note:
- Baseline tests will cover current-date sell inclusion and prior-date sell exclusion.

### 2026-06-24 - Step 2 baseline verification note: AUDIT-010
Status: Confirmed, with stale-detail correction
Evidence:
- `python_app/alpaca_desktop/engine.py::AppConfig` still has independent `max_trade_notional` and `max_trade_percent` fields and no explicit `trade_size_mode`.
- Current code verification shows `AppConfig(profile="neutral", max_trade_notional="20")` preserves `max_trade_notional=20` and default `max_trade_percent=7.0`, leaving both caps active.
- This differs from the earlier audit note that said the notional value normalized to zero. The underlying gap remains: dollar-only intent depends on caller behavior, and conflicting sizing fields are accepted instead of rejected or migrated through an explicit mode.
Step 2 harness note:
- Baseline tests will pin the current implicit-conflict behavior and mark rejection of conflicting sizing fields as expected-failing.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-011
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/engine.py::trade_notional()` returns `Decimal("0")` when `exposure_room < planned_cap`.
- The current code does not try `min(planned_cap, exposure_room)` even when the remaining exposure room is above the minimum entry notional.
Step 2 harness note:
- A baseline test will assert the desired downsize behavior and mark it expected-failing until Step 3.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-012
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/server.py::load_saved_settings_to_manager()` catches all exceptions while parsing each saved account and then `continue`s.
- The invalid account is not preserved as a visible shell with a settings-load error.
Step 2 harness note:
- Baseline tests will pin current invalid-account drop behavior and mark visible preservation of invalid accounts as expected-failing.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-013
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/storage.py::load_settings()` catches all exceptions from reading/parsing `python-settings.json` and returns `{}`.
- `python_app/alpaca_desktop/storage.py::save_settings()` writes JSON directly to `SETTINGS_PATH` with no temp-file replace or backup path.
Step 2 harness note:
- Baseline tests will mark corrupt-settings load error surfacing as expected-failing and verify save write errors still propagate.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-016
Status: Confirmed
Evidence:
- Selected-account payloads use `account.daily_pl` for the raw value and `account.daily_pl_display` for display.
- Account-card summaries use `summary.daily_pl` for the formatted display string and `summary.daily_pl_raw` for the raw value.
- `python_app/static/app.js` consumes those two shapes through separate rendering paths.
Step 2 harness note:
- Baseline tests will pin the current overloaded contract and mark a standardized raw/display/percent contract as expected-failing.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-018
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/engine.py::TraderManager.market_data_symbols()` builds eligible connected engines but returns as soon as the first eligible engine yields dashboard symbols.
- It uses only that engine's `trading_symbols()` for both dashboard and bar subscriptions.
Step 2 harness note:
- Baseline tests will pin current first-account-only behavior and mark unioned bar-symbol coverage as expected-failing.

### 2026-06-24 - Step 2 baseline confirmation: AUDIT-019
Status: Confirmed
Evidence:
- `python_app/alpaca_desktop/engine.py::TraderEngine.scan_symbols()` merges `trading_symbols()` with `position_symbols_for_market_data()`.
- `python_app/alpaca_desktop/engine.py::TraderManager.market_data_symbols()` calls `engine.trading_symbols()` instead of `engine.scan_symbols()`, so held positions can be omitted from shared bar subscriptions.
Step 2 harness note:
- Baseline tests will prove held symbols are present in `scan_symbols()` but absent from current market-stream bar symbols, with the desired inclusion marked expected-failing.

## Step 2 Implementation Notes

### 2026-06-24 - Step 2 status update: AUDIT-005
Status: Fixed in `codex/alpaca-regression-harness-v2`
Evidence:
- Added repo-local regression runner `scripts/run_regression_tests.py`.
- Added baseline unittest coverage in `tests/test_regression_baselines.py` and shared test helper `tests/helpers.py`.
- The runner forces `LOCALAPPDATA` to `.runtime\localappdata`, disables auto-connect/auto-start, and requires no real Alpaca credentials.
- The runner includes the existing Step 1 runtime-currentness tests from `scripts/test_runtime_currentness.py`.
- Documented the command in `README.md` and `.codex/README.md`: `.\.venv\Scripts\python.exe scripts\run_regression_tests.py`.

### 2026-06-24 - Step 2 baseline coverage update: AUDIT-002, AUDIT-003, AUDIT-010, AUDIT-011, AUDIT-012, AUDIT-013, AUDIT-016, AUDIT-018, AUDIT-019
Status: Baseline covered; business behavior intentionally left open for later steps
Evidence:
- AUDIT-002/AUDIT-016: `ProfitLossContractBaselineTests` pins the current selected-account and account-summary Daily P/L payload shapes, and marks the standardized raw/display/percent contract expected-failing.
- AUDIT-003: `ProfitLossContractBaselineTests` pins current-date realized-sell inclusion and prior-date exclusion, and marks explicit session/date exposure expected-failing.
- AUDIT-010: `ConfigAndSizingBaselineTests` pins the current implicit sizing-field conflict behavior and marks explicit `trade_size_mode` conflict rejection expected-failing.
- AUDIT-011: `ConfigAndSizingBaselineTests` pins current exposure-room blocking and marks downsizing to remaining exposure room expected-failing.
- AUDIT-012: `SettingsBaselineTests` pins current invalid saved-account drop behavior and marks visible invalid-account shell preservation expected-failing.
- AUDIT-013: `SettingsBaselineTests` pins corrupt settings loading as `{}` and save write-error propagation, and marks visible corrupt-settings load error surfacing expected-failing.
- AUDIT-018: `MarketStreamBaselineTests` pins current first-eligible-account stream symbol selection and marks unioned connected-account bar symbols expected-failing.
- AUDIT-019: `MarketStreamBaselineTests` proves held symbols are included in `scan_symbols()` but omitted from current shared stream bar symbols, and marks held-symbol bar inclusion expected-failing.
Expected-failing future contracts:
- `test_desired_daily_pl_contract_has_standard_raw_display_and_percent_fields` - AUDIT-002/AUDIT-016
- `test_desired_daily_realized_summary_exposes_session_date` - AUDIT-003
- `test_desired_trade_size_mode_rejects_conflicting_caps` - AUDIT-010
- `test_desired_trade_notional_downsizes_to_remaining_exposure_room` - AUDIT-011
- `test_desired_saved_account_parse_failure_preserves_visible_shell` - AUDIT-012
- `test_desired_corrupt_settings_load_surfaces_error` - AUDIT-013
- `test_desired_market_stream_symbols_union_connected_accounts` - AUDIT-018
- `test_desired_market_stream_bars_include_held_position_symbols` - AUDIT-019
Harness-discovered changes from baseline:
- None. Current behavior matched the Step 2 baseline confirmations.

### 2026-06-24 - Step 2 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 22 tests, with 8 expected failures for documented future contracts.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices for edited text files.
Regression review:
- AUDIT-001: No regression observed; runtime currentness code was not changed.
- AUDIT-002: No regression observed; baseline contract coverage added, behavior intentionally unchanged.
- AUDIT-003: No regression observed; baseline date-boundary coverage added, behavior intentionally unchanged.
- AUDIT-004: No regression observed; no monolith split or production refactor was attempted.
- AUDIT-005: Fixed for Step 2; repo-local regression harness now exists and is documented.
- AUDIT-006: No regression observed; broad exception handling was not changed.
- AUDIT-007: No regression observed; frontend polling behavior was not changed.
- AUDIT-008: No regression observed; Step 1 currentness behavior was not changed.
- AUDIT-009: No regression observed; selected-account response sequencing was not changed.
- AUDIT-010: No regression observed; baseline sizing-conflict coverage added, behavior intentionally unchanged.
- AUDIT-011: No regression observed; baseline exposure-room coverage added, behavior intentionally unchanged.
- AUDIT-012: No regression observed; baseline saved-account-load failure coverage added, behavior intentionally unchanged.
- AUDIT-013: No regression observed; baseline settings load/save error coverage added, behavior intentionally unchanged.
- AUDIT-014: No regression observed; VBS launcher currentness behavior was not changed.
- AUDIT-015: No regression observed; layout/CSS was not changed.
- AUDIT-016: No regression observed; baseline P/L field-overload coverage added, behavior intentionally unchanged.
- AUDIT-017: No regression observed; inverse ETF code/docs were not changed.
- AUDIT-018: No regression observed; baseline first-account stream selection coverage added, behavior intentionally unchanged.
- AUDIT-019: No regression observed; baseline held-position stream omission coverage added, behavior intentionally unchanged.
- AUDIT-020: No regression observed; Step 1 launcher fallback behavior was not changed.
- AUDIT-021: No regression observed; day-tape/replay behavior was not changed.
Conclusion:
- No previous finding regressed in Step 2.

## Step 3 Implementation Notes

### 2026-06-24 - Step 3 status update: AUDIT-002, AUDIT-016
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- Selected-account state and account-card summaries now expose standardized Daily P/L fields: `daily_pl_raw`, `daily_pl_display`, `daily_pl_pct_raw`, `daily_pl_pct_display`, `daily_pl_account_basis_raw`, `daily_pl_account_basis_display`, and `daily_pl_session_date`.
- The legacy `daily_pl` alias is now a display string consistently across selected-account and summary payloads, while frontend rendering consumes the explicit raw/display/percent keys.
- The UI now labels the card `Daily P/L (equity)` and renders amount plus percent for the selected account and account cards.
- Regression coverage converted the AUDIT-002/AUDIT-016 expected-failing contract into passing tests.

### 2026-06-24 - Step 3 status update: AUDIT-003
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- `daily_realized_pl_summary()` now returns `session_date` for the local date boundary used to include/exclude sell rows.
- The UI label now says `Realized Today`, with the session date rendered under the metric.
- Regression coverage now asserts that the realized-today summary exposes the session/date boundary.

### 2026-06-24 - Step 3 status update: AUDIT-010
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- `AppConfig` now has explicit `trade_size_mode` values: `percent`, `notional`, and `exposure_slot`.
- Explicit conflicting percent/dollar payloads are rejected. Legacy one-cap payloads are normalized to an explicit mode, and saved-settings legacy conflicts can migrate through the labeled `trade_size_migration` field.
- Built-in profiles and the frontend default config now use percent mode with `max_trade_notional=0`.
- The account form now sends exactly one active trade cap according to the selected trade-size mode.

### 2026-06-24 - Step 3 status update: AUDIT-011
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- `trade_notional()` now computes final notional as the planned cap downsized by buying power and remaining exposure room.
- The entry is blocked only when the final notional is below `MIN_ENTRY_NOTIONAL`.
- Regression coverage now proves a `$75` remaining exposure room can produce a `$75` entry instead of blocking, while sub-minimum room still blocks.

### 2026-06-24 - Step 3 status update: AUDIT-012
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- Saved-account parse failures now preserve an account shell with the raw account id/name, default safe config, no credentials, no auto-connect, and a visible `settings_load_error`.
- `TraderManager` now records `settings_diagnostics` and exposes them in settings, state, dashboard state, and health payloads.
- The frontend uses the existing top warning banner to surface settings diagnostics.

### 2026-06-24 - Step 3 status update: AUDIT-013
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- `load_settings()` now returns visible `settings_load_error` diagnostics instead of silently returning `{}` on corrupt or unreadable settings files.
- If a timestamped backup can be parsed, settings load recovers from that backup and includes `settings_recovered_from_backup`.
- `save_settings()` now writes through a temp file with flush/fsync and `os.replace`, and backs up the previous settings file before replacement.
- Regression coverage now tests corrupt-load surfacing, backup recovery, atomic replacement, backup creation, and write-error propagation.

### 2026-06-24 - Step 3 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 21 tests, with 2 expected failures remaining only for out-of-scope AUDIT-018 and AUDIT-019.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
Regression review:
- AUDIT-001: No regression observed; runtime currentness behavior was not changed beyond adding settings diagnostics to `/api/health`.
- AUDIT-002: Fixed; Daily P/L payloads and UI now expose raw/display/percent/date fields clearly.
- AUDIT-003: Fixed; realized-today summary now exposes the session date boundary used for filtering.
- AUDIT-004: No regression observed; no monolith split or broad refactor was attempted.
- AUDIT-005: No regression observed; Step 2 harness remains in place and Step 3 contracts now pass.
- AUDIT-006: Improved narrowly for settings load/save visibility; broad exception handling outside Step 3 scope remains open.
- AUDIT-007: No regression observed; frontend polling coordination was not changed.
- AUDIT-008: No regression observed; stale-runtime recovery behavior was not changed.
- AUDIT-009: No regression observed; selected-account response sequencing was not changed.
- AUDIT-010: Fixed; trade sizing now uses explicit mode with conflict rejection or labeled saved-settings migration.
- AUDIT-011: Fixed; exposure-room sizing downsizes to remaining tradeable room.
- AUDIT-012: Fixed; invalid saved accounts are preserved visibly instead of silently dropped.
- AUDIT-013: Fixed; corrupt settings loads surface diagnostics and saves are backup-backed atomic replacements.
- AUDIT-014: No regression observed; launcher currentness behavior was not changed.
- AUDIT-015: No regression observed; layout breakpoints and table scrolling were not changed.
- AUDIT-016: Fixed; selected-account and account-card Daily P/L contracts now use consistent raw/display/percent keys.
- AUDIT-017: No regression observed; inverse ETF code/docs were not changed.
- AUDIT-018: No regression observed; market-stream union behavior remains intentionally unchanged for Step 5 and still has an expected-failing future contract.
- AUDIT-019: No regression observed; held-symbol stream behavior remains intentionally unchanged for Step 5 and still has an expected-failing future contract.
- AUDIT-020: No regression observed; launcher fallback behavior was not changed.
- AUDIT-021: No regression observed; day-tape/replay behavior was not changed.
Conclusion:
- No previous finding regressed in Step 3.

### 2026-06-24 - Step 3 child-found finding: STEP3-CHILD-001 settings diagnostics could hide runtime-health warning
Status: Fixed in `codex/alpaca-account-metrics-settings`
Evidence:
- After the Step 3 focused regression audit entry was written, final diff review found a frontend warning-banner edge case in `python_app/static/app.js`.
- `renderSettingsDiagnostics()` reused the runtime-health banner to surface settings-load diagnostics. A successful state/settings poll with no settings warnings could call `renderRuntimeHealth({current: true, settings_diagnostics: {}})` and hide an existing runtime-health error banner created by `renderRuntimeHealthError()`.
Impact:
- A later successful settings-diagnostics refresh could visually clear a still-unresolved runtime-health warning.
Fix:
- Added a guard so an empty settings-diagnostics update does not hide an existing runtime-health error when no successful runtime-health payload has replaced it.
Scope:
- This is a Step 3 UI warning-surface fix only. It does not change Step 4 polling coordination, Step 5 market-stream behavior, the stable checkout, or the live backend.


### 2026-06-24 - Step 3 correction verification: STEP3-CHILD-001
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 21 tests, with 2 expected failures remaining only for out-of-scope AUDIT-018 and AUDIT-019.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
Conclusion:
- STEP3-CHILD-001 is logged and fixed. No Step 4 or Step 5 work was started.

## Step 4 Implementation Notes

### 2026-06-24 - Step 4 status update: AUDIT-007, AUDIT-009
Status: Fixed in `codex/alpaca-frontend-state-layout`
Evidence:
- `python_app/static/app.js` now has per-channel request coordination for `health`, `state`, and `dashboard` requests.
- State and dashboard polling use request sequence tokens, `AbortController` cancellation for superseded state/dashboard fetches, and selected-account context checks before rendering.
- Aborted fetches no longer enter stale-instance recovery.
- `renderState(state, context)` rejects stale selected-account responses before mutating selected-account UI, metrics, config fields, positions, tables, warnings, or buttons.
- `renderDashboard(dashboard, context)` and dashboard stream recovery reject stale dashboard contexts before repainting visible dashboard warnings or stream status.
- Account switching through the account select, account cards, and New account button now runs through `switchToAccount()`, which invalidates in-flight state/dashboard requests and pauses background polling during the transition.
- Auto-save, settings reload, profile preset, custom-profile save, and account-specific action responses now carry guards so older responses cannot overwrite the form or selected account after a newer account switch.
- Step 3 account metric labels and rendering helpers were preserved: `Daily P/L (equity)`, `Realized Today`, `dailyPlDisplay()`, `renderRealizedPlMetric()`, and the explicit raw/display/percent fields remain in use.

### 2026-06-24 - Step 4 status update: AUDIT-015
Status: Fixed in `codex/alpaca-frontend-state-layout`
Evidence:
- `python_app/static/styles.css` now collapses the Accounts layout to one column at `max-width: 1180px`, covering 1024px and 1100px desktop windows.
- Account layout containers, panels, workspace, tabs, and tab panels now include `min-width: 0`/`max-width` containment where needed.
- Metrics now use `repeat(auto-fit, minmax(128px, 1fr))` instead of forcing a six-column minimum.
- Wide dashboard/account tables remain horizontally scrollable inside `.dashboard-table` or `.tab-panel` instead of expanding the whole page.
- Browser automation was not available in this worktree: local `playwright` and `puppeteer` modules were absent, and tool discovery did not expose a browser screenshot tool. Added deterministic rendered-layout contract check `scripts/check_frontend_layout.py`.
- Layout evidence from `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py`:
  - 1024px: Accounts layout collapsed, workspace width 988px, metric required width 828px, tables scroll locally, whole-page horizontal overflow `false`.
  - 1100px: Accounts layout collapsed, workspace width 1064px, metric required width 828px, tables scroll locally, whole-page horizontal overflow `false`.
  - 1280px launcher/default width from `Launch Alpaca Paper Trader.vbs --window-size=1280,900`: Accounts layout not collapsed, workspace width 906px, metric required width 828px, tables scroll locally, whole-page horizontal overflow `false`.

### 2026-06-24 - Step 4 regression coverage update: AUDIT-007, AUDIT-009, AUDIT-015
Status: Covered
Evidence:
- Added `tests/test_frontend_state_layout.py`.
- Coverage pins state polling request tokens, abort/cancellation behavior, stale render rejection, dashboard request guards, latest-only health warning rendering, guarded account switching/auto-save, and Accounts layout containment rules.
- Added `scripts/check_frontend_layout.py` for deterministic 1024px, 1100px, and 1280px launcher/default viewport layout evidence.

### 2026-06-24 - Step 4 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 27 tests, with 2 expected failures remaining only for out-of-scope AUDIT-018 and AUDIT-019.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py` passed with the viewport evidence listed above.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices for edited static files.
Regression review:
- AUDIT-001: No regression observed; runtime currentness/backend restart behavior was not changed.
- AUDIT-002: No regression observed; Step 3 Daily P/L amount/percent display remains covered and unchanged.
- AUDIT-003: No regression observed; realized-today session date behavior remains covered and unchanged.
- AUDIT-004: No regression observed; no broad monolith split or architecture refactor was attempted.
- AUDIT-005: No regression observed; regression harness remains in place and now includes Step 4 frontend/layout coverage.
- AUDIT-006: No regression observed; broad exception handling outside previously fixed settings paths was not changed.
- AUDIT-007: Fixed; frontend polling now rejects stale state/dashboard/health responses through request sequencing, cancellation, and render guards.
- AUDIT-008: No regression observed; stale-runtime health/recovery behavior was preserved.
- AUDIT-009: Fixed; selected-account state responses and account switch/auto-save paths are guarded against older account-specific responses.
- AUDIT-010: No regression observed; explicit trade-size-mode behavior remains covered and unchanged.
- AUDIT-011: No regression observed; exposure-room downsizing behavior remains covered and unchanged.
- AUDIT-012: No regression observed; invalid saved-account shell/diagnostic behavior remains covered and unchanged.
- AUDIT-013: No regression observed; corrupt settings load and atomic save behavior remain covered and unchanged.
- AUDIT-014: No regression observed; VBS launcher currentness behavior was not changed.
- AUDIT-015: Fixed; Accounts view no longer requires whole-page horizontal panning at 1024px, 1100px, or 1280px launcher/default width.
- AUDIT-016: No regression observed; standardized Daily P/L raw/display/percent contract remains covered and unchanged.
- AUDIT-017: No regression observed; inverse ETF code/docs were not changed.
- AUDIT-018: No regression observed; market-stream union behavior remains intentionally unchanged for Step 5 and still has an expected-failing future contract.
- AUDIT-019: No regression observed; held-symbol stream behavior remains intentionally unchanged for Step 5 and still has an expected-failing future contract.
- AUDIT-020: No regression observed; launcher fallback/currentness behavior was not changed.
- AUDIT-021: No regression observed; day-tape/replay behavior was not changed.
- STEP3-CHILD-001: No regression observed; settings diagnostics still do not clear an unresolved runtime-health error without a successful runtime-health payload.
Conclusion:
- No previous finding regressed in Step 4.
- No new defects were discovered during Step 4 verification.
- Step 5 market-stream union/held-symbol behavior was not started.

## Step 5 Implementation Notes

### 2026-06-24 - Step 5 status update: AUDIT-017
Status: Fixed in `codex/alpaca-market-data-strategy-drift`
Evidence:
- Removed the unused `market_downturn_active()` and `downturn_inverse_allowed()` helpers and the stale downturn threshold constants.
- Renamed the active inverse-universe helpers away from downturn terminology. Top-volume allow mode now adds the bounded inverse ETF set directly, inverse-only mode uses that same set, and exclude mode suppresses the automatic inverse set.
- SPY/QQQ remain market-proxy analysis symbols only; they do not gate inverse ETF eligibility.
- The entry path still evaluates inverse ETFs through `inverse_etf_hold_reason()` and the same normal entry-quality checks as other candidates. No separate downturn blocker was added.
- The Accounts UI now labels the inverse choices as `Exclude auto set`, `Allow top-volume set`, and `Inverse set only`.
- `README.md`, `readme.md`, and `OPERATING.md` now describe the current no-downturn-gate inverse ETF contract.
- Regression coverage now asserts that `SQQQ` is eligible in allow mode without an inverse-specific hold reason, the old downturn gate helpers are absent, and exclude mode suppresses the automatic inverse set.

### 2026-06-24 - Step 5 status update: AUDIT-018, AUDIT-019
Status: Fixed in `codex/alpaca-market-data-strategy-drift`
Evidence:
- `TraderManager.market_data_symbols()` now keeps dashboard symbols tied to the selected shared stream source while building bar subscriptions as a deterministic capped union of every connected account with `use_market_stream` enabled.
- The bar subscription union starts with dashboard symbols, then adds each eligible account's `scan_symbols()` in source-first order, preserving coverage for account-specific candidates.
- Held positions are included because `scan_symbols()` already merges `position_symbols_for_market_data()`.
- Regression coverage converted the previous AUDIT-018 and AUDIT-019 expected-failing future contracts into normal passing tests.

### 2026-06-24 - Step 5 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 27 tests, no expected failures.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py` passed with the Step 4 viewport evidence still showing no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
Regression review:
- AUDIT-001: No regression observed; runtime currentness/backend restart behavior was not changed.
- AUDIT-002: No regression observed; Step 3 Daily P/L amount/percent display remains covered and unchanged.
- AUDIT-003: No regression observed; realized-today session date behavior remains covered and unchanged.
- AUDIT-004: No regression observed; no broad monolith split or architecture refactor was attempted.
- AUDIT-005: No regression observed; regression harness remains in place and now covers Step 5 market-stream and inverse ETF contracts.
- AUDIT-006: No regression observed; broad exception handling outside previously fixed settings paths was not changed.
- AUDIT-007: No regression observed; frontend polling coordination tests still pass.
- AUDIT-008: No regression observed; stale-runtime health/recovery behavior was preserved.
- AUDIT-009: No regression observed; selected-account response sequencing tests still pass.
- AUDIT-010: No regression observed; explicit trade-size-mode behavior remains covered and unchanged.
- AUDIT-011: No regression observed; exposure-room downsizing behavior remains covered and unchanged.
- AUDIT-012: No regression observed; invalid saved-account shell/diagnostic behavior remains covered and unchanged.
- AUDIT-013: No regression observed; corrupt settings load and atomic save behavior remain covered and unchanged.
- AUDIT-014: No regression observed; launcher currentness behavior was not changed.
- AUDIT-015: No regression observed; layout contract check still passes at the Step 4 viewports.
- AUDIT-016: No regression observed; standardized Daily P/L raw/display/percent contract remains covered and unchanged.
- AUDIT-017: Fixed; inverse ETF code, docs, and UI now match the no-downturn-gate strategy contract.
- AUDIT-018: Fixed; shared market-stream bar subscriptions now union connected eligible account scan symbols.
- AUDIT-019: Fixed; held-position symbols are included in shared market-stream bar subscriptions.
- AUDIT-020: No regression observed; launcher fallback/currentness behavior was not changed.
- AUDIT-021: No regression observed; day-tape/replay behavior was not changed.
- STEP3-CHILD-001: No regression observed; settings diagnostics still do not clear an unresolved runtime-health error without a successful runtime-health payload.
Conclusion:
- No previous finding regressed in Step 5.
- No new defects were discovered during Step 5 verification.
- Step 6 monolith/backtester work was not started.

### 2026-06-24 - Step 5 coordinator-found finding: STEP5-COORD-001 exclude inverse mode validator remaps to allow
Status: Fixed in `codex/alpaca-market-data-strategy-drift`
Evidence:
- Coordinator review after the Step 5 child finished found `AppConfig.validate_inverse_etf_mode()` still returns `allow` when the incoming mode is `exclude`.
- The Step 5 UI, docs, and tests now define `exclude` as suppressing the automatic bounded inverse ETF set, but normal validated payloads would silently become `allow`.
- The added regression test used `model_copy(update={"inverse_etf_mode": "exclude"})`, which bypasses normal validation and therefore did not catch the persisted/config-load path.
Impact:
- A user selecting `Exclude auto set` could still get automatic inverse ETF candidates after validation, contradicting the Step 5 contract.
Required fix:
- Preserve `exclude` through `AppConfig` validation and add a regression test that constructs or validates an `AppConfig` with `inverse_etf_mode="exclude"` through the normal validation path.
- Rerun the full Step 5 verification set and update this finding before Step 5 is committed.
Fix evidence:
- `AppConfig.validate_inverse_etf_mode()` now returns the validated mode unchanged, so `exclude` survives normal Pydantic construction and saved/config payload validation.
- `MarketStreamBaselineTests.test_inverse_etf_eligibility_has_no_downturn_gate` now constructs `AppConfig(symbols=["MSFT"], use_top_volume_symbols=True, inverse_etf_mode="exclude")` through the normal validation path, asserts the mode remains `exclude`, and proves `SQQQ` is not in `trading_symbols()`.
Verification:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 27 tests.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py` passed.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
### 2026-06-24 - Step 6 coordinator finding: STEP6-COORD-001 child thread materialized detached and systemErrored before work
Status: Replaced with clean child thread
Evidence:
- Step 6 `create_thread` returned only pending worktree id `local:7236e7da-ee57-4020-9c0f-d63bd339df83`.
- The real child thread later materialized as `019efbcd-d267-7191-bf5a-9eb11b247761` in `C:\Users\solo leveling\.codex\worktrees\da22\alpaca trading app`, but Codex reported `systemError` before any assistant response.
- Coordinator inspection showed the worktree at commit `032b0e5` with `## HEAD (no branch)` instead of branch `codex/alpaca-monolith-backtester-seam`.
Impact:
- Treating the queued worktree as started would silently halt the Step 6 fix and repeat the earlier coordination failure.
Required fix:
- Attach the worktree to `codex/alpaca-monolith-backtester-seam`, verify it is not the stable checkout, send a corrective follow-up to the child, and keep polling until the child either progresses or a replacement thread is launched.
Resolution evidence:
- Coordinator switched the worktree to `codex/alpaca-monolith-backtester-seam` at `032b0e5` and sent a corrective follow-up.
- Polling showed the follow-up was recorded but no assistant turn ran; the thread remained `systemError`.
- Coordinator committed this audit note and will launch a replacement Step 6 child from a fresh branch so work can continue from a clean, branch-attached state.
- Replacement child `019efbcf-9b4f-75b2-a4a3-cb2114401413` materialized in `C:\Users\solo leveling\.codex\worktrees\411a\alpaca trading app`, also detached at `d130000`, and also reported `systemError` before any assistant response.
- The repeated signature points to a Codex child-thread startup failure for this Step 6 launch pattern rather than a code or test failure inside the app.
- Coordinator will try one reduced prompt/thread launch without the high-reasoning override; if that fails, continue with an isolated worker/subagent or coordinator-owned worktree so Step 6 does not halt.
- Reduced-prompt child `019efbd0-b8cb-7413-ae35-f27d3e1c7c4e` is the active Step 6 child in `C:\Users\solo leveling\.codex\worktrees\7555\alpaca trading app`.
- Coordinator verified this worktree initially materialized detached at `7b67059`, then attached it to branch `codex/alpaca-monolith-backtester-seam-v3` at the same commit before any child changes.
- Child self-check before edits confirmed `## codex/alpaca-monolith-backtester-seam-v3` and root `C:/Users/solo leveling/.codex/worktrees/7555/alpaca trading app`, not the stable checkout.

### 2026-06-24 - Step 6 pre-implementation scope: AUDIT-004, AUDIT-006, AUDIT-021
Status: In progress in `codex/alpaca-monolith-backtester-seam-v3`
Evidence:
- `python_app/alpaca_desktop/engine.py::TraderEngine.refresh()` still combines account refresh, market-data fetch, strategy execution, order/protection handling, P/L payload assembly, and day-tape scan recording.
- `python_app/alpaca_desktop/engine.py::apply_strategy()`, `submit_protective_exit_order()`, `submit_limit_exit_order()`, and `submit_exit_order()` submit live orders directly through `TradingClient`, so a future backtester has no concrete order-execution boundary to replace.
- `python_app/alpaca_desktop/engine.py::append_replay_event()` and `python_app/alpaca_desktop/day_tape.py::append_day_tape_event()` attach `write_error` to returned events, but they do not emit a shared runtime diagnostic.
- `python_app/alpaca_desktop/engine.py::load_dashboard_cache_rows()` returns `{}` on read/parse failure, and `save_dashboard_cache_rows()` uses `pass` on write failure.
- `python_app/alpaca_desktop/engine.py::record_day_tape_bars()`, `record_day_tape_scan()`, `trade_intent_lookup()`, and `restore_trade_guards_from_replay()` can drop replay/day-tape failures with `pass` or `return`.
- `python_app/alpaca_desktop/server.py::get_health()`, `TraderManager.state()`, and `TraderManager.dashboard_state()` expose settings and stream health but no shared runtime diagnostics for recoverable persistence/replay/cache failures.
Planned fix:
- Add a small backtester boundary module with typed ports for account state, market data, order execution, clock, replay, and strategy evaluation.
- Add a `TraderEngine.backtester_boundary()` adapter that delegates to the existing live strategy methods instead of copying strategy rules.
- Wrap live order submission through the boundary with a typed order-execution error while preserving existing order-rejection behavior.
- Add a small runtime diagnostics ring and surface it through health/state/dashboard payloads.
- Replace the confirmed silent persistence/replay/cache fallback paths with typed catches and diagnostic logging.
Scope guard:
- Do not rewrite the strategy scan, sizing, metrics, layout, market-stream, or refresh-loop contracts.
- If a broader monolith split is needed beyond these ports and diagnostics, log it as out of scope and stop.

### 2026-06-24 - Step 6 status update: AUDIT-004, AUDIT-006, AUDIT-021
Status: Fixed in `codex/alpaca-monolith-backtester-seam-v3`
Evidence:
- Added `python_app/alpaca_desktop/backtester.py` with typed ports for account state, market data, order execution, replay, clock, and strategy evaluation.
- Added `TraderEngine.backtester_boundary()` in `python_app/alpaca_desktop/engine.py`; the strategy port delegates to existing `entry_candidate()`, `apply_strategy()`, `snapshot()`, and `scan_symbols()` so future backtests reuse live strategy logic instead of copying rules.
- Live order submission/cancellation paths now run through the order-execution boundary and wrap broker/client failures as `OrderExecutionError` while preserving existing order-intent, hold, and rejection handling.
- Added `python_app/alpaca_desktop/runtime_diagnostics.py` as a shared ring for recoverable runtime diagnostics.
- `/api/health`, manager `state()`, manager `dashboard_state()`, and the runtime-health banner now surface runtime diagnostics alongside existing settings diagnostics.
- Replaced confirmed silent/default fallbacks in replay, day-tape, dashboard cache, settings load/recovery, launcher currentness helpers, custom-profile validation, API-client cleanup, and market-stream cleanup with typed catches and runtime diagnostics.
- Kept strategy scoring, sizing, account metrics, layout rules, polling coordination, and market-stream subscription contracts unchanged.

### 2026-06-24 - Step 6 regression coverage update
Status: Covered
Evidence:
- Added `tests/test_backtester_boundary_diagnostics.py`.
- Coverage proves the backtester strategy boundary delegates into `TraderEngine.apply_strategy()` with the same arguments instead of implementing parallel strategy logic.
- Coverage proves account-state snapshots are copied, live order failures become `OrderExecutionError` plus runtime diagnostics, manager state/dashboard payloads include runtime diagnostics, dashboard-cache parse failures are diagnosed, and replay write failures still return `write_error` while recording diagnostics.

### 2026-06-24 - Step 6 focused regression audit
Status: Complete
Checks:
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 33 tests.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local setup.
- `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py` passed with the Step 4 viewport evidence still showing no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `git diff --check` passed; warnings were only Git's existing LF-to-CRLF normalization notices.
Regression review:
- AUDIT-001: No regression observed; runtime currentness/backend restart behavior was not changed.
- AUDIT-002: No regression observed; Daily P/L amount/percent display tests still pass.
- AUDIT-003: No regression observed; realized-today date/session behavior tests still pass.
- AUDIT-004: Fixed narrowly for the backend/backtester boundary; frontend monolith splitting remains out of Step 6 scope.
- AUDIT-005: No regression observed; regression harness now covers Step 6 boundary and diagnostics.
- AUDIT-006: Fixed for the confirmed critical silent/default fallback paths; remaining broad API/background/stream handlers are logged, surfaced as health/state, or converted to HTTP errors.
- AUDIT-007: No regression observed; frontend request coordination tests still pass.
- AUDIT-008: No regression observed; stale-runtime health/recovery behavior was preserved.
- AUDIT-009: No regression observed; selected-account response sequencing tests still pass.
- AUDIT-010: No regression observed; explicit trade-size-mode behavior remains covered and unchanged.
- AUDIT-011: No regression observed; exposure-room downsizing behavior remains covered and unchanged.
- AUDIT-012: No regression observed; invalid saved-account shell/diagnostic behavior remains covered and unchanged.
- AUDIT-013: No regression observed; corrupt settings load and atomic save behavior remain covered and unchanged, with runtime diagnostics added for load/recovery failures.
- AUDIT-014: No regression observed; VBS launcher currentness behavior was not changed.
- AUDIT-015: No regression observed; layout contract check still passes at the Step 4 viewports.
- AUDIT-016: No regression observed; standardized Daily P/L raw/display/percent contract remains covered and unchanged.
- AUDIT-017: No regression observed; inverse ETF code/docs/UI behavior was not changed.
- AUDIT-018: No regression observed; shared market-stream union tests still pass.
- AUDIT-019: No regression observed; held-symbol stream tests still pass.
- AUDIT-020: No regression observed; launcher fallback/currentness behavior was preserved except for typed, non-silent launcher exception handling.
- AUDIT-021: Fixed; the replay/backtester path now has a concrete live-engine boundary for account state, market data, order execution, replay, clock, and strategy evaluation.
- STEP3-CHILD-001: No regression observed; settings diagnostics still do not clear unresolved runtime-health errors without a successful runtime-health payload.
- STEP5-COORD-001: No regression observed; `inverse_etf_mode="exclude"` still survives validation and suppresses the automatic inverse set.
Conclusion:
- No previous finding regressed in Step 6.
- No new defects were discovered during Step 6 verification.
- Stable checkout, live backend, saved credentials, and real `%LOCALAPPDATA%\AlpacaPaperTrader` were not touched.

### 2026-06-24 - Step 6 coordinator-found finding: STEP6-COORD-002 background error recorder can still silently drop failures
Status: Fixed in `codex/alpaca-monolith-backtester-seam-v3`
Evidence:
- Coordinator review after Step 6 commit `63fa3ad` found `python_app/alpaca_desktop/server.py::record_background_error()` still catches a broad `Exception` and uses `pass`.
- This is the fallback used by the background refresh/watchdog loop to surface failures through account logs and `last_error`.
Impact:
- If account-level error recording fails, the background-loop error can still disappear without entering the new runtime diagnostics ring, contradicting the Step 6 AUDIT-006 completion claim.
Required fix:
- Replace the silent `pass` with a runtime diagnostic entry that preserves the existing loop recovery behavior without exposing credentials or changing trading decisions.
Fix evidence:
- `record_background_error()` now records a `background_loop` runtime diagnostic if account-level error recording itself fails.
- Added `test_background_error_recorder_failure_records_diagnostic` to `tests/test_backtester_boundary_diagnostics.py`.
- Coordinator rerun passed: `scripts/run_regression_tests.py` 34 tests, Python compile, `node --check python_app\static\app.js`, `scripts/check_frontend_layout.py`, worktree-local `setup-worktree.ps1 -SmokeOnly`, and `git diff --check` with only LF-to-CRLF warnings.

### 2026-06-24 - Step 7 full regression audit and live deployment plan
Status: Complete; documentation-only update on `codex/alpaca-full-regression-deployment-plan`
Scope guard:
- Verified current worktree root before Step 7 edits: `C:\Users\solo leveling\.codex\worktrees\b399\alpaca trading app`.
- Verified branch before Step 7 edits: `## codex/alpaca-full-regression-deployment-plan`.
- Verified starting commit before Step 7 edits: `dffc0fa24a2c1b83f06b31ee41d7b275695e4dd5`.
- The initial worktree materialized detached, but the coordinator attached it to `codex/alpaca-full-regression-deployment-plan` at `dffc0fa`; Step 7 self-check confirmed the branch was attached before any edits.
- No behavior code was changed in Step 7.
- Stable checkout, live backend, saved credentials, and real `%LOCALAPPDATA%\AlpacaPaperTrader` were not touched.

Verification:
- Initial `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` attempt did not execute because the worktree virtual environment was missing.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1` passed, created only worktree-local `.venv` and `.runtime\localappdata`, and the import smoke passed.
- `.\.venv\Scripts\python.exe scripts\run_regression_tests.py` passed: 34 tests.
- `.\.venv\Scripts\python.exe -m compileall -q python_app` passed.
- `node --check python_app\static\app.js` passed.
- `.\.venv\Scripts\python.exe scripts\check_frontend_layout.py` passed; viewports 1024, 1100, and 1280 all had `whole_page_horizontal_overflow=false`.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed with worktree-local `LOCALAPPDATA`.
- `git diff --check` passed after the Step 7 documentation edit; warning was only Git's LF-to-CRLF normalization notice for the audit log.

Final AUDIT finding status:
- AUDIT-001: Fixed for runtime currentness detection and launcher reuse safety; live replacement still requires an approved deployment/restart window.
- AUDIT-002: Fixed; Daily P/L amount and percent are covered by regression tests.
- AUDIT-003: Fixed; realized-today date/session behavior is explicit and covered.
- AUDIT-004: Closed for deployment scope; backend/backtester boundary is in place, with remaining frontend monolith cleanup tracked as non-blocking future debt.
- AUDIT-005: Fixed; the regression harness exists and covers the critical audited contracts.
- AUDIT-006: Fixed for confirmed critical silent/default fallback paths; runtime diagnostics now surface recoverable failures.
- AUDIT-007: Fixed; frontend polling/request coordination is covered.
- AUDIT-008: Fixed; stale-runtime health/currentness behavior is covered.
- AUDIT-009: Fixed; selected-account response sequencing is covered.
- AUDIT-010: Fixed; explicit trade-size-mode behavior is covered.
- AUDIT-011: Fixed; exposure-room downsizing behavior is covered.
- AUDIT-012: Fixed; invalid saved-account shell/diagnostic behavior is covered.
- AUDIT-013: Fixed; corrupt settings load, backup recovery, and atomic save behavior are covered.
- AUDIT-014: Fixed; launcher currentness behavior is covered.
- AUDIT-015: Fixed; narrow desktop layout contract is covered.
- AUDIT-016: Fixed; Daily P/L raw/display/percent payload contract is covered.
- AUDIT-017: Fixed; inverse ETF behavior no longer depends on a separate downturn gate and docs/UI match.
- AUDIT-018: Fixed; shared market-stream bar subscriptions union connected eligible account symbols.
- AUDIT-019: Fixed; held-position symbols are included in shared market-stream bar subscriptions.
- AUDIT-020: Fixed; legacy PowerShell fallback is removed from the launch path.
- AUDIT-021: Fixed; replay/backtester work now has live-engine boundary ports for account state, market data, order execution, replay, clock, and strategy evaluation.

Final coordinator/non-AUDIT finding status:
- STEP2-COORD-001: Closed; Step 7 verified the branch-attached worktree and did not edit the stable checkout.
- STEP2-COORD-002: Closed; Step 7 did not move stable dirty state or touch the stable checkout.
- STEP3-CHILD-001: Fixed; settings diagnostics still do not clear unresolved runtime-health errors without a successful runtime-health payload.
- STEP5-COORD-001: Fixed; `inverse_etf_mode="exclude"` survives validation and suppresses the automatic inverse set.
- STEP6-COORD-001: Closed; Step 6 completed through the clean replacement path, and Step 7 started from verified Step 6 commit `dffc0fa`.
- STEP6-COORD-002: Fixed; background error recorder fallback now records a runtime diagnostic.

Regression conclusion:
- No new defects or regressions were discovered during Step 7 verification.
- No code change is required from Step 7.

Live deployment plan:
- Status: Prepared only; not executed in Step 7.
- Deployment should happen only after explicit user approval for a live app restart/replacement. Until then, leave the current live backend and data collection running.
- Prefer a planned maintenance point, ideally outside active data-collection/trading hours. If deployment must happen while collection is active, first capture a timestamped pre-deploy snapshot of live `/api/health`, source stamp, PID, account count, and day-tape append state without exposing credentials or account identifiers.
- Before touching the stable checkout, confirm its `git status --short --branch`, current commit, and live source stamp. Preserve any unrelated user changes; do not reset or overwrite the stable checkout.
- Back up `%LOCALAPPDATA%\AlpacaPaperTrader\python-settings.json`, `instance.json`, and the day-tape directory to a timestamped local backup folder. Do not decrypt, print, copy into chat, or modify credential blobs.
- Apply the verified code through Git in the stable checkout only after approval, using the audited Step 6/Step 7 branch lineage. Do not copy `.runtime`, `.venv`, worktree settings, or any worktree-local app data into the stable checkout.
- Run pre-live checks from the stable checkout with an isolated `LOCALAPPDATA` override first: regression harness, Python compile, frontend syntax check, layout check, and smoke check. These checks must not connect to Alpaca or reuse real saved settings.
- When approved to replace the running app, use the app's current launcher/runtime-currentness path and verify that `/api/health` reports the expected current source stamp, PID, and source path. Do not force-kill a protected PID while active collection is still required unless the user explicitly approves that interruption.
- After launch, verify that saved accounts still load, settings diagnostics are clear or explicitly understood, runtime diagnostics have no new deployment errors, and day-tape recording resumes or remains correctly closed-market idle. Verify account count/names only locally and do not expose account identifiers.
- Confirm that saved sizing/exposure/auto-connect/auto-start settings are unchanged from the pre-deploy snapshot unless the user explicitly approved a settings change.
- Rollback plan: if health/currentness, settings load, credential access, or day-tape continuity fails, stop and preserve logs. Revert code to the previous stable commit only with user approval, and restore settings/day-tape backups only if the file state was changed or corrupted.

### 2026-06-24 - Goal resume live-runtime check
Status: Live deployment still pending approval
Evidence:
- Stable checkout has five pre-existing dirty files before this pass: `Launch Alpaca Paper Trader.vbs`, `python_app/alpaca_desktop/engine.py`, `python_app/run.py`, `scripts/test_runtime_currentness.py`, and `tests/test_backtester_boundary_diagnostics.py`.
- Offline checks against the current dirty checkout passed: `scripts/run_regression_tests.py` ran 38 tests, Python compile passed, `node --check python_app\static\app.js` passed, `git diff --check` passed with only LF-to-CRLF normalization warnings, `setup-worktree.ps1 -SmokeOnly` passed with isolated `LOCALAPPDATA`, and `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- Read-only live `/api/health` check found the backend reachable at `http://127.0.0.1:8765`, but `status=stale`, `current=False`, and the live `source_stamp` did not match the current checkout source stamp.
Impact:
- The current disk code is regression-clean, but the running desktop app is still not satisfying the no-stale-runtime-warning acceptance item until an approved live restart/replacement loads the current source.
Verification needed:
- Before live replacement, take the planned pre-deploy backup/snapshot without exposing credentials or account identifiers.
- After live replacement, verify `/api/health` reports `current=True` and matching source stamp, then verify all saved accounts, Daily P/L fields, sizing mode, runtime diagnostics, and day-tape continuity locally.

### 2026-06-24 - Goal resume finding: AUDIT-022 top-volume universe still seeded from local S&P list
Status: Fixed locally, not live until approved restart/replacement
Evidence:
- `python_app/alpaca_desktop/sp500.py` contains a hardcoded S&P 500 symbol list.
- `python_app/alpaca_desktop/engine.py::refresh_top_volume()` calls `fetch_stock_snapshots_chunked(data_client, list(SP500_SYMBOLS), feed)` and ranks those snapshot rows by daily volume.
- The installed Alpaca client exposes `ScreenerClient.get_most_actives()` with `MostActivesRequest`, so a direct Alpaca top-volume source is available.
Impact:
- Although snapshot price/volume data comes from Alpaca, the live candidate universe is constrained by a local list that can become stale and violates the contract's "no hardcoded lists, stale cache, mock data, or outside data sources for live candidate selection" rule.
Required fix:
- Use Alpaca's screener/most-actives API as the primary top-volume candidate source, then enrich/rank the returned symbols with Alpaca snapshots.
- Keep held-position monitoring separate and keep the bounded inverse ETF set only as an explicit strategy extension that must pass the same rules as other symbols.
Verification needed:
- Add regression coverage proving `refresh_top_volume()` uses the screener source before snapshot enrichment and does not call the hardcoded S&P list for live top-volume selection.
- Rerun the full offline regression set and isolated smoke checks.
Fix evidence:
- Removed the local `python_app/alpaca_desktop/sp500.py` symbol list and removed the `SP500_SYMBOLS` import from the live engine.
- Added `fetch_most_active_symbols()` using Alpaca `ScreenerClient.get_most_actives(MostActivesRequest(top=25, by=MostActivesBy.VOLUME))`.
- `refresh_top_volume()` now uses the Alpaca most-actives response as the ranked universe, then enriches only those returned symbols with Alpaca snapshots for display price/status context.
- Updated day-tape top-volume source labels from `sp500_snapshot_volume` to `alpaca_most_actives_volume`.
- Updated README and the account settings checkbox copy from S&P wording to Alpaca top-25 volume wording.
Verification:
- `scripts/run_regression_tests.py` passed: 39 tests, including `test_top_volume_refresh_uses_alpaca_most_actives_screener`.
- Python compile, `node --check python_app\static\app.js`, `git diff --check`, `setup-worktree.ps1 -SmokeOnly`, and `scripts/check_frontend_layout.py` all passed.
- `rg` found no remaining live-code or user-doc `SP500`, `sp500`, `S&P 500`, or `sp500_snapshot_volume` references outside this audit ledger's historical evidence.

### 2026-06-24 - Goal resume finding: AUDIT-023 replay lacked app-engine day-tape backtest path
Status: Fixed locally, not live until approved restart/replacement
Evidence:
- `README.md` still described `scripts/day_tape_fast_forward.py` as only an event-flow foundation and said the fake broker/profit simulator was a later layer.
- The stable checkout had `python_app/alpaca_desktop/backtester.py` boundary ports, but no runnable day-tape backtest script that reported accepted trades, rejected candidates, rejection reasons, and winner/loser indicator comparisons.
Impact:
- The replay/backtester acceptance item could not be proven from a user-runnable artifact. The app had useful tape review tools, but not the requested strategy-replay evidence path.
Required fix:
- Add a day-tape backtest command that consumes recorded top-volume snapshots, feeds market bars into the same `TraderEngine` strategy state, and evaluates entries through the app-engine boundary rather than a parallel selector.
- Keep replay sizing/capacity fixed at one replay account, `$1000` starting equity/cash, 20 max positions, 5% per slot, and 100% total exposure.
Fix evidence:
- Added `scripts/day_tape_backtest.py`.
- The script uses top-volume snapshots from the tape as the replay universe, calls `TraderEngine.trading_symbols()` for the live-equivalent entry universe, feeds `market_bar` events into `StrategyState`, evaluates candidates through `EngineBacktesterBoundary.strategy.entry_candidate()`, and applies exits through the live `local_protection_exit_decision()` helper.
- It reports `selection_engine: app_engine`, fixed sizing harness settings, accepted trades, closed trades, rejected candidate samples with hold reasons, and winner/loser averages for the exact entry indicator raw fields.
- Updated README and `scripts/day_tape_fast_forward.py` to point to the new backtest command.
Verification:
- `python -m unittest tests.test_day_tape_backtest -v` passed.
- A bounded read-only run against the real `tape-20260624.jsonl` completed without Alpaca API calls or app-state writes; the existing tape still reported old source `sp500_snapshot_volume` because it was recorded before AUDIT-022 is live.

### 2026-06-25 - Goal continuation finding: AUDIT-024 blocked stale runtime still attempted hidden backend start
Status: Fixed locally, not live until approved restart/replacement
Evidence:
- `python_app/run.py::active_instance_url()` printed `Refusing to start on a random fallback port` when a stale backend did not stop, but returned an empty string.
- `python_app/run.py::main()` treated an empty existing URL as permission to call `save_instance_url()` and then `uvicorn.run()` on the preferred port.
Impact:
- If the stale backend still occupied `127.0.0.1:8765`, normal VBS launch could start a hidden `pythonw` process that immediately failed to bind, while the operator only saw delayed launcher failure. That contradicts the no-duplicate/no-stale-runtime launcher contract.
Required fix:
- Represent stale-runtime stop failure as a blocked launch, not as "no existing backend"; exit nonzero before saving a replacement `instance.json` or trying to bind the port.
Fix evidence:
- Added `LaunchBlockedError` in `python_app/run.py`.
- `active_instance_url()` now raises `LaunchBlockedError` when a non-reusable backend remains alive and cannot be stopped.
- `main()` exits nonzero on `LaunchBlockedError` instead of attempting to start another backend.
Verification:
- `scripts/test_runtime_currentness.py` now includes `test_stale_backend_stop_failure_blocks_launch`.
- Focused runtime-currentness tests passed: 8 tests.

### 2026-06-25 - Goal continuation finding: AUDIT-025 pre-live app-data backup was planned but not operator-runnable
Status: Fixed locally, not executed against real app data
Evidence:
- The live deployment plan required backing up `%LOCALAPPDATA%\AlpacaPaperTrader\python-settings.json`, `instance.json`, and day-tape data before live restart/replacement.
- The stable checkout did not have a dedicated command that performed that backup consistently without printing credential contents.
Impact:
- The live cutover step still depended on manual copying, increasing the chance of missing replay/day-tape/dashboard-cache state or accidentally exposing sensitive data in output.
Required fix:
- Add a local pre-live backup command with dry-run default and explicit `--execute` for approved cutovers.
Fix evidence:
- Added `scripts/pre_live_backup.py`.
- Dry-run mode prints source/target paths plus file and directory counts/sizes only; it does not print settings contents, account IDs, or credentials.
- Execute mode copies `python-settings.json`, `instance.json`, `dashboard-cache.json`, `replay`, and `day-tape` into `.runtime\pre-live-deploy-backups\<timestamp>`.
- README now documents the dry-run and approved `--execute` flow.
Verification:
- `tests/test_pre_live_backup.py` covers dry-run/no-copy behavior and execute-copy behavior using synthetic app data.
- Real app-data dry run completed without copying: planned backup was 8.7 KB settings, 231 B `instance.json`, 9.4 KB dashboard cache, 24 replay files / 55.6 MB, and 10 day-tape files / 12.8 GB.

### 2026-06-25 - Goal continuation finding: AUDIT-026 strategy refresh could trade from an old top-volume universe
Status: Fixed locally, not live until approved restart/replacement
Evidence:
- `TraderManager.refresh_account()` called `shared_historical_bars_for()` and `TraderEngine.refresh()` without first refreshing the top-volume universe.
- `TraderEngine.refresh()` builds `entry_symbols = self.trading_symbols()` from the current in-memory `top_volume_symbols`.
- The background loop refreshed the dashboard top-volume data only when `_last_dashboard_refresh` exceeded `TOP_VOLUME_CACHE_SECONDS`; the strategy refresh loop could therefore keep evaluating an older candidate universe.
Impact:
- The app could be otherwise healthy and still enter from an old top-volume set, weakening the contract that new entries come from the current Alpaca top-25 volume universe.
Required fix:
- Before any connected account strategy refresh, refresh the shared Alpaca most-active universe through one source engine, sync it to all accounts, and only then build shared bars / entry symbols.
- Keep scan cadence separate from strategy comparison knobs; this is operational data freshness, not a strategy parameter.
Fix evidence:
- Added `TraderManager.refresh_trading_universe_for()`.
- `refresh_account()` now calls `refresh_trading_universe_for(engine)` before shared bars and `engine.refresh()`.
- Reduced top-volume cache window to 60 seconds and force refresh cooldown to 30 seconds so the universe is kept current without per-account duplicate screener calls.
Verification:
- `MarketStreamBaselineTests.test_account_refresh_updates_top_volume_before_strategy_symbols` proves the source refresh happens before strategy refresh and syncs the top-volume symbols to the target account.
- `MarketStreamBaselineTests.test_top_volume_cache_is_short_enough_for_live_trading_refresh` covers the freshness bound.
- Focused market-stream/top-volume baseline tests passed: 7 tests.

### 2026-06-25 - Goal continuation finding: AUDIT-027 desktop shortcut verification was not reusable
Status: Fixed locally, actual shortcut inspected without launching
Evidence:
- The goal contract requires launcher verification through the desktop shortcut/VBS path.
- `scripts/test_runtime_currentness.py` covered VBS health-currentness behavior but did not cover the PowerShell shortcut creator or provide a reusable read-only check for the real `.lnk` file.
- A read-only COM inspection of the current desktop shortcut found it points to `C:\Windows\System32\wscript.exe`, passes `"C:\Users\solo leveling\Documents\alpaca trading app\Launch Alpaca Paper Trader.vbs"` as arguments, and uses the repo folder as working directory.
Impact:
- The launch path could regress from the no-window VBS route back to a terminal-visible or wrong-folder route without a focused regression test.
Required fix:
- Add source-level coverage for the desktop shortcut creator and hidden VBS launch behavior.
- Add an operator-runnable shortcut verifier that reads the actual `.lnk` metadata without launching the app.
Fix evidence:
- Added `scripts/verify_desktop_shortcut.py`.
- Added regression coverage for `Create-DesktopShortcut.ps1`, hidden `pythonw --no-browser` VBS startup, Edge `--app=` mode, and verifier validation logic.
- README now documents the shortcut verifier command.
Verification:
- Focused runtime-currentness tests passed: 11 tests.
- `scripts/verify_desktop_shortcut.py --json` inspected the actual desktop shortcut without launching the app and returned `ok: true`.

### 2026-06-25 - Goal continuation verification summary
Status: Offline repair checks passed; live replacement still pending approval
Evidence:
- `scripts/run_regression_tests.py` passed 49 tests.
- Python compile passed for `python_app` and `scripts`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts\verify_desktop_shortcut.py --json` returned `ok: true` for the actual desktop shortcut and confirmed the `wscript.exe` to VBS path, repo working directory, and icon.
- `scripts\pre_live_backup.py` dry-run completed against real app data without copying or printing contents: settings, `instance.json`, dashboard cache, replay, and day-tape were all included in the planned backup.
- A bounded `scripts\day_tape_backtest.py --days 1 --max-events 50000` run completed read-only with `selection_engine: app_engine`, fixed replay sizing harness, 230 evaluations, 6,900 rejected candidate checks, and zero parse errors.
- Read-only live `/api/health` still reports the backend reachable at `http://127.0.0.1:8765` but `current=False`, `status=stale`, and PID `11068`.
Impact:
- The current disk code is offline-clean and the desktop shortcut metadata is correct, but the live desktop app still cannot satisfy the no-stale-runtime and current-backend acceptance items until an approved backup/restart/relaunch loads the current source.
Verification still needed after approval:
- Execute the pre-live backup.
- Relaunch through the desktop shortcut/VBS path.
- Confirm one active backend on `http://127.0.0.1:8765`, current `/api/health`, retained `instance.json`, all saved accounts loaded, Daily P/L values are real/not false zero, sizing modes are conflict-free, runtime diagnostics are clean or actionable, and day-tape continuity is preserved.

### 2026-06-25 - Goal continuation finding: AUDIT-028 post-relaunch contract verification was still manual
Status: Fixed locally, live result currently fails until approved relaunch
Evidence:
- The acceptance contract requires proof across launcher, backend, account loading, Daily P/L, sizing, top-volume source, runtime diagnostics, and `instance.json`.
- Before this pass, the repo had separate checks for shortcut metadata, regression tests, layout, and backup dry-run, but no single sanitized read-only command that could verify the live app after desktop relaunch without exposing account identifiers.
Impact:
- Live cutover could still end with scattered evidence and incomplete proof, especially around all three accounts, Daily P/L source math, sizing conflicts, and top-volume cache/source.
Required fix:
- Add a read-only live verifier that queries only local app endpoints, summarizes booleans/counts, compares Daily P/L to account equity/last-equity source fields, checks sizing-mode exclusivity, validates the desktop shortcut, checks `instance.json`, checks the preferred backend URL/currentness, and verifies the top-volume source/cache.
- Keep output sanitized: no API keys, secret keys, account IDs, or account names.
Fix evidence:
- Added `scripts/verify_live_contract.py`.
- Added `tests/test_live_contract_verifier.py`, including a regression that the report does not contain synthetic account IDs or account names.
- Added `top_volume_source` to `dashboard_state()` with source `alpaca_most_actives_volume`, so post-relaunch verification can distinguish the fixed Alpaca screener path from an old/stale backend.
- README now documents the post-relaunch verifier command.
Verification:
- Focused verifier tests passed.
- Full `scripts/run_regression_tests.py` passed 51 tests.
- `scripts/verify_live_contract.py` against the current running app failed as expected because live is still stale: `backend.current=False`, two repo launcher processes were found, `top_volume.source` is missing, and `top_volume.cache_seconds=600`.
- The same live verifier confirmed 3 accounts were readable, top-volume rows existed, and account Daily P/L/sizing checks were inspectable without printing account identifiers.

### 2026-06-25 - Goal continuation finding: AUDIT-029 live cutover sequence needed one guarded command
Status: Fixed locally, dry-run only; execute still requires approval
Evidence:
- The live verifier found two repo launcher processes: one `.venv\Scripts\pythonw.exe` process and one system Python 3.12 `pythonw.exe` process, both running this repo's `python_app\run.py --no-browser`. PID `11068` is the backend serving `/api/health`.
- The live app remains stale until the old process set is deliberately replaced, but the safe sequence requires backup before stop/relaunch and post-launch verification.
Impact:
- Without a single guarded command, the live replacement could be done out of order, skip the backup, stop the wrong process, or relaunch without running the contract verifier.
Required fix:
- Add a dry-run-first coordinator that performs the approved sequence only when explicitly run with `--execute`: pre-live backup, validate desktop shortcut, stop only this repo's `python_app\run.py` launcher processes, launch through the desktop shortcut, then wait for the sanitized live verifier to pass.
Fix evidence:
- Added `scripts/live_cutover.py`.
- Added `tests/test_live_cutover.py`, covering that dry-run does not stop or launch and that execute mode orders backup, stop, launch, and verifier calls.
- README now documents the dry-run and `--execute` live cutover command.
Verification:
- `scripts/live_cutover.py` dry-run completed without stopping or launching anything. It printed the planned backup scope and the current repo launcher PIDs `12716` and `11068`.
- Full `scripts/run_regression_tests.py` passed 53 tests.
- Python compile, `node --check`, `git diff --check`, isolated smoke, and layout checks passed.
Remaining approval gate:
- Do not run `scripts/live_cutover.py --execute` until the user explicitly approves stopping/relaunching the live local backend after backup.

### 2026-06-25 - Goal continuation finding: AUDIT-030 backup/cutover preflight needed disk and process-scan guards
Status: Fixed locally, dry-run only; execute still requires approval
Evidence:
- The real app-data backup plan is large because day-tape data is included: current dry-run reports 12.8 GB planned.
- The previous backup command did not check destination free space before execute mode.
- A live verifier run immediately after smoke checks briefly reported an extra repo launcher process, but a direct process inspection showed only the two long-running `--no-browser` processes. The process scanner needed to ignore transient `python_app\run.py --smoke` checks.
Impact:
- An approved live cutover could have stopped the backend after starting a backup that could not fit on disk.
- A transient smoke/import check could falsely fail the single-backend verifier, making live verification noisy.
Required fix:
- Add destination disk-space reporting and an execute-mode abort before copying if the planned backup is larger than available free space.
- Filter `--smoke` rows out of active backend process scanning while still counting real `python_app\run.py` launcher processes.
Fix evidence:
- `scripts/pre_live_backup.py` now prints planned backup total and available destination disk space, and refuses execute mode before copying when space is insufficient.
- `scripts/verify_live_contract.py` now parses process rows and excludes `--smoke` checks.
- Added regression coverage for insufficient backup disk space and smoke-process filtering.
Verification:
- Focused backup/cutover tests passed.
- Real `scripts/pre_live_backup.py` dry-run reported 12.8 GB planned and 103.5 GB available.
- Real `scripts/live_cutover.py` dry-run reported the same backup preflight and the two current long-running PIDs `12716` and `11068`.
- Real `scripts/verify_live_contract.py` now reports the true two-process duplicate condition, not a transient smoke-process count.

### 2026-06-25 - Goal continuation finding: AUDIT-031 Daily P/L verification needed rendered UI proof
Status: Fixed locally and verified against current live UI; live backend still stale
Evidence:
- The contract requires P/L verification to check actual displayed values against live/account source data.
- Backend state and regression tests already covered Daily P/L source math, but there was no headless browser check proving the rendered metric cards matched `/api/state`.
Impact:
- A backend could return correct Daily P/L fields while the browser still displayed stale/default values, and the previous verifier set would not catch that user-visible failure.
Required fix:
- Add a rendered UI verifier that opens the app in a temporary headless Edge/Chrome profile, reads the actual DOM metric cards, and compares them against `/api/state` without printing account IDs, account names, API keys, or secrets.
- Include the rendered UI verifier in the approved cutover execute path after the live API contract verifier passes.
Fix evidence:
- Added `scripts/verify_ui_display.py`.
- Added `tests/test_ui_display_verifier.py`, including a regression that the report does not contain synthetic account IDs or names and that a rendered Daily P/L mismatch fails.
- Updated `scripts/live_cutover.py` so execute mode runs the rendered UI verifier after `verify_live_contract.py`.
- README now documents `scripts/verify_ui_display.py` and the cutover sequence now waits for both API and rendered UI verifiers.
Verification:
- `scripts/verify_ui_display.py` passed against the current live UI: it rendered 3 account cards, saw the runtime warning banner, and matched equity, Daily P/L, Daily P/L session detail, realized P/L, realized P/L session detail, buying power, cash, last refresh, and the active account-card Daily P/L to `/api/state`.
- Full `scripts/run_regression_tests.py` passed 57 tests.
- Python compile, `node --check`, `git diff --check`, isolated smoke, layout check, and cutover dry-run passed.
Remaining live gate:
- `scripts/verify_live_contract.py` still fails until approved live cutover because `/api/health` is stale, two repo launcher processes remain, and the running backend still exposes old top-volume source/cache behavior.

### 2026-06-25 - Goal continuation finding: AUDIT-032 acceptance status was still scattered across multiple commands
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The contract has many acceptance gates: desktop launcher, backend currentness, `instance.json`, all accounts, backend Daily P/L, rendered UI Daily P/L, sizing modes, top-volume universe, runtime diagnostics, and regressions.
- Before this pass, evidence existed in separate commands, but there was no single sanitized status command that grouped those gates into clear pass/fail categories for the final cutover decision.
Impact:
- It was still possible to claim partial success from one verifier while missing another acceptance gate, especially the split between backend API evidence, rendered UI evidence, and regression evidence.
Required fix:
- Add a read-only aggregator that runs the sanitized live verifier and rendered UI verifier, optionally runs the regression harness, and reports category-level pass/fail status without printing credentials or account identifiers.
Fix evidence:
- Added `scripts/contract_status.py`.
- Added `tests/test_contract_status.py` to pin the category mapping, including the expected current-live failures for stale backend currentness and old top-volume behavior.
- README now documents the aggregate status command.
Verification:
- `scripts/run_regression_tests.py` passed 58 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/verify_ui_display.py` passed against the current live UI: 3 account cards rendered, the runtime warning banner was visible, and rendered values matched `/api/state`.
- `scripts/live_cutover.py` dry-run completed without stopping or launching anything, confirmed a 12.8 GB backup plan with 103.5 GB free, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
- `scripts/verify_live_contract.py` failed as expected before cutover: `backend.current=False`, two repo launcher processes remain, `top_volume.source` is missing, and `top_volume.cache_seconds=600`.
- `scripts/contract_status.py --include-regression` failed as expected before cutover, with `backend_currentness` and `top_volume_universe` as the only failed categories; desktop launcher, `instance_json`, accounts, backend Daily P/L, rendered UI Daily P/L, sizing modes, runtime diagnostics, and regression harness all passed.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass.

### 2026-06-25 - Goal continuation finding: AUDIT-064 Daily P/L used account-field subtraction instead of Alpaca portfolio history
Status: Fixed locally; live restart and post-relaunch verification required
Evidence:
- A read-only comparison against Alpaca portfolio history for the three saved paper accounts showed the current app-subtraction values did not match the portfolio-history `profit_loss` source.
- `python_app/alpaca_desktop/engine.py::TraderEngine.refresh()` still computed Daily P/L as `equity - last_equity`.
- `scripts/verify_live_contract.py::check_daily_pl()` validated that same subtraction through `daily_pl_source_math`, so the verifier could pass while proving the wrong source.
Impact:
- The UI could show zero, stale, or wrong Daily P/L values even when Alpaca's account/session portfolio history showed a real gain or loss.
- A tiny non-zero percent could round to `0.00%`, violating the contract that Daily P/L must not show zero percent unless the account is actually flat.
Required fix:
- Use `TradingClient.get_portfolio_history()` with the account market-clock session date as the Daily P/L source.
- Mark Daily P/L unavailable when portfolio history is unavailable instead of falling back to account-field subtraction.
- Expose a `daily_pl_source` contract field and make the live verifier fail when the source is not Alpaca portfolio history.
Fix evidence:
- `TraderEngine.refresh()` now populates Daily P/L from `portfolio_history_daily_pl_payload()`, which reads Alpaca portfolio-history `profit_loss`, `profit_loss_pct`, and `base_value`.
- `standardized_account_metrics()` now rejects account-field-only Daily P/L payloads and returns unavailable Daily P/L unless `daily_pl_source` is `alpaca_portfolio_history`.
- `signed_percent_value()` now preserves small non-zero percentages with extra decimal places so non-flat accounts do not display as `0.00%`.
- `scripts/verify_live_contract.py` now checks `daily_pl_source` and `daily_pl_percent_source` instead of `equity - last_equity`.
- `scripts/contract_status.py` now maps the Daily P/L category to those portfolio-history source checks.
Verification:
- Focused P/L and verifier tests passed: `python -m unittest tests.test_regression_baselines.ProfitLossContractBaselineTests tests.test_live_contract_verifier tests.test_contract_status -v`.
Remaining live gate:
- Restart the local backend with the guarded cutover path, then run live API and rendered UI verification against the restarted process.

### 2026-06-25 - Goal continuation finding: AUDIT-065 day-tape backtester was not integrated into the app UI
Status: Fixed in `codex/alpaca-backtest-ui` worktree; stable cutover still pending
Evidence:
- The goal contract requires replay/backtest evidence before strategy changes go live.
- `scripts/day_tape_backtest.py` could run the collected day tape through the app-engine strategy boundary, but the desktop app only exposed a passive Replay event table.
- There was no in-app control to choose a tape window, run the backtest, and inspect accepted trades, rejected candidates, or source/evaluation checks.
Impact:
- Backtest evidence existed as a developer script rather than an operator workflow inside the GUI, so it was not easy to use while running the desktop app.
- The app could still be described as missing part of the goal contract even though the engine-backed replay code existed outside the UI.
Required fix:
- Add a read-only app endpoint that runs the existing day-tape backtester against collected local tape with `selection_engine=app_engine`.
- Add Replay-tab controls and result tables for the fixed sizing harness, top-volume source/evaluation checks, accepted trades, and rejected-candidate samples.
- Keep the UI path read-only: no Alpaca API calls, no order submission, and no stable app-data writes from worktree tests.
Fix evidence:
- Added `POST /api/backtest/day-tape`, backed by `scripts/day_tape_backtest.py`.
- Added Replay-tab controls for days, max events, latest-window selection, and a Run Backtest button.
- Added summary cards and result tables for checks, accepted trades, and rejected samples.
- Added focused endpoint and frontend surface tests.
Verification:
- Focused endpoint/frontend/backtester tests passed: `python -m unittest tests.test_backtest_ui_api tests.test_frontend_state_layout tests.test_day_tape_backtest -v`.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app/static/app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
Remaining live gate:
- Run focused checks in the worktree, then prepare a guarded stable checkout cutover only after the first UI slice passes.

### 2026-06-25 - Goal continuation finding: AUDIT-061 max-position capacity was still part of candidate selection
Status: Fixed and deployed live; full replay acceptance still pending market-open strategy scans
Evidence:
- `python_app/alpaca_desktop/engine.py::entry_candidate()` returned `Hold (max positions)` before computing and storing the candidate score when `open_position_count >= config.max_open_positions`.
- The refresh loop already has a post-ranking max-position capacity check before calling `apply_strategy()`, and `apply_strategy()` also blocks order submission when max positions are full.
Expected behavior:
- Account size, buying power, max trade dollars, exposure, max open positions, and share price must not drive stock selection or ranking.
- Capacity and sizing limits should stop entries only after the indicator-driven candidate ranking has been built.
Impact:
- When the account was already at its position limit, the engine could skip scoring otherwise valid top-volume candidates, weakening replay evidence and contradicting the contract's separation between stock selection and sizing/capacity.
Required fix:
- Remove the max-position block from `entry_candidate()` while preserving the existing post-ranking and order-path capacity gates.
- Add focused regression coverage proving candidate scoring ignores sizing/capacity/share-price inputs and that `apply_strategy()` still blocks entries after ranking when capacity is full.
Fix evidence:
- Removed the pre-ranking max-position block from `TraderEngine.entry_candidate()`.
- Kept the existing post-ranking refresh-loop capacity check and the `apply_strategy()` max-position order-path guard.
- Added `StrategySelectionContractTests` proving candidate scoring ignores sizing/capacity/share-price inputs while `apply_strategy()` still blocks entries after ranking when max positions are full.
- Added `strategy_selection_contract` to `scripts/contract_status.py` and the guarded cutover aggregate, with an acceptance item for stock-selection independence from sizing/capacity.
Verification:
- Focused tests passed: `python -m unittest tests.test_regression_baselines.StrategySelectionContractTests tests.test_contract_status tests.test_live_cutover -v`.
- Focused strategy contract check passed with 19 tests covering top-volume universe, sizing/capacity separation, inverse ETF same-rule eligibility, held-position monitoring, and replay engine reuse.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- Full `scripts/run_regression_tests.py` passed 103 tests.
- `scripts/contract_status.py --include-regression --include-backtest` showed `strategy_selection_contract: ok`; before relaunch it still failed `backend_currentness` because the live backend had not loaded this source edit, and `replay_backtester` because the market was closed and no Alpaca-source strategy-scan evaluations existed yet.
- `scripts/live_cutover.py --execute --disable-auto-start-for-launch --timeout 120` backed up app data to `.runtime\pre-live-deploy-backups\20260625T040643Z`, stopped only the two repo launcher processes, relaunched from the desktop shortcut, and verified the current backend on `http://127.0.0.1:8765` with PID `11200` and one listener.
- The post-launch aggregate shows `strategy_selection_contract: ok`, `backend_currentness: ok`, and all live/UI/local categories passing except `replay_backtester`.
Remaining verification:
- Full replay acceptance still requires real market-open `strategy_scan` evaluations using `alpaca_most_actives_volume`.

### 2026-06-25 - Goal continuation finding: AUDIT-063 safe no-auto-start relaunch needed replay-capture proof
Status: Fixed locally; full replay acceptance still pending market-open strategy scans
Evidence:
- The successful guarded relaunch used `--disable-auto-start-for-launch`, leaving all three saved accounts connected but `trading_enabled=False`.
- The remaining full-acceptance gate requires market-open `strategy_scan` evaluations using `alpaca_most_actives_volume`.
Expected behavior:
- Suppressing saved paper-trading auto-start for a safe relaunch should not prevent future market-open day-tape snapshots from proving the top-volume replay universe.
- The backtester should be able to consume market-open `strategy_scan` context even when the live app did not submit paper entries.
Impact:
- Without focused proof, the safe no-auto-start path could leave the app live and healthy but unable to collect the evidence needed to close the replay/backtester acceptance item.
Required fix:
- Add regression coverage proving `record_day_tape_scan()` writes Alpaca top-volume context on market-open scans even when `should_trade=False`.
- Add replay coverage proving a disabled-trading `strategy_scan` still evaluates the embedded Alpaca top-volume universe through the app-engine backtester path.
- Include the disabled-trading replay test in the named `strategy_selection_contract` aggregate category.
Fix evidence:
- Added `test_market_open_strategy_scan_records_context_when_trading_disabled` to `tests/test_regression_baselines.py`.
- Added `test_disabled_trading_strategy_scan_still_proves_replay_universe` to `tests/test_day_tape_backtest.py`.
- Added the disabled-trading replay test to `scripts/contract_status.py::run_strategy_contract_check()`.
Verification:
- Focused tests passed: `python -m unittest tests.test_regression_baselines.MarketStreamBaselineTests tests.test_day_tape_backtest tests.test_contract_status -v`.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
Remaining verification:
- Full replay acceptance still requires real market-open `strategy_scan` evaluations using `alpaca_most_actives_volume`.

### 2026-06-25 - Goal continuation finding: AUDIT-062 cutover had no safe process-only auto-start suppression
Status: Fixed and deployed live; full replay acceptance still pending market-open strategy scans
Evidence:
- `scripts/live_cutover.py` correctly aborted execute mode when saved accounts had `auto_start_trading` enabled unless `--allow-auto-start` was supplied.
- The backend already honors `ALPACA_TRADER_DISABLE_AUTO_START=1` in `python_app/alpaca_desktop/server.py::auto_connect_saved_accounts()`, but the cutover command could not pass that safer process-only override through the desktop relaunch path.
Expected behavior:
- A guarded live restart should be possible without editing saved credentials/settings and without approving saved paper-trading auto-start behavior.
- If saved auto-start is enabled, the operator should be able to choose either explicit normal auto-start approval or a process-level launch override that leaves saved settings unchanged.
Impact:
- Loading current code into the live gateway was blocked by saved auto-start settings even though a safer no-settings-change runtime guard already existed.
Required fix:
- Add a cutover execute option that sets `ALPACA_TRADER_DISABLE_AUTO_START=1` only around desktop shortcut launch, restores the current process environment afterward, and documents the behavior.
Fix evidence:
- Added `--disable-auto-start-for-launch` to `scripts/live_cutover.py`.
- The option sets `ALPACA_TRADER_DISABLE_AUTO_START=1` only around desktop shortcut launch and restores the current process environment afterward.
- The cutover command now verifies the override after launch by inspecting sanitized account states and failing if any expected account returns with `trading_enabled=True`.
- README documents the two execute choices: `--allow-auto-start` for explicit normal saved auto-start behavior, or `--disable-auto-start-for-launch` for a process-only no-settings-change override.
Verification:
- Focused cutover tests passed: `python -m unittest tests.test_live_cutover -v`.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/live_cutover.py --disable-auto-start-for-launch` dry-run passed backup space, shortcut, process, and saved auto-start preflight checks without stopping or launching anything.
- `scripts/live_cutover.py --execute --disable-auto-start-for-launch --timeout 120` completed successfully: backup path `.runtime\pre-live-deploy-backups\20260625T040643Z`, backend current on PID `11200`, 3 accounts loaded, 25 top-volume rows, rendered UI verified, and post-launch auto-start override verified with `trading_enabled_accounts=none`.
Remaining verification:
- Full replay acceptance still requires real market-open `strategy_scan` evaluations using `alpaca_most_actives_volume`.

### 2026-06-25 - Goal continuation finding: AUDIT-048 desktop restart could delete fresh instance file and overcount launcher wrappers
Status: Fixed and verified live; fresh replay tape still pending for full acceptance
Evidence:
- After the approved guarded restart, `/api/health` reported the current repo backend on `http://127.0.0.1:8765`, but `C:\Users\solo leveling\AppData\Local\AlpacaPaperTrader\instance.json` was missing.
- The VBS launcher called `DeleteInstanceIfUrl` when `/api/health` returned no text. During startup, that empty response can mean the backend is still warming up, not that the saved instance is stale.
- The live verifier counted both the virtualenv `pythonw.exe` launcher process and its child system `pythonw.exe` backend process as duplicate repo launcher processes, even though only the child owned the listening `127.0.0.1:8765` socket.
Expected behavior:
- The launcher should keep waiting on an empty startup health response and preserve `instance.json` while the backend is coming up.
- Duplicate-backend verification should fail on multiple listening backends, not on a single backend wrapped by the Windows virtualenv launcher.
Files:
- `Launch Alpaca Paper Trader.vbs`
- `scripts/verify_live_contract.py`
- `scripts/contract_status.py`
- `scripts/test_runtime_currentness.py`
- `tests/test_live_contract_verifier.py`
- `tests/test_contract_status.py`
Required verification:
- Focused launcher/verifier tests must pass.
- Regression harness and Python compile must pass.
- A post-fix desktop-shortcut restart must retain `instance.json`, report one listening backend on `127.0.0.1:8765`, and keep `/api/health.pid` equal to the listener PID.
Fix evidence:
- `Launch Alpaca Paper Trader.vbs` now treats an empty startup health response as "keep waiting" and does not delete `instance.json` unless a responding backend proves stale.
- `scripts/verify_live_contract.py` now separately collects the listening PID for the expected backend URL and uses that listener set for duplicate-backend verification.
- `scripts/contract_status.py` now includes the launcher startup guard in the desktop-launcher category.
- Focused tests passed: `python -m unittest scripts.test_runtime_currentness tests.test_live_contract_verifier tests.test_contract_status -v`.
- Python compile passed for `python_app`, `scripts`, and `tests`; `node --check python_app\static\app.js` passed; `git diff --check` had only LF-to-CRLF warnings.
- Full regression harness passed 80 tests.
- Guarded live cutover completed through the desktop shortcut after app-data backup `C:\Users\solo leveling\Documents\alpaca trading app\.runtime\pre-live-deploy-backups\20260625T030902Z`.
- Post-launch live verifier passed with health current, PID `10712`, one listener `[10712]`, three accounts loaded, top-volume rows `25`, and no failures.
- Rendered UI verifier passed with three rendered account cards and no visible runtime warning.
- Follow-up live verifier still passed after relaunch, and `C:\Users\solo leveling\AppData\Local\AlpacaPaperTrader\instance.json` remained present.
Remaining verification:
- Aggregate contract status now passes every live/local category except `replay_backtester`, because the latest bounded day tape still contains pre-cutover `sp500_snapshot_volume` source rows and zero `alpaca_most_actives_volume` replay evaluations. A fresh market-hours tape is still required for full replay acceptance.

### 2026-06-25 - Goal continuation finding: AUDIT-049 aggregate replay verifier read the start of large tape files
Status: Fixed locally; full replay acceptance still pending market-open strategy scans
Evidence:
- `scripts/contract_status.py --include-regression --include-backtest` used `scripts/day_tape_backtest.py` with `max_events=50000`, but the backtester consumed the first 50,000 events in the selected tape file.
- On a large same-day tape, post-cutover `alpaca_most_actives_volume` snapshots were near the end of the file, so the aggregate replay category could miss the current deployment evidence and report only older pre-cutover rows.
Expected behavior:
- Post-deployment aggregate replay verification should inspect a bounded latest-event window by default, while preserving a from-start mode for historical diagnostics.
- The replay gate should remain strict: Alpaca-source top-volume snapshots are not enough to pass until a market-open `strategy_scan` evaluates candidates against that source.
Files:
- `scripts/day_tape_backtest.py`
- `scripts/contract_status.py`
- `tests/test_day_tape_backtest.py`
- `tests/test_contract_status.py`
Fix evidence:
- `scripts/day_tape_backtest.py` now supports `latest_events=True` and `--latest-events`, reading the latest bounded event window in chronological order.
- `scripts/contract_status.py` now uses latest-window replay by default for the replay/backtester category and exposes `--backtest-from-start` for older diagnostics.
- The backtester summary now reports `top_volume_snapshots_by_source`, and the aggregate status reports both expected-source snapshot count and expected-source evaluation count.
- Focused replay/status tests passed: `python -m unittest tests.test_day_tape_backtest tests.test_contract_status -v`.
- Aggregate status now reports latest-window evidence with fresh `alpaca_most_actives_volume` snapshots captured, but still fails replay acceptance because no market-open `strategy_scan` has evaluated that source yet.
Remaining verification:
- Full replay acceptance still requires fresh market-hours strategy scans using `alpaca_most_actives_volume`, then `scripts\contract_status.py --include-regression --include-backtest` should pass the replay category.

### 2026-06-25 - Goal continuation finding: AUDIT-050 strategy scan tape omitted its top-volume universe context
Status: Fixed and deployed live; full replay acceptance still pending market-open strategy scans
Evidence:
- `record_day_tape_scan()` writes market-open `strategy_scan` payloads with account/config/strategy rows, but not the current top-volume source, symbols, or rows.
- `scripts/day_tape_backtest.py` carries the candidate universe forward from prior `top_volume_snapshot` events. A bounded latest-event replay can begin at a `strategy_scan` after the relevant snapshot, leaving the backtester without direct evidence of the universe that scan used.
Expected behavior:
- Each market-open `strategy_scan` should include sanitized top-volume source and current top-25 universe context so replay evidence is self-contained enough for bounded post-deployment checks.
- The backtester should prefer scan-embedded top-volume context when present and still support older tapes that only have separate `top_volume_snapshot` rows.
Files:
- `python_app/alpaca_desktop/engine.py`
- `scripts/day_tape_backtest.py`
- `tests/test_day_tape_backtest.py`
- `tests/test_regression_baselines.py`
Required verification:
- Unit tests must prove scan-embedded top-volume context is written without secrets and consumed by the backtester.
- Aggregate status must still require actual Alpaca-source strategy evaluations before passing replay acceptance.
Fix evidence:
- `record_day_tape_scan()` now writes `symbol_source`, `top_volume_source`, `top_volume_updated_at`, `top_volume_symbols`, and sanitized `top_volume_rows` into market-open `strategy_scan` payloads.
- `scripts/day_tape_backtest.py` now applies scan-embedded top-volume context before evaluating a `strategy_scan`, while keeping support for older tapes that only have separate `top_volume_snapshot` rows.
- Backtest summaries now distinguish standalone top-volume snapshots from all top-volume contexts, including scan-embedded contexts.
- `scripts/contract_status.py` now checks top-volume context availability and still requires actual evaluations from `alpaca_most_actives_volume` before the replay category can pass.
- Replay source accounting now labels evaluations by the actual replay universe. The fixed harness forces top-volume replay for contract checks, and tests cover scan-embedded context passing without a standalone snapshot.
- Focused recorder/replay/status tests passed: `python -m unittest tests.test_day_tape_backtest tests.test_contract_status tests.test_regression_baselines.MarketStreamBaselineTests -v`.
- Focused replay/status tests passed after the stricter source-accounting patch: `python -m unittest tests.test_day_tape_backtest tests.test_contract_status -v`.
- Python compile passed for `python_app`, `scripts`, and `tests`; full regression harness passed 86 tests; `git diff --check` had only LF-to-CRLF warnings.
- Guarded live cutover completed through the desktop shortcut after app-data backup `C:\Users\solo leveling\Documents\alpaca trading app\.runtime\pre-live-deploy-backups\20260625T032051Z`.
- Post-launch live verifier passed with health current, PID `16136`, one listener `[16136]`, three accounts loaded, top-volume rows `25`, and no failures.
- Rendered UI verifier passed with three rendered account cards and no visible runtime warning.
Remaining verification:
- Aggregate contract status still fails only `replay_backtester` because current Alpaca market clocks are closed and the latest tape has fresh `alpaca_most_actives_volume` context but zero market-open strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-051 replay-pending status did not include live clock evidence
Status: Fixed locally
Evidence:
- `scripts/contract_status.py --include-regression --include-backtest` correctly failed `replay_backtester` while waiting for market-open `strategy_scan` evaluations, but the failing category did not show the live account market-clock state that explains why no valid scan can be recorded yet.
- `scripts/verify_live_contract.py` checked that each account exposed a market clock but only reported a generic detail string.
Expected behavior:
- The failing replay category should include sanitized live market-clock evidence so the remaining acceptance gate is auditable from one command.
Files:
- `scripts/verify_live_contract.py`
- `scripts/contract_status.py`
- `tests/test_live_contract_verifier.py`
- `tests/test_contract_status.py`
Fix evidence:
- Market-clock verifier details now include `is_open`, `status`, and `session` without account identifiers or credentials.
- When the replay/backtester category fails, aggregate status appends the three account market-clock details to the replay evidence.
- Focused verifier/status tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v`.
- Aggregate status now shows `account_1.market_clock`, `account_2.market_clock`, and `account_3.market_clock` as closed directly under the failing `replay_backtester` category.
Remaining verification:
- Full replay acceptance still requires a real market-open `strategy_scan` evaluated against `alpaca_most_actives_volume`.

### 2026-06-25 - Goal continuation finding: AUDIT-052 aggregate status omitted rendered stale-warning check
Status: Fixed locally
Evidence:
- `scripts/verify_ui_display.py` emits checks for rendered runtime-warning state, including `ui.stale_runtime_warning_hidden` when `/api/health.current=True`.
- `scripts/contract_status.py` only used rendered UI checks for Daily P/L fields and did not include the runtime-warning checks in any aggregate category.
Expected behavior:
- The aggregate contract status should explicitly include the rendered runtime-warning state because the acceptance contract requires normal launch not to show stale runtime warnings.
Files:
- `scripts/contract_status.py`
- `tests/test_contract_status.py`
- `README.md`
Required verification:
- Aggregate status tests must prove a current backend with a stale runtime warning visible fails a dedicated rendered runtime-warning category.
- Full regression must pass after the category mapping change.
Fix evidence:
- `scripts/contract_status.py` now includes a `runtime_warning_rendered` category using `ui.runtime_warning_visible` plus the appropriate stale-runtime warning visibility check from `scripts/verify_ui_display.py`.
- `tests/test_contract_status.py` now proves a current backend with a stale runtime warning visible fails that aggregate category.
- Focused status tests passed: `python -m unittest tests.test_contract_status -v`.
- Full regression harness passed 90 tests; Python compile passed; `git diff --check` had only LF-to-CRLF warnings.

### 2026-06-25 - Goal continuation finding: AUDIT-053 aggregate status did not map categories to current acceptance bullets
Status: Fixed locally
Evidence:
- `scripts/contract_status.py` reported technical categories but did not directly map them to the objective file's current acceptance standard bullets.
- That made final completion auditing depend on a manual mapping from categories to acceptance items.
Expected behavior:
- The aggregate status should include a sanitized acceptance summary that maps the current acceptance standard to existing evidence categories without weakening any underlying gate.
Files:
- `scripts/contract_status.py`
- `tests/test_contract_status.py`
Fix evidence:
- `scripts/contract_status.py` now builds an `acceptance` section with items for shortcut launch, no visible terminal/self-contained launcher behavior, expected backend URL, stale-warning absence, single active backend, retained `instance.json`, account loading/surfaces, Daily P/L correctness, sizing-mode conflicts, Alpaca top-25 universe, backtester strategy alignment, and regression checks.
- The top-level command `ok` still reflects requested categories; the new `summary.acceptance_ok` and `acceptance` list show whether the full current acceptance standard is proven.
- `tests/test_contract_status.py` now covers acceptance mapping, including missing regression/backtest evidence when those checks are not requested.
- A live `scripts\contract_status.py --include-regression --include-backtest` run now shows all acceptance items passing except `backtester_uses_same_strategy_logic`, which is still waiting on real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-054 replay-pending clock evidence omitted next open/close
Status: Fixed locally
Evidence:
- `scripts/contract_status.py --include-regression --include-backtest` reported the three account market clocks as closed under the failing `replay_backtester` category, but did not include the next Alpaca open/close time already exposed by `/api/state`.
- The remaining acceptance blocker depends on a real market-open `strategy_scan`, so the status output should show when the next eligible market window begins.
Expected behavior:
- The sanitized market-clock detail should include `is_open`, `status`, `session`, `next_open`, and `next_close` without account identifiers, credentials, or raw settings.
Files:
- `scripts/verify_live_contract.py`
- `tests/test_live_contract_verifier.py`
- `tests/test_contract_status.py`
Fix evidence:
- `scripts/verify_live_contract.py` now includes `next_open` and `next_close` in per-account market-clock check details when the backend exposes them.
- `tests/test_live_contract_verifier.py` covers the added market-clock detail fields.
- `tests/test_contract_status.py` covers that a replay-pending aggregate includes next-open evidence in the replay failure category.
Verification:
- Focused verifier/status tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v` ran 20 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- Live `scripts/verify_live_contract.py` passed with one listener, three accounts loaded, top-volume rows `25`, and no failures.
- `scripts/contract_status.py --include-regression --include-backtest` still fails only `replay_backtester`; the failure now includes all three closed account clocks with `next_open=Jun 25, 08:30 AM Central Daylight Time` and `next_close=Jun 25, 03:00 PM Central Daylight Time`.
Remaining verification:
- Full replay acceptance still requires a real market-open `strategy_scan` evaluated against `alpaca_most_actives_volume`.

### 2026-06-25 - Goal continuation finding: AUDIT-055 aggregate status omitted layout contract evidence
Status: Fixed locally
Evidence:
- The objective requires no whole-page horizontal overflow at normal desktop widths and says layout verification must use rendered/browser behavior where practical.
- `scripts/check_frontend_layout.py` already produced viewport evidence for 1024px, 1100px, and the launcher default width, but `scripts/contract_status.py` did not run it or include a layout category.
- `scripts/live_cutover.py --execute` also built its final aggregate without the layout gate.
Expected behavior:
- The all-up contract status and guarded cutover aggregate should include layout evidence, including no whole-page horizontal overflow and local table scrolling.
Files:
- `scripts/contract_status.py`
- `scripts/live_cutover.py`
- `tests/test_contract_status.py`
- `tests/test_live_cutover.py`
- `README.md`
Fix evidence:
- `scripts/contract_status.py` now runs `scripts/check_frontend_layout.py` by default and adds a `layout_contract` category plus `layout_no_horizontal_overflow` acceptance item.
- `scripts/live_cutover.py --execute` now includes `run_layout_check()` in its final aggregate.
- `tests/test_contract_status.py` covers the layout evidence summary and missing-layout acceptance failure.
- `tests/test_live_cutover.py` covers that execute mode passes layout evidence into the final aggregate.
- README now states that full acceptance and execute-mode aggregate status include layout evidence.
Verification:
- Focused status/cutover/frontend-layout tests passed: `python -m unittest tests.test_contract_status tests.test_live_cutover tests.test_frontend_state_layout -v` ran 21 tests.
- Standalone `scripts/check_frontend_layout.py` passed with `whole_page_horizontal_overflow=false` and `tables_scroll_locally=true` at 1024px, 1100px, and 1280px.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `layout_contract: ok` and `layout_no_horizontal_overflow: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-056 paper-only safety was not an explicit acceptance item
Status: Fixed locally
Evidence:
- The objective has a core safety boundary that the app is paper trading only.
- `scripts/verify_live_contract.py` already emitted `backend.paper_only`, and `scripts/contract_status.py` included it inside `backend_currentness`, but the acceptance list did not show a dedicated paper-only safety item.
- A final status could therefore bury the paper-only proof inside a broader backend bucket instead of making the safety boundary auditable on its own.
Expected behavior:
- The all-up contract status and guarded cutover aggregate should explicitly show paper-only broker safety as an acceptance item.
Files:
- `scripts/contract_status.py`
- `tests/test_contract_status.py`
Fix evidence:
- `scripts/contract_status.py` now adds a `paper_trading_safety` category from `backend.paper_only`.
- The acceptance list now includes `paper_trading_only`.
- `tests/test_contract_status.py` covers both the passing acceptance mapping and the failure path when the health paper-only contract is missing.
Verification:
- Focused status tests passed: `python -m unittest tests.test_contract_status -v` ran 11 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `paper_trading_safety: ok` and `paper_trading_only: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-057 aggregate status omitted app-data preservation evidence
Status: Fixed locally
Evidence:
- The objective requires saved credentials, settings, logs, day tape, replay data, and dashboard cache to be preserved.
- `scripts/pre_live_backup.py` and `scripts/live_cutover.py` already implemented the guarded backup-before-stop path, but `scripts/contract_status.py` did not include a preservation category or acceptance item.
- The all-up status could therefore show live/UI/layout/regression/replay status while omitting whether a safe backup plan covers the local app data needed before any restart.
Expected behavior:
- The aggregate contract status and guarded cutover final aggregate should include sanitized app-data preservation evidence without printing credential contents, account IDs, or setting payloads.
Files:
- `scripts/contract_status.py`
- `scripts/live_cutover.py`
- `tests/test_contract_status.py`
- `tests/test_live_cutover.py`
- `README.md`
Fix evidence:
- `scripts/contract_status.py` now adds `run_app_data_preservation_check()`, an `app_data_preservation` category, and `saved_app_data_preserved` acceptance item.
- The preservation check verifies that the backup plan covers `python-settings.json`, `instance.json`, `dashboard-cache.json`, `replay`, and `day-tape`, and that destination disk space is sufficient.
- `scripts/live_cutover.py --execute` now passes preservation evidence into its final aggregate.
- `tests/test_contract_status.py` covers complete and missing preservation plans.
- `tests/test_live_cutover.py` covers that execute mode passes preservation evidence into the final aggregate.
- README now states that full acceptance includes app-data preservation.
Verification:
- Focused status/cutover/backup tests passed: `python -m unittest tests.test_contract_status tests.test_live_cutover tests.test_pre_live_backup -v` ran 21 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `app_data_preservation: ok` and `saved_app_data_preserved: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-058 aggregate status omitted market-stream health evidence
Status: Fixed locally
Evidence:
- The objective requires live market data through Alpaca, a shared market stream with needed symbols, actionable stream errors, and no benign shutdown noise as runtime warnings.
- `scripts/verify_live_contract.py` only checked that account dashboard payloads included a `market_stream` object as part of the broad dashboard-surface check.
- `scripts/contract_status.py` did not have a dedicated market-data stream category or acceptance item.
Expected behavior:
- The live verifier and aggregate status should explicitly prove that the market-stream health surface exists, has no current error, and covers the dashboard top-volume symbols with bar subscriptions.
Files:
- `scripts/verify_live_contract.py`
- `scripts/contract_status.py`
- `tests/test_live_contract_verifier.py`
- `tests/test_contract_status.py`
- `README.md`
Fix evidence:
- `scripts/verify_live_contract.py` now emits sanitized `market_stream.surface`, `market_stream.status`, `market_stream.error`, `market_stream.dashboard_symbols`, and `market_stream.bar_symbols` checks without printing account identifiers or names.
- `scripts/contract_status.py` now adds a `market_data_stream` category and `market_data_stream_healthy` acceptance item.
- `tests/test_live_contract_verifier.py` covers stream error and subscription-count failures.
- `tests/test_contract_status.py` covers the aggregate category failure path.
- README now states that full acceptance includes market-data stream health.
Verification:
- Focused verifier/status tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v` ran 26 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- Live `scripts/verify_live_contract.py` passed with one backend listener, three accounts loaded, and no failures.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `market_data_stream: ok` and `market_data_stream_healthy: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-059 aggregate status omitted audit/build-note evidence
Status: Fixed locally
Evidence:
- The objective requires discovered defects to be logged, build notes to be retrievable for weekly rollup, and audit/build notes not to expose credentials or account IDs.
- The audit file existed and was actively maintained, but `scripts/contract_status.py` did not include an audit/build-note category or acceptance item.
- The final aggregate could therefore prove live/UI/layout/preservation/stream/regression/replay status while omitting the audit-log requirement.
Expected behavior:
- The all-up contract status and guarded cutover aggregate should include a sanitized audit-log proof that the audit file exists, contains structured AUDIT entries, includes verification language, and does not match obvious credential/account-id token patterns.
Files:
- `scripts/contract_status.py`
- `scripts/live_cutover.py`
- `tests/test_contract_status.py`
- `tests/test_live_cutover.py`
- `README.md`
Fix evidence:
- `scripts/contract_status.py` now adds `run_audit_log_check()`, an `audit_logging` category, and `audit_build_notes_retrievable` acceptance item.
- The audit check verifies structured audit terms and scans for Alpaca-key-like tokens, 32-hex tokens, and JSON-style secret assignments without printing any matched values.
- `scripts/live_cutover.py --execute` now passes audit evidence into its final aggregate.
- `tests/test_contract_status.py` covers both a structured sanitized audit file and a sensitive-token failure.
- `tests/test_live_cutover.py` covers that execute mode passes audit evidence into the final aggregate.
- README now states that full acceptance includes audit/build-note evidence.
Verification:
- Focused status/cutover tests passed: `python -m unittest tests.test_contract_status tests.test_live_cutover -v` ran 21 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `audit_logging: ok` and `audit_build_notes_retrievable: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-060 aggregate status omitted frontend state-coordination evidence
Status: Fixed locally
Evidence:
- The objective requires account switching to cancel or ignore stale async responses and settings auto-save not to write stale account data into the wrong account.
- `tests/test_frontend_state_layout.py::FrontendStateCoordinationTests` covered account-scoped request guards, stale response guards, latest-only health rendering, account-switch invalidation, and guarded auto-save behavior.
- `scripts/contract_status.py` only surfaced this through the broad regression harness rather than a dedicated acceptance category.
Expected behavior:
- The all-up contract status and guarded cutover aggregate should include a named frontend state-coordination proof for account switching and settings auto-save safety.
Files:
- `scripts/contract_status.py`
- `scripts/live_cutover.py`
- `tests/test_contract_status.py`
- `tests/test_live_cutover.py`
- `README.md`
Fix evidence:
- `scripts/contract_status.py` now adds `run_frontend_state_coordination_check()`, a `frontend_state_coordination` category, and `account_switching_async_safe` acceptance item.
- The focused check runs `tests.test_frontend_state_layout.FrontendStateCoordinationTests`.
- `scripts/live_cutover.py --execute` now includes frontend state-coordination evidence in its final aggregate.
- `tests/test_contract_status.py` covers pass/fail behavior and missing-acceptance behavior.
- `tests/test_live_cutover.py` covers that execute mode passes frontend state evidence into the final aggregate.
- README now states that full acceptance includes account-switching/autosave guards.
Verification:
- Focused status/cutover/frontend-state tests passed: `python -m unittest tests.test_contract_status tests.test_live_cutover tests.test_frontend_state_layout -v` ran 29 tests.
- Standalone focused frontend state check passed: `python -m unittest tests.test_frontend_state_layout.FrontendStateCoordinationTests -v` ran 4 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `frontend_state_coordination: ok` and `account_switching_async_safe: ok`.
Remaining verification:
- Full aggregate status still fails only `replay_backtester`, pending real market-open `alpaca_most_actives_volume` strategy-scan evaluations.

### 2026-06-25 - Goal continuation finding: AUDIT-043 held-position bars were subscribed but not ingested for strategy management
Status: Fixed locally; final live pass still requires approved cutover
Observed behavior:
- `TraderEngine.scan_symbols()` correctly included the current entry universe, held position symbols, and market proxy symbols.
- `TraderManager.market_data_symbols()` could subscribe the shared market stream to held positions outside the top-volume universe.
- `TraderEngine.ingest_market_bar()` only called `strategy_state.add_bar()` for current top-volume symbols or manual config symbols, so a held position that fell out of top 25 could receive stream bars but not update the strategy snapshot used by exit/management logic.
Expected behavior:
- New entries must remain limited to the current Alpaca top-25 volume universe unless explicitly overridden.
- Held positions must continue receiving strategy-state bars for monitoring and exits even after they leave the top-25 entry universe.
- Market proxy symbols included by `scan_symbols()` should also update their strategy history when bars arrive.
Code pointer:
- `python_app/alpaca_desktop/engine.py::TraderEngine.ingest_market_bar()`.
Impact:
- The app could satisfy the subscription side of the held-position requirement while still managing exits from stale strategy snapshots for symbols no longer in top volume.
Fix evidence:
- `TraderEngine.ingest_market_bar()` now checks the full `scan_symbols()` set before updating strategy history, preserving top-25-only entry selection while ingesting bars for held positions and market proxies.
- Added regression coverage that a held `AAPL` position outside `top_volume_symbols` updates its snapshot when a market bar arrives.
- Added regression coverage that `SPY` market-proxy bars update strategy history in top-volume mode.
Verification:
- Focused market-stream baseline tests passed: `python -m unittest tests.test_regression_baselines.MarketStreamBaselineTests -v`.
- Full regression passed: `python scripts/run_regression_tests.py` ran 75 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- JavaScript syntax check passed: `node --check python_app\static\app.js`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.

### 2026-06-25 - Goal continuation finding: AUDIT-044 Daily P/L session date used workstation date instead of Alpaca market clock date
Status: Fixed locally; final live pass still requires approved cutover
Observed behavior:
- The contract requires each account's own Alpaca market clock/session date to define "today" for Daily P/L.
- `TraderEngine.refresh()` set `daily_pl_session_date` from `datetime.now().astimezone().date()`.
- `TraderEngine.daily_realized_pl_summary()` also filtered realized sells against the workstation's local date.
- `TraderEngine.format_market_clock()` exposed open/closed status and next open/close, but not the clock timestamp's session date.
Expected behavior:
- Daily P/L and realized Daily P/L should carry the account's Alpaca clock-derived session date when a market clock is available.
- Prior-day activity should be excluded relative to the account market-clock session date, not merely the workstation date.
Code pointer:
- `python_app/alpaca_desktop/engine.py::TraderEngine.refresh()`.
- `python_app/alpaca_desktop/engine.py::TraderEngine.format_market_clock()`.
- `python_app/alpaca_desktop/engine.py::TraderEngine.daily_realized_pl_summary()`.
Impact:
- Near date boundaries, the app could label or filter Daily P/L using the local machine date instead of the account's Alpaca market-clock date, weakening the P/L acceptance proof.
Fix evidence:
- `format_market_clock()` now includes `session_date` derived from the Alpaca clock timestamp when available.
- `refresh()` now uses `market_clock["session_date"]` for `daily_pl_session_date`.
- `daily_realized_pl_summary()` now accepts the session date and filters sells against that date.
- `standardized_account_metrics()` now uses the engine's market-clock `session_date` as the fallback when account P/L fields do not already include one.
- Added regression coverage for clock session-date payload, standardized P/L fallback, and realized-P/L filtering by supplied session date.
Verification:
- Focused P/L and market-stream tests passed: `python -m unittest tests.test_regression_baselines.ProfitLossContractBaselineTests tests.test_regression_baselines.MarketStreamBaselineTests -v`.
- Full regression passed: `python scripts/run_regression_tests.py` ran 75 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- JavaScript syntax check passed: `node --check python_app\static\app.js`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.

### 2026-06-25 - Goal continuation finding: AUDIT-045 unavailable P/L fallback rendered as fake zero
Status: Fixed locally; final live pass still requires approved cutover
Observed behavior:
- The contract says missing or unavailable P/L must display as unavailable/loading, not fake zero.
- `TraderEngine.standardized_account_metrics()` defaulted missing Daily P/L fields to numeric zero values.
- The UI Daily P/L helper defaulted missing amount and percent to `$0.00 (0.00%)`.
Expected behavior:
- When no account/equity/P&L source fields are present, the backend should expose an unavailable state instead of manufacturing zero P/L.
- Connected accounts must still expose real raw/display/source fields and fail verification if those fields are missing.
Code pointer:
- `python_app/alpaca_desktop/engine.py::TraderEngine.standardized_account_metrics()`.
- `python_app/static/app.js::dailyPlDisplay()`.
- `python_app/static/app.js::renderRealizedPlMetric()`.
Impact:
- A disconnected or not-yet-loaded account could look flat for the day even though no source data had been loaded.
Fix evidence:
- `standardized_account_metrics()` now returns `Unavailable` displays and blank raw fields when no P/L source data exists.
- The UI metric helpers now render `Unavailable` without appending a fake percent and without assigning positive/negative styling to blank raw values.
- Existing connected-account verifier checks still require nonblank raw/display fields and source math, so unavailable data cannot pass live acceptance for connected accounts.
- Updated the empty-account regression to assert unavailable displays and blank raw P/L fields.
Verification:
- Focused P/L tests passed: `python -m unittest tests.test_regression_baselines.ProfitLossContractBaselineTests -v`.
- JavaScript syntax check passed: `node --check python_app\static\app.js`.
- Full regression passed: `python scripts/run_regression_tests.py` ran 75 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/contract_status.py --include-regression --include-backtest` still fails before cutover only on stale/duplicate backend, old live top-volume universe, and missing fresh `alpaca_most_actives_volume` replay-tape evaluations; `daily_pl_backend`, `daily_pl_rendered_ui`, `sizing_modes`, account surfaces, launcher, runtime diagnostics, and regression harness pass.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.

### 2026-06-25 - Goal continuation finding: AUDIT-046 cutover execute could silently preserve saved auto-start trading
Status: Fixed locally; final live pass still requires approved cutover
Observed behavior:
- A sanitized read-only settings check showed 3 saved accounts and 3 saved `auto_start_trading=true` settings.
- `scripts/live_cutover.py --execute` launched the normal desktop shortcut after backup and process stop without separately surfacing or confirming saved auto-start behavior.
- The project safety rules require explicit approval before changing or relying on auto-start behavior during trading-app work.
Expected behavior:
- Dry-run should show the saved auto-start count before any live action.
- Execute mode should not proceed past backup into stop/relaunch when saved accounts would auto-start trading unless the user explicitly approved that behavior.
Code pointer:
- `scripts/live_cutover.py::run_cutover()`.
Impact:
- An operator could approve a backend restart thinking it only refreshes code, while the normal launch path immediately resumes paper trading for all saved auto-start accounts.
Fix evidence:
- `scripts/live_cutover.py` now reads only sanitized settings counts and prints an auto-start preflight.
- Execute mode aborts before process stop/relaunch when `auto_start_trading` is present unless `--allow-auto-start` is supplied.
- Execute mode also aborts before process stop/relaunch if saved settings cannot be read and auto-start behavior is unknown.
- README and OPERATING now document the `--allow-auto-start` approval boundary.
- Added regression coverage for the saved-auto-start abort, unknown-settings abort, and explicit allow paths.
Verification:
- Focused cutover tests passed: `python -m unittest tests.test_live_cutover -v`.
- Full regression passed: `python scripts/run_regression_tests.py` ran 77 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- JavaScript syntax check passed: `node --check python_app\static\app.js`.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/live_cutover.py` dry-run now reports `auto-start trading enabled: 3` and stops short of any process changes.
- `scripts/contract_status.py --include-regression --include-backtest` still fails before cutover on stale/duplicate backend, old live top-volume universe, and missing fresh `alpaca_most_actives_volume` replay-tape evaluations; `regression_harness` is ok.

### 2026-06-25 - Goal continuation finding: AUDIT-047 live verifier did not prove P/L dates matched account market clock
Status: Fixed locally; final live pass requires approved cutover and post-relaunch verification
Observed behavior:
- AUDIT-044 fixed the backend to carry `market_clock.session_date` into Daily P/L and realized P/L.
- `scripts/verify_live_contract.py` still only checked Daily P/L field presence and source math, not whether `daily_pl_session_date` or `realized_pl_session_date` matched the selected account's market clock session date.
- `scripts/contract_status.py` therefore could report `daily_pl_backend: ok` without proving the contract requirement that each account's own Alpaca market clock defines "today."
Expected behavior:
- The live verifier should fail if P/L session dates are missing or disagree with the account market-clock session date.
- The aggregate `daily_pl_backend` category should include that proof for all three accounts.
Code pointer:
- `scripts/verify_live_contract.py::check_daily_pl()`.
- `scripts/contract_status.py::build_categories()`.
Impact:
- A post-cutover acceptance report could miss a date-boundary P/L bug even if value math was correct for a mismatched session label.
Fix evidence:
- `verify_live_contract.py` now emits `account_N.daily_pl_session_date` and `account_N.realized_pl_session_date` checks that require equality with `selected.market_clock.session_date`.
- `contract_status.py` now includes those checks in `daily_pl_backend`.
- Added live-verifier regression coverage for a deliberate market-clock/P&L session-date mismatch.
Verification:
- Focused verifier/status tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v`.
- Full regression passed: `python scripts/run_regression_tests.py` ran 78 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- JavaScript syntax check passed: `node --check python_app\static\app.js`.

### 2026-06-25 - Goal continuation finding: AUDIT-038 normal top-volume mode still appended hardcoded inverse ETFs
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The contract requires the live entry universe to come from the current Alpaca top-25 volume source, with no hardcoded live candidate lists unless there is an explicit override.
- `python_app/alpaca_desktop/engine.py::TraderEngine.active_inverse_symbols()` still appended `SQQQ`, `SPXU`, `SDS`, `SH`, and `TZA` whenever `inverse_etf_mode="allow"` and top-volume mode was enabled.
- `TraderEngine.trading_symbols()` also allowed `inverse_only` mode to carry the Alpaca top-volume base list plus the inverse set, so the mode was not actually inverse-only.
- `scripts/verify_live_contract.py` accepted `trading_symbol_count >= 25`, so a 30-symbol top-volume entry universe could pass even though it included five non-Alpaca-top-25 additions.
Impact:
- New entries could come from a hardcoded inverse ETF list in normal top-volume mode instead of only from the Alpaca top-25 volume universe.
- Post-cutover verification could miss that violation because the account-level top-volume check only proved a lower bound.
Required fix:
- Keep normal `allow` mode on the Alpaca-returned top-25 only; inverse ETFs remain eligible only if Alpaca returns them in that set.
- Make `exclude` explicitly block inverse ETF entries and make `inverse_only` use only the bounded inverse set as an explicit override.
- Tighten live verification so normal top-volume accounts must report exactly the dashboard top-25 symbols, not a larger merged set.
Fix evidence:
- `TraderEngine.active_inverse_symbols()` now returns the bounded inverse set only for `inverse_only`.
- `TraderEngine.trading_symbols()` no longer includes the top-volume base list when `inverse_etf_mode="inverse_only"`.
- `inverse_etf_hold_reason()` now blocks inverse ETF entries when `inverse_etf_mode="exclude"`.
- Account `symbol_source` now reports `inverse_only` for that explicit override.
- The Accounts UI labels now read `Exclude inverse ETFs`, `Allow Alpaca top-25`, and `Inverse set only`.
- README and `OPERATING.md` now describe inverse ETF behavior as Alpaca-top-25-only in normal mode, with inverse-only as an explicit override.
- `scripts/verify_live_contract.py` now compares per-account `trading_symbols` to the dashboard top-volume symbols and fails normal top-volume mode if there are extras or missing symbols.
Verification:
- Focused inverse/verifier tests passed: `python -m unittest tests.test_regression_baselines.MarketStreamBaselineTests.test_inverse_etf_eligibility_has_no_downturn_gate tests.test_live_contract_verifier -v`.
- Full `scripts/run_regression_tests.py` passed 65 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- Live `scripts/verify_live_contract.py` now detects the current stale backend's old 30-symbol top-volume universe with five extras for each account; remaining failures are `backend.current`, `backend.single_process`, those account top-volume extras, `top_volume.source`, and `top_volume.cache_seconds`.
- `scripts/contract_status.py --include-regression --include-backtest` now reports the stricter `top_volume_universe` failures while regression harness and replay backtester still pass.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass against a current backend.

### 2026-06-25 - Goal continuation finding: AUDIT-039 rendered UI verifier sampled stale API state before page refresh
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- `scripts/verify_ui_display.py` fetched `/api/state` before launching the headless browser, then compared the rendered DOM against that pre-browser payload.
- Loading the app page can trigger a state refresh, so fields such as `last_refresh` can legitimately advance before the DOM snapshot is taken.
- A read-only run of `scripts/verify_ui_display.py` failed only on `ui.lastRefresh` while all Daily P/L, card count, and runtime-warning checks matched.
Impact:
- The rendered UI verifier could falsely fail a current UI because it compared the DOM to an older source snapshot, adding noise to the post-cutover acceptance gate.
Required fix:
- During the DOM wait loop, re-sample `/api/state` and compare the rendered metric cards and `lastRefresh` against the current API payload used for that iteration.
Fix evidence:
- `collect_rendered_payload()` now keeps the initial account-count target but refreshes `/api/state` on each DOM sample and returns the state payload that matches the rendered `dailyPl` and `lastRefresh`.
Verification:
- `scripts/verify_ui_display.py` now passes against the current stale backend, with the stale runtime warning visible as expected.
- Focused UI verifier tests passed: `python -m unittest tests.test_ui_display_verifier -v`.
- Python compile passed for `scripts\verify_ui_display.py` and `tests\test_ui_display_verifier.py`.
Remaining live gate:
- The rendered UI verifier still needs to pass after the approved live cutover with `health.current=True` and no stale-runtime warning.

### 2026-06-25 - Goal continuation finding: AUDIT-042 paper-only broker contract was not exposed to live verification
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The contract requires paper trading only and says the app must never start live trading.
- `TraderEngine.connect()` constructed Alpaca `TradingClient(..., paper=True)`, but `/api/health` did not expose any non-sensitive paper-only contract flag.
- `scripts/verify_live_contract.py` therefore could not prove after cutover that the running backend advertises paper-only broker mode.
Impact:
- A post-cutover live contract report could pass backend currentness, account loading, P/L, sizing, and top-volume checks without explicitly proving the paper-only safety contract.
Required fix:
- Expose a non-secret paper-only broker flag in health.
- Require the live verifier and aggregate status to fail if that paper-only contract is missing.
- Add regression coverage that the connect path still constructs the Alpaca trading client with `paper=True`.
Fix evidence:
- `/api/health` now includes `paper_trading_only: true` and `broker_mode: "paper"`.
- `scripts/verify_live_contract.py` now adds `backend.paper_only`.
- `scripts/contract_status.py` includes `backend.paper_only` in `backend_currentness`.
- `tests.test_regression_baselines.ServerContractTests` verifies both the health payload and `TraderEngine.connect()` constructing the trading client with `paper=True` using fake clients.
- `tests.test_live_contract_verifier.LiveContractVerifierTests.test_missing_paper_only_health_contract_fails` covers the live verifier failure path.
Verification:
- Focused paper/verifier/status tests passed: `python -m unittest tests.test_regression_baselines.ServerContractTests tests.test_live_contract_verifier tests.test_contract_status -v`.
- Python compile passed for the touched health/verifier/status/test files.
Remaining live gate:
- The current running backend is stale, so `backend.paper_only` will remain failed until approved cutover loads the updated health endpoint.

### 2026-06-25 - Goal continuation finding: AUDIT-040 replay aggregate passed old top-volume source evidence
Status: Fixed locally; final live pass still requires approved cutover and fresh expected-source replay evidence
Evidence:
- The acceptance contract requires the backtester to replay the same top-25-by-volume candidate universe logic used by the fixed live app.
- `scripts/contract_status.py --include-regression --include-backtest` was passing the `replay_backtester` category as long as day tape had any top-volume snapshots, evaluations, rejections, zero parse errors, and the fixed sizing harness.
- A real read-only `scripts/day_tape_backtest.py --days 1 --max-events 50000 --json` run showed `top_volume_sources=["sp500_snapshot_volume"]`, so the passing replay category was based on pre-fix source data.
Impact:
- The aggregate status could claim replay/backtester evidence passed even though the selected tape did not contain any evaluations using the required `alpaca_most_actives_volume` source.
Required fix:
- Track which top-volume source is active for each replay evaluation.
- Require the aggregate replay category to include at least one evaluation under `alpaca_most_actives_volume`.
Fix evidence:
- `scripts/day_tape_backtest.py` now records `expected_top_volume_source`, `evaluations_by_top_volume_source`, and each accepted trade's `top_volume_source`.
- `scripts/contract_status.py` now fails `replay_backtester` unless `alpaca_most_actives_volume` appears in the tape sources and has at least one strategy evaluation.
- The human day-tape backtest output now prints the expected-source evaluation count.
- README now states that older `sp500_snapshot_volume` tape remains diagnostic only and does not satisfy the post-fix source contract.
- Added focused tests for source attribution in `tests/test_day_tape_backtest.py` and the legacy-source aggregate failure in `tests/test_contract_status.py`.
Verification:
- Focused replay tests passed: `python -m unittest tests.test_day_tape_backtest tests.test_contract_status -v`.
- Python compile passed for the touched replay/status files.
- `scripts/contract_status.py --include-regression --include-backtest` now fails `replay_backtester` on the current real tape with `top_volume_sources=sp500_snapshot_volume` and `alpaca_most_actives_volume_evaluations=0`, which is the expected pre-cutover result.
Remaining live gate:
- The aggregate status is expected to remain failed until the approved cutover runs the current app and a market-hours tape records at least one `alpaca_most_actives_volume` strategy evaluation.

### 2026-06-25 - Goal continuation finding: AUDIT-041 cutover success and full replay acceptance needed separate outcomes
Status: Fixed locally; final full acceptance still requires approved cutover and fresh expected-source replay evidence
Evidence:
- AUDIT-040 made the full aggregate correctly fail when the only available tape contains old `sp500_snapshot_volume` replay evaluations.
- `scripts/live_cutover.py --execute` runs that aggregate immediately after backup, relaunch, live verifier, UI verifier, regression, and backtest.
- If the command is run outside market hours or before fresh post-fix tape exists, the live app can be successfully deployed and verified while the full aggregate remains failed only on `replay_backtester`.
Impact:
- A successful backup/stop/shortcut-launch/live-verification operation could exit as a generic failure solely because fresh expected-source day tape is not available yet, encouraging unnecessary repeated restarts.
Required fix:
- Keep full contract acceptance strict, but make the cutover command report deployment success separately when the only remaining category is fresh replay tape evidence.
Fix evidence:
- `scripts/live_cutover.py` now keeps the aggregate report as `ok: False` when `replay_backtester` is pending, but returns cutover success with a clear message if every live deployment gate passed and only fresh replay tape is missing.
- README now documents that cutover can complete while full acceptance remains pending until market-hours tape records `alpaca_most_actives_volume`.
- Added `tests.test_live_cutover.LiveCutoverTests.test_execute_reports_success_when_only_fresh_replay_tape_is_pending`.
Verification:
- Focused cutover/status tests passed: `python -m unittest tests.test_live_cutover tests.test_contract_status -v`.
- Full `scripts/run_regression_tests.py` passed 67 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
Verification still needed:
- Re-run read-only `scripts/live_cutover.py` dry-run and full `contract_status.py --include-regression --include-backtest`.

### 2026-06-25 - Goal continuation finding: AUDIT-037 desktop launcher aggregate under-checked no-window/app-mode launcher contract
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The acceptance contract requires desktop launch from shortcut, self-contained app opening, and no visible terminal windows.
- `scripts/test_runtime_currentness.py` covered VBS source behavior for hidden `pythonw --no-browser` launch and Edge `--app=` mode, but `scripts/contract_status.py` only represented this as `desktop_launcher: shortcut.path`.
- `scripts/verify_live_contract.py` did not emit separate live/status checks for VBS health-currentness, hidden backend launch, hidden smoke check, or Edge app-mode behavior.
Impact:
- A final aggregate status could show `desktop_launcher: ok` from a valid `.lnk` even if the VBS script stopped honoring the no-window/self-contained app launch contract.
Required fix:
- Add sanitized launcher-source checks to the live verifier and include them in the `desktop_launcher` aggregate category.
Fix evidence:
- `scripts/verify_live_contract.py` now inspects `Launch Alpaca Paper Trader.vbs` and emits separate checks for VBS presence, `/api/health` currentness validation, hidden backend launch with `--no-browser`, hidden startup smoke check, and Edge `--app=` mode.
- `scripts/contract_status.py` now requires those launcher checks in the `desktop_launcher` category, alongside the desktop shortcut metadata check.
- Added regression coverage proving missing hidden-backend or Edge app-mode launcher checks fail the live verifier and that the aggregate category includes the launcher checks.
Verification:
- Focused tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v`.
- Live `scripts/verify_live_contract.py` passed the new launcher checks against the current checkout; remaining failures were only `backend.current`, `backend.single_process`, `top_volume.source`, and `top_volume.cache_seconds`.
- Full `scripts/run_regression_tests.py` passed 64 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `desktop_launcher: ok` from shortcut plus explicit VBS no-window/app-mode/currentness checks; it still fails as expected before cutover with only `backend_currentness` and `top_volume_universe` failing.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass.

### 2026-06-25 - Goal continuation finding: AUDIT-036 live cutover aggregate omitted regression harness
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The acceptance standard explicitly includes "Regression checks pass."
- `scripts/contract_status.py --include-regression --include-backtest` can include regression evidence, but `scripts/live_cutover.py --execute` built its final aggregate with `regression_result=None` and printed `regression_included: False`.
- The guarded live cutover command is the final backup/stop/shortcut-launch/verify path, so its final status should include the regression gate.
Impact:
- An approved cutover could report a final aggregate pass from live/UI/backtest checks while omitting the required regression-harness evidence from the same final proof.
Required fix:
- Run the isolated regression harness in execute-mode final aggregation, pass that result into `contract_status.build_categories()`, and mark `regression_included=True` in the cutover summary.
Fix evidence:
- `scripts/live_cutover.py --execute` now runs `contract_status.run_regression()` before the final aggregate.
- The execute-mode final aggregate now passes the regression result into `contract_status.build_categories()` and prints `regression_included: True`.
- README now states that the approved execute path includes the isolated regression harness and bounded read-only day-tape backtest.
- `tests/test_live_cutover.py` now proves execute mode calls the regression harness and passes both regression and backtest results into the final aggregate.
Verification:
- Focused tests passed: `python -m unittest tests.test_live_cutover tests.test_contract_status -v`.
- Full `scripts/run_regression_tests.py` passed 63 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/contract_status.py --include-regression --include-backtest` still reports `regression_harness: ok` and `replay_backtester: ok`; it fails as expected before cutover with only `backend_currentness` and `top_volume_universe` failing.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass.

### 2026-06-25 - Goal continuation finding: AUDIT-035 live verifier under-checked per-account state surfaces
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The contract requires each account to show its own positions, orders, dashboard, logs, market clock, trading state, and P/L, with connected/trading-enabled/market-clock state accurate per account.
- `scripts/verify_live_contract.py` checked account count, connected state, market-clock presence, Daily P/L math, sizing mode, and top-volume universe, but did not fail if `trading_enabled` was missing/not boolean or if per-account positions, orders, logs, replay, or dashboard payloads were absent.
- `scripts/contract_status.py` summarized `accounts_loaded` but did not include a per-account state-surface category.
Impact:
- A post-cutover status could pass account count and P/L checks while still missing one of the account-specific UI/API surfaces required by the contract.
Required fix:
- Add sanitized per-account checks for `trading_enabled` boolean, market-clock shape, positions list, orders list, logs list, replay payload, and dashboard payload.
- Add an aggregate status category so these account-surface checks are visible in `contract_status.py` and the guarded cutover summary.
Fix evidence:
- `scripts/verify_live_contract.py` now fetches `/api/dashboard?account_id=...` for every account in addition to per-account `/api/state`.
- The live verifier now checks each account's `trading_enabled` boolean, market-clock `is_open/status` shape, positions/orders/protection/trade-history/order-intents/strategy/logs lists, replay path/events payload, and account-specific dashboard surface.
- `scripts/contract_status.py` now includes an `account_state_surfaces` category that groups those per-account state checks in the aggregate status and guarded cutover summary.
- Added regression coverage for missing per-account surfaces and for the aggregate category mapping.
Verification:
- Focused verifier tests passed: `python -m unittest tests.test_live_contract_verifier tests.test_contract_status -v`.
- Live `scripts/verify_live_contract.py` passed the new account-surface checks against the current running app; remaining failures were only `backend.current`, `backend.single_process`, `top_volume.source`, and `top_volume.cache_seconds`.
- Full `scripts/run_regression_tests.py` passed 63 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/contract_status.py --include-regression --include-backtest` now reports `account_state_surfaces: ok`; it still fails as expected before cutover with only `backend_currentness` and `top_volume_universe` failing.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass.

### 2026-06-25 - Goal continuation finding: AUDIT-033 aggregate status omitted replay/backtester evidence
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The acceptance contract requires strategy verification to use replay/backtester evidence, and the current acceptance standard includes "Backtester uses the same strategy logic."
- `scripts/contract_status.py` aggregated live API, rendered UI, sizing, top-volume, runtime diagnostics, and optional regressions, but did not include a category for a bounded day-tape backtest run.
- `scripts/live_cutover.py` printed an aggregate post-launch status from live and UI reports only, so a post-relaunch pass could still omit the replay/backtester gate.
Impact:
- The final status command could report all visible live categories as passing while the strategy replay acceptance evidence remained separate and easy to miss.
Required fix:
- Add an optional bounded read-only day-tape backtest check to `scripts/contract_status.py`, with evidence that it uses `selection_engine=app_engine`, the fixed replay sizing harness, recorded top-volume snapshots, evaluations, rejected-candidate reporting, and zero parse errors.
- Include the bounded backtest category in the guarded cutover execute aggregate without making any Alpaca API calls or app-data writes.
Fix evidence:
- `scripts/contract_status.py` now supports `--include-backtest`, `--backtest-days`, and `--backtest-max-events`.
- The backtest status category runs `scripts/day_tape_backtest.py` in-process against the latest local day tape, defaults to a bounded 50,000-event read-only pass, and checks `selection_engine=app_engine`, the fixed `$1000`/20-slot/5% replay sizing harness, top-volume snapshots, evaluations, rejected-candidate reporting, zero parse errors, and winner/loser indicator report fields.
- `scripts/live_cutover.py --execute` now includes the bounded backtest result in its final aggregate contract status after backup, shortcut launch, live API verification, and rendered UI verification.
- README now documents `scripts/contract_status.py --include-regression --include-backtest` and notes that cutover execute includes the bounded replay category.
- Added regression coverage for the backtest status pass/fail contract and the cutover execute call into the backtest check.
Verification:
- Focused tests passed: `python -m unittest tests.test_contract_status tests.test_live_cutover -v`.
- Full `scripts/run_regression_tests.py` passed 60 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/day_tape_backtest.py --days 1 --max-events 50000` completed read-only with `selection_engine: app_engine`, 230 evaluations, 6,900 rejected candidates, zero parse errors, and the fixed replay sizing harness. The latest available tape is still pre-cutover and reports recorded source `sp500_snapshot_volume`; live Alpaca screener source remains verified separately by the live top-volume category after cutover.
- `scripts/contract_status.py --include-regression --include-backtest` failed as expected before cutover with only `backend_currentness` and `top_volume_universe` failing; `replay_backtester`, desktop launcher, `instance_json`, accounts, backend Daily P/L, rendered UI Daily P/L, sizing modes, runtime diagnostics, and regression harness all passed.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass. A fresh post-cutover market-hours tape will be needed before the day-tape backtest itself can show recorded `alpaca_most_actives_volume` source rows.

### 2026-06-25 - Goal continuation finding: AUDIT-034 rendered UI verifier did not prove stale-warning absence after current launch
Status: Fixed locally; final live pass still requires approved cutover
Evidence:
- The acceptance contract requires normal launch not to show stale runtime warnings.
- `scripts/verify_ui_display.py` only checked that `runtimeWarningVisible` was a boolean, so it could pass even if a stale-runtime banner remained visible after `/api/health` reported `current=True`.
- `python_app/static/index.html` used a static `Stale runtime warning` banner title even though `renderRuntimeHealth()` can also show settings or runtime diagnostics for a current backend.
Impact:
- A post-cutover UI could falsely show a stale-runtime warning or mislabeled current-runtime diagnostic while the rendered UI verifier still passed.
Required fix:
- Make the runtime warning title dynamic: stale backend, settings warning, runtime warning, or health-unavailable.
- Teach `scripts/verify_ui_display.py` to fetch `/api/health` and assert that a stale-runtime warning is visible only when health is stale, and hidden/not stale when health is current.
Fix evidence:
- `python_app/static/index.html` now gives the runtime warning title its own `#runtimeHealthTitle` element instead of hardcoding every warning as `Stale runtime warning`.
- `python_app/static/app.js` now sets the warning title to `Stale runtime warning`, `Settings warning`, `Runtime warning`, or `Runtime health unavailable` based on the actual health state.
- `scripts/verify_ui_display.py` now fetches `/api/health`, captures the rendered warning title from the DOM, and requires stale-warning visibility to match health currentness: stale health must show a stale warning; current health must not.
- `tests/test_ui_display_verifier.py` now covers the current-backend stale-warning failure case and the stale-backend visible-warning pass case.
Verification:
- Focused rendered UI verifier tests passed: `python -m unittest tests.test_ui_display_verifier -v`.
- Live `scripts/verify_ui_display.py` passed against the current stale backend because `/api/health` reported `current=False` and the rendered UI showed `Stale runtime warning`.
- Full `scripts/run_regression_tests.py` passed 62 tests.
- Python compile passed for `python_app`, `scripts`, and `tests`.
- `node --check python_app\static\app.js` passed.
- `git diff --check` passed with only Git's LF-to-CRLF normalization warnings.
- `powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly` passed.
- `scripts/check_frontend_layout.py` reported no whole-page horizontal overflow at 1024px, 1100px, or 1280px.
- `scripts/contract_status.py --include-regression --include-backtest` failed as expected before cutover with only `backend_currentness` and `top_volume_universe` failing; rendered UI Daily P/L, warning-state verification, regression harness, and replay backtester all passed.
- `scripts/live_cutover.py` dry-run passed without stopping or launching anything, confirmed the backup plan, validated the desktop shortcut, and found the two current repo launcher PIDs `12716` and `11068`.
Remaining live gate:
- The aggregate status is expected to remain failed until `scripts/live_cutover.py --execute` is explicitly approved and post-relaunch verifiers pass.
