@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if errorlevel 1 (
  echo [ERROR] Could not open project root: %ROOT%
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
set "HF_HOME=%CD%\.hf_cache"
set "HF_HUB_CACHE=%CD%\.hf_cache\hub"
set "HF_XET_CACHE=%CD%\.hf_cache\xet"
set "TORCH_HOME=%CD%\.torch_cache"
set "PIP_CACHE_DIR=%CD%\.pip_cache"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "HF_XET_HIGH_PERFORMANCE=1"

if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo [OmniVoice] Creating isolated venv: .venv_omnivoice
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3.10 -m venv ".venv_omnivoice"
    if errorlevel 1 py -3 -m venv ".venv_omnivoice"
  ) else (
    python -m venv ".venv_omnivoice"
  )
)

if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo [ERROR] Could not create .venv_omnivoice. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

".venv_omnivoice\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [ERROR] Could not prepare pip in .venv_omnivoice.
  pause
  exit /b 1
)

".venv_omnivoice\Scripts\python.exe" -m pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
  echo [WARN] CUDA PyTorch install failed. Trying generic torch and torchaudio. This may be CPU-only.
  ".venv_omnivoice\Scripts\python.exe" -m pip install torch torchaudio
  if errorlevel 1 (
    echo [ERROR] Could not install PyTorch.
    pause
    exit /b 1
  )
)
".venv_omnivoice\Scripts\python.exe" -m pip install -U huggingface_hub hf_xet soundfile omnivoice
if errorlevel 1 (
  echo [WARN] PyPI omnivoice install failed. Trying GitHub source.
  ".venv_omnivoice\Scripts\python.exe" -m pip install -U huggingface_hub hf_xet soundfile git+https://github.com/k2-fsa/OmniVoice.git
  if errorlevel 1 (
    echo [ERROR] Could not install OmniVoice from PyPI or GitHub.
    pause
    exit /b 1
  )
)
".venv_omnivoice\Scripts\python.exe" tools\omnivoice_probe.py
if errorlevel 1 (
  echo [ERROR] OmniVoice probe failed. The environment is incomplete.
  pause
  exit /b 1
)

echo.
echo [OK] OmniVoice environment is ready.
echo Next: run scripts\omnivoice\set_omnivoice_mode.bat and scripts\tests\test_tts_windows.bat
pause
exit /b 0
