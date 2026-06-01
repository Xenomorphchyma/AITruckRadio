@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist ".venv\Scripts\python.exe" call "%ROOT%\setup_windows.bat"
if not exist ".venv\Scripts\python.exe" ( echo Local Python venv is still missing. Setup failed. & pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
echo Installing Piper into local .venv...
python -m pip install --upgrade pip piper-tts
if errorlevel 1 ( echo Piper install failed. & pause & exit /b 1 )
python "tools\setup_piper_voice.py"
pause
