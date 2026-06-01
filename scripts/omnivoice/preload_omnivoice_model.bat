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
set "HF_XET_HIGH_PERFORMANCE=1"
if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo .venv_omnivoice not found. Run scripts\omnivoice\install_omnivoice_windows.bat first.
  pause
  exit /b 1
)
".venv_omnivoice\Scripts\python.exe" -c "from huggingface_hub import snapshot_download; snapshot_download('k2-fsa/OmniVoice')"
pause
