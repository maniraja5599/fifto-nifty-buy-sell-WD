@echo off
title NIFTY Pivot Gap Trading System Dashboard
color 0B
echo ========================================================
echo   STARTING NIFTY PIVOT GAP AUTOMATED TRADING SYSTEM
echo ========================================================
echo.

:: Show current time
echo Current Time: %TIME%
echo.

:: ── Market Hours Guard ─────────────────────────────────────────────────────
:: Get current hour and minute
for /f "tokens=1-2 delims=:. " %%a in ("%TIME%") do (
    set /a CUR_H=1%%a - 100
    set /a CUR_M=1%%b - 100
)

:: If before 09:00 — wait until 09:00
if %CUR_H% LSS 9 (
    echo [TIME] Before 09:00. Waiting for pre-open window...
    :WAIT_LOOP
    for /f "tokens=1-2 delims=:. " %%a in ("%TIME%") do (
        set /a CUR_H=1%%a - 100
        set /a CUR_M=1%%b - 100
    )
    if %CUR_H% LSS 9 (
        echo    Waiting... Current time: %TIME%
        timeout /t 30 >nul
        goto WAIT_LOOP
    )
    echo [TIME] 09:00 reached. Proceeding...
    echo.
)

:: If after 09:15 — WARN (scanner will use live OpenAlgo tick for open price)
if %CUR_H% GTR 9 (
    goto LATE_WARNING
) else (
    if %CUR_M% GTR 15 (
        goto LATE_WARNING
    ) else (
        goto AFTER_TIMECHECK
    )
)

:LATE_WARNING
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo  WARNING: Started AFTER 09:15 market open ^(%TIME%^)
echo  Gap will use live OpenAlgo tick - NOT from CSV.
echo  Make sure OpenAlgo is CONNECTED and RUNNING!
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo.
timeout /t 5 >nul

:AFTER_TIMECHECK

:: 1. Check Python
echo [1/4] Checking Python environment...
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in system PATH!
    pause
    exit /b
)

:: 2. Check if OpenAlgo is online on port 5000
echo [2/4] Checking if OpenAlgo Server is online...
powershell -Command "try { $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:5000' -TimeoutSec 1 -UseBasicParsing; exit 0 } catch { exit 1 }" >nul 2>nul
if %errorlevel% equ 0 (
    echo OpenAlgo Server is ONLINE.
) else (
    echo OpenAlgo Server is OFFLINE. Starting it in background...
    if exist "E:\Projects\OPENALGO\Angelone" (
        start "OpenAlgo Server Backend" /min cmd /c "cd /d E:\Projects\OPENALGO\Angelone && .venv\Scripts\python.exe app.py"
        echo Waiting 5 seconds for OpenAlgo to initialize...
        timeout /t 5 >nul
    ) else (
        echo WARNING: OpenAlgo not found at E:\Projects\OPENALGO\Angelone
        echo Please start OpenAlgo manually.
    )
)

:: 3. Launch Dashboard Server
echo.
echo [3/4] Launching Web Dashboard Server...
echo --------------------------------------------------------
echo   Web Dashboard : http://localhost:8080
echo   OpenAlgo      : http://127.0.0.1:5000
echo   Start Time    : %TIME%
echo --------------------------------------------------------
echo.
echo [4/4] Starting Auto-Scanner Engine...
echo Press Ctrl+C to stop the system at any time.
cd /d "%~dp0"

echo Starting unified Dashboard Server...
C:\Python314\python.exe dashboard_server.py
echo.
pause
