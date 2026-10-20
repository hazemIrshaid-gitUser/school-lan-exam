@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Collect problem information
cd /d "%~dp0"
echo.
set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if defined PY "%PY%" report_problem.py
if defined PY goto done
python --version >nul 2>&1
if %errorlevel%==0 (python report_problem.py & goto done)
py --version >nul 2>&1
if %errorlevel%==0 (py report_problem.py & goto done)
echo Python was not found on this computer - that may be the problem itself.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
set R=problem_report_no_python.txt
echo PROBLEM REPORT - PYTHON NOT FOUND> "%R%"
ver>> "%R%" 2>&1
echo where python:>> "%R%"
where python>> "%R%" 2>&1
where py>> "%R%" 2>&1
echo Folder: "%~dp0">> "%R%"
dir /b>> "%R%" 2>&1
echo A small report was saved: %R%
start "" notepad "%R%"
:done
echo.
pause
