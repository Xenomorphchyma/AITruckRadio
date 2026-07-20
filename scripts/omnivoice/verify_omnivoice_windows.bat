@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
set "PYTHONUTF8=1"
set "HF_HOME=%CD%\.hf_cache"
set "HF_HUB_CACHE=%CD%\.hf_cache\hub"
set "HF_XET_CACHE=%CD%\.hf_cache\xet"
set "TORCH_HOME=%CD%\.torch_cache"
if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo .venv_omnivoice not found. Run scripts\omnivoice\install_omnivoice_windows.bat first.
  pause
  exit /b 1
)
".venv_omnivoice\Scripts\python.exe" tools\omnivoice_probe.py
set "PROBE_EXIT=%ERRORLEVEL%"
if not "%PROBE_EXIT%"=="0" echo [ERROR] OmniVoice verification failed with exit code %PROBE_EXIT%.
pause
exit /b %PROBE_EXIT%
