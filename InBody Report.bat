@echo off
setlocal
title InBody Report
rem Double-click to pick a scan, or drag InBody PDFs (and optionally the last report) onto this file.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
rem Nothing is written into this folder except reports, so it can live on any drive.
set PYTHONDONTWRITEBYTECODE=1
set "VENV=%LOCALAPPDATA%\InBody\venv"
set "VPY=%VENV%\Scripts\python.exe"

rem ---- find Python -----------------------------------------------------------
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
rem "python" alone may be the Microsoft Store shortcut, so check it really runs.
if not defined PY (
    python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python is not installed.
    echo Install it from python.org and tick "Add python.exe to PATH", then run this again.
    start "" https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

rem ---- first run: private environment + packages (in %LOCALAPPDATA%\InBody) ----
if not exist "%VENV%\setup-done.txt" (
    echo First-time setup, this takes a minute...
    if not exist "%VPY%" (
        %PY% -m venv "%VENV%" || goto :fail
    )
    "%VPY%" -m pip install --quiet --upgrade pip
    "%VPY%" -m pip install --quiet -r requirements.txt || goto :fail
    echo ok> "%VENV%\setup-done.txt"
    echo Setup complete.
    echo.
)

"%VPY%" -m inbody.launcher %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong. The details are above.
pause
exit /b 1
