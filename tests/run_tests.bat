@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>&1 || (echo Python not found. Install it from python.org and tick "Add python.exe to PATH" & pause & exit /b 1)
python -c "import pytest, openpyxl, playwright, pypdf, psutil" >nul 2>&1 || (echo Installing test tools... & python -m pip install pytest openpyxl playwright pypdf psutil pymupdf pillow)
echo Running exam package tests (about 20 minutes; browser tests need Microsoft Edge; Office tests need Excel and LibreOffice, otherwise they are skipped)...
python -X utf8 -m pytest -q -p no:cacheprovider -rx %*
echo.
pause
