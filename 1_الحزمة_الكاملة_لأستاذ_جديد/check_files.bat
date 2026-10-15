@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Check exam files
cd /d "%~dp0"
python --version >nul 2>&1
if %errorlevel%==0 (python check_files.py) else (py check_files.py)
echo.
pause
