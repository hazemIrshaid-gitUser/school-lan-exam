@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Check exam files
cd /d "%~dp0"
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if defined PY goto run
python --version >nul 2>&1
if %errorlevel%==0 (set "PY=python") else (set "PY=py")
:run
"%PY%" check_files.py
echo.
pause
