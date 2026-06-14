@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0python_app\run.py"
  exit /b
)
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0python_app\run.py"
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\App.ps1"
)
