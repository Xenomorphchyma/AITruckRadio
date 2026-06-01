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
pause
