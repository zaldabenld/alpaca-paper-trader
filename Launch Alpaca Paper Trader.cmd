@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
  echo ERROR: Alpaca Paper Trader Python virtualenv is missing.
  echo Expected: "%PYTHON_EXE%"
  echo.
  echo Run this from the project folder:
  echo powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1
  echo.
  echo The legacy PowerShell trader is not launched by this shortcut.
  pause
  exit /b 1
)

"%PYTHON_EXE%" "%~dp0python_app\run.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo ERROR: Alpaca Paper Trader Python startup failed with exit code %EXIT_CODE%.
  echo Check the Python traceback above, then reinstall dependencies if needed:
  echo powershell -ExecutionPolicy Bypass -File .\.codex\setup-worktree.ps1
  pause
)
exit /b %EXIT_CODE%
