@echo off
setlocal
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist ".venv\Scripts\python.exe" (
  echo Local .venv not found. Running setup_windows.bat first...
  call "%ROOT%\setup_windows.bat"
)
".venv\Scripts\python.exe" tools\set_omnivoice_mode.py
pause
