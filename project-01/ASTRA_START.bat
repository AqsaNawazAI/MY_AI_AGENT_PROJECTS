@echo off
setlocal EnableExtensions
title ASTRA WORLD v29 - ONE CLICK START
cd /d "%~dp0"

echo.
echo ============================================================
echo                  ASTRA WORLD v29 - ONE CLICK START
echo ============================================================
echo.

REM ============================================================
REM 1. Stop an old ASTRA backend on port 8765
REM ============================================================
echo [1/5] Checking ASTRA backend...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr LISTENING ^| findstr ":8765"') do (
    echo Stopping old ASTRA process %%P...
    taskkill /PID %%P /F >nul 2>&1
)

REM ============================================================
REM 2. Check/install Python Playwright package
REM ============================================================
echo [2/5] Checking Playwright...
python -c "import playwright" >nul 2>nul
if errorlevel 1 (
    echo Playwright package is missing.
    echo Installing it now...
    python -m pip install playwright
    if errorlevel 1 (
        echo.
        echo ERROR: Could not install Playwright.
        pause
        exit /b 1
    )
)

REM ============================================================
REM 3. Install Chromium only when it is not already available
REM ============================================================
echo [3/5] Checking Chromium browser...
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.executable_path; p.stop(); import os; raise SystemExit(0 if os.path.exists(b) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Chromium browser is missing.
    echo Installing Chromium. This may take some time...
    python -m playwright install chromium
    if errorlevel 1 (
        echo.
        echo WARNING: Chromium installation failed.
        echo ASTRA backend will still be attempted.
    )
)

REM ============================================================
REM 4. Start Chrome Browser Runtime on port 9222
REM ============================================================
echo [4/5] Starting Browser Runtime on port 9222...

set "ASTRA_BROWSER_PROFILE=%~dp0data\browser-profile"
if not exist "%ASTRA_BROWSER_PROFILE%" mkdir "%ASTRA_BROWSER_PROFILE%"

netstat -ano | findstr LISTENING | findstr ":9222" >nul
if errorlevel 1 (
    if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
        start "ASTRA Browser Runtime" /min "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%ASTRA_BROWSER_PROFILE%" --no-first-run
    ) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
        start "ASTRA Browser Runtime" /min "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%ASTRA_BROWSER_PROFILE%" --no-first-run
    ) else (
        echo Chrome was not found in the standard installation folders.
        echo Browser Runtime may remain OFFLINE.
    )
) else (
    echo Browser Runtime is already running on port 9222.
)

timeout /t 2 /nobreak >nul

REM ============================================================
REM 5. Start ASTRA backend + open dashboard
REM ============================================================
echo [5/5] Starting ASTRA backend...

if not exist "backend\main.py" (
    echo.
    echo ERROR: backend\main.py was not found.
    pause
    exit /b 1
)

start "ASTRA BACKEND - KEEP OPEN" cmd /k "cd /d ""%~dp0"" && python backend\main.py"

timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8765/"

echo.
echo ============================================================
echo                    ASTRA IS STARTING
echo ============================================================
echo.
echo Everything is handled by this ONE BAT:
echo   - Python Playwright check
echo   - Chromium check/install
echo   - Chrome Browser Runtime :9222
echo   - ASTRA Backend :8765
echo   - Dashboard
echo.
echo You do NOT need to run any other BAT file.
echo Keep the ASTRA BACKEND window open while using ASTRA.
echo.
endlocal
