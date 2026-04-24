@echo off
REM ============================================================
REM  YK One-Shot - Auto cipher capture + analysis
REM ============================================================
REM  Double-click to run. Auto:
REM    1. Find ZUFN.exe PID
REM    2. Attach Frida hook
REM    3. Prompt user to trigger 1 YK login
REM    4. Auto-run analysis + output (P, K, C) tuples
REM ============================================================

chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo.
echo ========================================================
echo   YK One-Shot Cipher Capture
echo ========================================================
echo.
echo   ATTENTION: After hook installs, IMMEDIATELY trigger
echo   1 YK login in KS184 (account+password, click Login).
echo.

python tools\yk_oneshot.py %*

echo.
echo ========================================================
echo   DONE. Press any key to close...
echo ========================================================
pause >nul
