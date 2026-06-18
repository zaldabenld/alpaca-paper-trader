@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8787/' -TimeoutSec 1; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { Start-Process 'http://127.0.0.1:8787/'; exit 0 } } catch { }"

if exist "%~dp0.venv\Scripts\python.exe" (
  start "Alpaca Strategy Simulator" "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\strategy_simulation_dashboard.py" --port 8787 --open
  exit /b
)

python "%~dp0scripts\strategy_simulation_dashboard.py" --port 8787 --open
