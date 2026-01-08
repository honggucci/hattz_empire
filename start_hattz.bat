@echo off
chcp 65001 >nul
title Hattz Empire Launcher

echo ============================================
echo   HATTZ EMPIRE - Auto Start Script
echo ============================================
echo.

cd /d "%~dp0"

:: logs 폴더 생성
if not exist logs mkdir logs

echo [1/2] Starting Flask Server (background)...
start /B "" python app.py > logs\flask.log 2>&1

echo [2/2] Waiting for Flask to initialize...
timeout /t 3 /nobreak >nul

echo [2/2] Starting ngrok Tunnel (background)...
start /B "" ngrok http 5000 --domain=caitlyn-supercivilized-intrudingly.ngrok-free.app > logs\ngrok.log 2>&1

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
