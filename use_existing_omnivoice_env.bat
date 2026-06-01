@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "tools\use_existing_omnivoice_env.py"
pause
