@echo off
cd /d "%~dp0"
title MAEK demo
python\python.exe serve.py
if errorlevel 1 pause
