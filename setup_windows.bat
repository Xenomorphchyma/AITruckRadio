@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not open the project folder.
    pause
    exit /b 1
)

echo [AI Truck Radio] Creating local Python venv in this folder...

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.13 -m venv ".venv"
        if errorlevel 1 py -3 -m venv ".venv"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python was not found. Install Python 3.13 and enable "Add python.exe to PATH".
            pause
            exit /b 1
        )
        python -m venv ".venv"
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Failed to create venv. Check that Python 3 is installed.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] Failed to update pip in .venv.
    pause
    exit /b 1
)
if exist "requirements.txt" (
    ".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Failed to install requirements.txt.
        pause
        exit /b 1
    )
)
if exist "requirements-optional-asr.txt" (
    echo [AI Truck Radio] Installing lightweight reference-audio transcription...
    ".venv\Scripts\python.exe" -m pip install -r "requirements-optional-asr.txt"
    if errorlevel 1 (
        echo [WARNING] Reference ASR was not installed. The radio will work, but automatic transcript checks will be unavailable.
    )
)

echo.
echo Done. Put your music into the music folder, then run run_radio.bat
echo.
pause
exit /b 0
