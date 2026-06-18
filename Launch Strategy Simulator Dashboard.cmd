@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$expected='2026.06.18-profile-builder-v4'; try { $state = Invoke-RestMethod -Uri 'http://127.0.0.1:8787/api/state' -TimeoutSec 1; $running = @($state.jobs | Where-Object { $_.status -eq 'running' -or $_.status -eq 'queued' }).Count -gt 0; if ($state.ui_version -eq $expected -or $running) { Start-Process 'http://127.0.0.1:8787/'; exit 0 }; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*strategy_simulation_dashboard.py*' -and $_.CommandLine -like '*--port 8787*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; Start-Sleep -Milliseconds 800 } catch { }"

if exist "%~dp0.venv\Scripts\python.exe" (
  start "Alpaca Strategy Simulator" "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\strategy_simulation_dashboard.py" --port 8787 --open
  exit /b
)

python "%~dp0scripts\strategy_simulation_dashboard.py" --port 8787 --open
