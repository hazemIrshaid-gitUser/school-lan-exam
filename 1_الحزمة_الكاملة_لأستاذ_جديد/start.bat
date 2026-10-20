@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Exam Server
cd /d "%~dp0"
echo.
echo Starting exam server... keep this window open during the exam.
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if defined PY goto run
python --version >nul 2>&1
if %errorlevel%==0 (set "PY=python") else (set "PY=py")
:run
"%PY%" server.py
echo.
echo If you see an error above, read it: either a problem in the exam files, or Python is not installed (the "python" folder next to server.py is missing - extract the full package again - or install Python from https://www.python.org/downloads/ and tick "Add Python to PATH").
pause
