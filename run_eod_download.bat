@echo off
title NIFTY Spot Data EOD Auto-Downloader
color 0A
echo ========================================================
echo   NIFTY SPOT DATA EOD AUTO-DOWNLOADER
echo ========================================================
echo.
echo [1/2] Changing directory to project folder...
cd /d "E:\Projects\fifto-nifty-pivot-gap-engine"

echo [2/2] Running NSE Spot Downloader...
python download_nse_data.py

echo.
echo ========================================================
echo   SYNC COMPLETED SUCCESSFULLY!
echo ========================================================
timeout /t 5
