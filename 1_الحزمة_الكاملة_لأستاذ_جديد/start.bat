@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Exam Server
cd /d "%~dp0"
echo.
echo Starting exam server... keep this window open during the exam.
python --version >nul 2>&1
if %errorlevel%==0 (python server.py) else (py server.py)
echo.
echo If you see an error above, read it: either a problem in the exam files, or Python is not installed (https://www.python.org/downloads/ - tick "Add Python to PATH").
pause
