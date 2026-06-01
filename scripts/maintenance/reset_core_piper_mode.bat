@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist ".venv\Scripts\python.exe" ( echo Local venv not found. Run setup_windows.bat first. & pause & exit /b 1 )
".venv\Scripts\python.exe" "tools\set_core_mode.py"
echo.
echo Done. Start run_radio.bat and use Piper/SAPI only.
pause
