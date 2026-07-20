@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if errorlevel 1 ( echo Could not open project root. & pause & exit /b 1 )
if not exist ".venv\Scripts\python.exe" (
  call "%ROOT%\setup_windows.bat"
  if errorlevel 1 exit /b 1
)
if not exist ".venv\Scripts\python.exe" ( echo Local Python venv is still missing. Setup failed. & pause & exit /b 1 )
echo Installing Piper into local .venv...
".venv\Scripts\python.exe" -m pip install --upgrade pip piper-tts
if errorlevel 1 ( echo Piper install failed. & pause & exit /b 1 )
".venv\Scripts\python.exe" "tools\setup_piper_voice.py"
if errorlevel 1 ( echo Piper voice setup failed. & pause & exit /b 1 )
pause
exit /b 0
