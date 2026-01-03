@echo off
chcp 65001 >nul
title Hattz Empire Launcher

echo ============================================
echo   HATTZ EMPIRE - Auto Start Script
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Starting Flask Server...
start "Hattz Flask" cmd /k "cd /d %~dp0 && python app.py"

echo [2/2] Waiting for Flask to initialize...
timeout /t 3 /nobreak >nul

echo [2/2] Starting ngrok Tunnel...
start "Hattz ngrok" cmd /k "ngrok http 5000 --url=caitlyn-supercivilized-intrudingly.ngrok-free.app"

echo.
echo ============================================
echo   Hattz Empire Started!
echo ============================================
echo.
echo Local:    http://localhost:5000
echo External: https://caitlyn-supercivilized-intrudingly.ngrok-free.app
echo.
echo Press any key to close this launcher...
pause >nul
