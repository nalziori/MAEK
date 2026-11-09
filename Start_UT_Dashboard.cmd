@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\serve_ut_dashboard.py --port 8894
) else (
  py -3 scripts\serve_ut_dashboard.py --port 8894
)
if errorlevel 1 pause
