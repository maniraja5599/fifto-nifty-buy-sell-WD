@echo off
title NIFTY Pivot Gap Trading System Dashboard
color 0B
echo ========================================================
echo   STARTING NIFTY PIVOT GAP AUTOMATED TRADING SYSTEM
echo ========================================================
echo.

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
    echo OpenAlgo Server is already ONLINE.
) else (
    echo OpenAlgo Server is OFFLINE. Starting it automatically in background...
    if exist "E:\Projects\OPENALGO\Angelone" (
        start "OpenAlgo Server Backend" /min cmd /c "cd /d E:\Projects\OPENALGO\Angelone && .venv\Scripts\python.exe app.py"
        echo Waiting 5 seconds for OpenAlgo to initialize...
        timeout /t 5 >nul
    ) else (
        echo WARNING: OpenAlgo directory not found at E:\Projects\OPENALGO\Angelone!
        echo Please ensure OpenAlgo is running manually.
    )
)

:: 3. Launch Dashboard Server
echo.
echo [3/4] Launching Web Dashboard Server...
echo --------------------------------------------------------
echo   Web Dashboard URL : http://localhost:8080
echo   OpenAlgo Server   : http://127.0.0.1:5000
echo --------------------------------------------------------
echo.
echo [4/4] Starting Auto-Scanner Engine (will monitor 09:15)...
echo.
echo Press Ctrl+C in this window to stop the system at any time.
echo.

cd /d "C:\Users\manir\.gemini\antigravity\scratch\fifto-nifty-pivot-gap"
python dashboard_server.py

pause
