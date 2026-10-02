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

rem ---- setup (first run, or after an update changes requirements.txt) ---------
fc /b "requirements.txt" "%VENV%\requirements.txt" >nul 2>nul
if errorlevel 1 (
    echo Setting up, this can take a few minutes the first time...
    if not exist "%VPY%" (
        %PY% -m venv "%VENV%" || goto :fail
    )
    "%VPY%" -m pip install --quiet --upgrade pip
    "%VPY%" -m pip install --quiet --prefer-binary -r requirements.txt || goto :fail
    copy /y "requirements.txt" "%VENV%\requirements.txt" >nul
    echo Setup complete.
    echo.
)

rem ---- desktop shortcut: made once, and re-pointed if this folder moves -----------
set "SCMARK=%LOCALAPPDATA%\InBody\shortcut-for.txt"
set "SCFOR="
if exist "%SCMARK%" set /p SCFOR=<"%SCMARK%"
if /i not "%SCFOR%"=="%~dp0" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$here=(Get-Location).Path; $lnk=Join-Path ([Environment]::GetFolderPath('Desktop')) 'InBody Report.lnk';" ^
      "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($lnk); $s.TargetPath=Join-Path $here 'InBody Report.bat';" ^
      "$s.WorkingDirectory=$here; $s.IconLocation=(Join-Path $here 'inbody.ico')+',0'; $s.Description='Make an InBody report'; $s.Save();" ^
      "Set-Content -Path $env:SCMARK -Value ($here.TrimEnd('\')+'\') -Encoding ASCII" ^
      >nul 2>nul && (
        echo An "InBody Report" shortcut was added to your desktop.
        echo.
    )
)

"%VPY%" -m inbody.launcher %*
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Something went wrong. The details are above.
pause
exit /b 1
