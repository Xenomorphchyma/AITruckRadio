@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
set "PYTHONUTF8=1"
set "HF_HOME=%CD%\.hf_cache"
set "HF_HUB_CACHE=%CD%\.hf_cache\hub"
set "HF_XET_CACHE=%CD%\.hf_cache\xet"
set "TORCH_HOME=%CD%\.torch_cache"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo .venv_omnivoice not found. Run scripts\omnivoice\install_omnivoice_windows.bat first.
  pause
  exit /b 1
)
".venv_omnivoice\Scripts\python.exe" -m pip install -U huggingface_hub hf_xet
".venv_omnivoice\Scripts\huggingface-cli.exe" login
pause
