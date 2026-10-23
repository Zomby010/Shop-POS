@echo off
rem Shop POS launcher: double-click to start the POS and open it in the browser.
title Shop POS
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe

rem Port: 8000 unless port.txt in this folder holds another number (e.g. 8001).
if not defined SHOPPOS_PORT set SHOPPOS_PORT=8000
if exist port.txt for /f "usebackq tokens=1" %%p in ("port.txt") do set SHOPPOS_PORT=%%p

if not exist "%PY%" (
    echo First run: setting up Shop POS. This needs the internet once and takes a few minutes...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist "%PY%" (
        echo Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
        pause
        exit /b 1
    )
)

rem Install or update libraries only when requirements.txt has changed.
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if errorlevel 1 (
    echo Installing libraries...
    "%PY%" -m pip install --quiet --upgrade pip
    "%PY%" -m pip install --quiet -r requirements.txt || (echo Library install failed. Check the internet connection and try again. & pause & exit /b 1)
    copy /y requirements.txt .venv\requirements.installed >nul
)

"%PY%" manage.py migrate --noinput >nul || (echo Database update failed. & pause & exit /b 1)
"%PY%" manage.py collectstatic --noinput >nul
"%PY%" manage.py setup_owner
"%PY%" manage.py backup --if-due

start "" http://localhost:%SHOPPOS_PORT%/
"%PY%" serve.py
pause
