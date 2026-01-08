@echo off
chcp 65001 >nul
title Hattz Empire - Flask + ngrok

echo ============================================================
echo  HATTZ EMPIRE - Starting Services
echo ============================================================
echo.

:: Kill existing processes
echo [1/4] Cleaning up existing processes...
taskkill /F /IM ngrok.exe 2>nul
for /f "tokens=2" %%a in ('tasklist ^| findstr python') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 2 /nobreak >nul

:: Start Flask in background (no window)
echo [2/4] Starting Flask server...
start /B "" python app.py > logs\flask.log 2>&1
timeout /t 3 /nobreak >nul

:: Check Flask is running
curl -s http://localhost:5000/api/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Flask failed to start! Check logs\flask.log
    pause
    exit /b 1
)
echo       Flask running on http://localhost:5000

:: Start ngrok (no window)
echo [3/4] Starting ngrok tunnel...
start /B "" ngrok http 5000 --domain=caitlyn-supercivilized-intrudingly.ngrok-free.app > logs\ngrok.log 2>&1
timeout /t 3 /nobreak >nul

echo [4/4] Services started!
echo.
echo ============================================================
echo  LOCAL:  http://localhost:5000
echo  PUBLIC: https://caitlyn-supercivilized-intrudingly.ngrok-free.app
echo ============================================================
echo.
echo  Accounts:
echo    - admin / admin (all projects)
echo    - test / 1234 (test project only)
echo.
echo  Press Ctrl+C to stop, or close this window.
echo ============================================================

:: Keep window open and show Flask logs
echo.
echo [Flask Logs]
type logs\flask.log
echo.
echo Tailing logs... (Ctrl+C to stop)

:loop
timeout /t 5 /nobreak >nul
type logs\flask.log 2>nul | more +100
goto loop
