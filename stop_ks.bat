@echo off
title KS Matrix Stopper
chcp 65001 >nul

echo.
echo ============================================================
echo   KS Matrix - Stopping all services
echo ============================================================
echo.

echo [1/4] Stopping Autopilot...
wmic process where "name='python.exe' and CommandLine like '%%run_autopilot%%'" delete 2>nul | find "success" >nul

echo [2/4] Stopping Dashboard API...
wmic process where "name='python.exe' and CommandLine like '%%dashboard.app%%'" delete 2>nul | find "success" >nul

echo [3/4] Stopping Streamlit...
wmic process where "name='python.exe' and CommandLine like '%%streamlit%%run%%'" delete 2>nul | find "success" >nul

echo [4/4] Stopping Watchdog + run_all...
wmic process where "name='python.exe' and CommandLine like '%%dashboard_watchdog%%'" delete 2>nul | find "success" >nul
wmic process where "name='python.exe' and CommandLine like '%%run_all%%'" delete 2>nul | find "success" >nul
wmic process where "name='python.exe' and CommandLine like '%%live_dashboard%%'" delete 2>nul | find "success" >nul

echo.
echo Done. Press any key to close.
pause >nul
