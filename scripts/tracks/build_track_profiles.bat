@echo off
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Building track profiles with LM Studio. Make sure Local Server is ON.
".venv\Scripts\python.exe" "tools\build_track_profiles.py"
pause
