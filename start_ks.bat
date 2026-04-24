@echo off
REM ===================================================================
REM  KS Matrix one-click launcher (single window mode)
REM  All 4 services log into this one cmd window
REM  Each line prefixed with [AUTO] [DASH] [STRM] [WDG] color-coded
REM  Banner every 30s shows CPU/GPU/task status
REM  Ctrl+C stops all services
REM ===================================================================

title KS Matrix Runner
cd /d "D:\ks_automation"
chcp 65001 >nul

echo.
echo ============================================================
echo   KS Matrix starting...
echo   All logs scroll in this one window
echo   Press Ctrl+C to stop all services
echo ============================================================
echo.

python -u -m scripts.run_all %*

echo.
echo ============================================================
echo   Exited (errorlevel: %ERRORLEVEL%)
echo   Press any key to close this window
echo ============================================================
pause >nul
