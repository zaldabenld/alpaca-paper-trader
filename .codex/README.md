# Codex Worktree Setup

Use this folder for repo-local Codex setup helpers.

For a fresh Codex worktree, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1
```

For a quick verification after dependencies already exist:

```powershell
powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1 -SmokeOnly
```

The setup script points `LOCALAPPDATA` at `.runtime\localappdata` for checks so Codex worktrees do not read or write the stable app's saved Alpaca settings.

Run the repo-local regression harness with:

```powershell
.\.venv\Scripts\python.exe scripts\run_regression_tests.py
```

The regression runner also points `LOCALAPPDATA` at `.runtime\localappdata`, disables auto-connect/auto-start, and needs no real Alpaca credentials.
