@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo This explicitly records 20 seconds of the selected system output.
echo Files are saved under artifacts\diagnostics. Nothing is uploaded.
".venv\Scripts\python.exe" -m scripts.repair_audio_check --seconds 20
pause
