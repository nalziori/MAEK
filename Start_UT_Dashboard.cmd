@echo off
cd /d "%~dp0"
"C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe" scripts\serve_ut_dashboard.py --port 8894
if errorlevel 1 pause
