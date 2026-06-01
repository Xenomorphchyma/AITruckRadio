@echo off
setlocal
cd /d "%~dp0"

rem Keep AI/HuggingFace/Torch caches inside project folder, not on C:\Users.
set HF_HOME=%CD%\.hf_cache
set HF_HUB_CACHE=%CD%\.hf_cache\hub
set TORCH_HOME=%CD%\.torch_cache


if not exist ".venv\Scripts\python.exe" (
    echo Local venv not found. Running setup_windows.bat first...
    call "%~dp0setup_windows.bat"
)

if not exist ".venv\Scripts\python.exe" (
    echo Local Python venv is still missing. Setup failed.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo.
echo Starting AI Truck Radio...
echo Open this in browser: http://127.0.0.1:8765/
echo Press Ctrl+C in this window to stop the radio.
echo.
python "ai_truck_radio.py"
pause
