@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Testing current TTS backend from config.json...
".venv\Scripts\python.exe" "tools\test_tts_backend.py"
echo.
echo Output should be: cache\test_tts_output.mp3
echo If it failed, copy the console log to ChatGPT.
echo.
pause
