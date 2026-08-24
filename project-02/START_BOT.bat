@echo off
title V5 Elite - Forex Bot
color 0A
cls
echo ========================================================
echo   FOREX BOT V5 ELITE - Complete Edition
echo ========================================================
echo.
cd /d "%~dp0"

echo [1/4] Installing packages...
python -m pip install requests flask flask-cors numpy --quiet 2>nul
echo       Done!

echo [2/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found! Download: python.org/downloads
    pause & exit
)

echo [3/4] Verifying packages...
python -c "import requests,flask,numpy" >nul 2>&1
if errorlevel 1 (
    echo Installing missing packages...
    python -m pip install requests flask flask-cors numpy
)

echo [4/4] Starting...
echo.
echo ========================================================
echo   Dashboard: http://localhost:5000
echo   Open Chrome/Edge and go to: localhost:5000
echo   Keep this window OPEN while bot runs!
echo   Press Ctrl+C to STOP
echo ========================================================
echo.
start "" "http://localhost:5000"
timeout /t 2 /nobreak >nul
python app.py

echo.
echo Bot stopped.
pause
