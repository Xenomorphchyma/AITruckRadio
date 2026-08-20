@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist ".venv_omnivoice\Scripts\python.exe" (
  echo .venv_omnivoice not found. Run scripts\omnivoice\install_omnivoice_windows.bat first.
  pause
  exit /b 1
)
".venv_omnivoice\Scripts\python.exe" tools\omnivoice_render.py --mode design --output cache\test_omnivoice_design.wav --text-file docs\omnivoice_prompt_examples\maxim_text.txt --instruct-file docs\omnivoice_prompt_examples\maxim_instruct.txt --device cuda:0 --steps 16 --speed 1.0
echo Output: %CD%\cache\test_omnivoice_design.wav
pause
