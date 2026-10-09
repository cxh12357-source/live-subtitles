@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup.ps1 with Python 3.12 installed first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
