@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if errorlevel 1 (
  echo [ERROR] Could not open project root: %ROOT%
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo .venv not found. Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Testing current TTS backend from config.json...
".venv\Scripts\python.exe" "tools\test_tts_backend.py"
set "TEST_EXIT=%ERRORLEVEL%"
if not "%TEST_EXIT%"=="0" (
  echo.
  echo [ERROR] TTS test failed with exit code %TEST_EXIT%.
  echo Copy the console log when asking for help.
  pause
  exit /b %TEST_EXIT%
)
echo.
echo Output should be: cache\test_tts_output.mp3
echo.
pause
exit /b 0
