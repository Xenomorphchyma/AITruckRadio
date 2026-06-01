@echo off
setlocal
cd /d "%~dp0"

echo [AI Truck Radio] Creating local Python venv in this folder...

where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m venv ".venv"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install Python 3.10+ and enable "Add python.exe to PATH".
        pause
        exit /b 1
    )
    python -m venv ".venv"
)

if errorlevel 1 (
    echo Failed to create venv. Check that Python 3 is installed.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if exist "requirements.txt" (
    python -m pip install -r "requirements.txt"
)

echo.
echo Done. Put your music into the music folder, then run run_radio.bat
echo.
pause
