@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install dependencies as described in README.md first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe desktop.py
if errorlevel 1 pause
