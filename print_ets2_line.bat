@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Local venv not found. Run setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" "ai_truck_radio.py" --print-ets2-line
pause
