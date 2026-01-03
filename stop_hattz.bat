@echo off
chcp 65001 >nul
title Hattz Empire - Stop

echo ============================================
echo   HATTZ EMPIRE - Stopping Services
echo ============================================
echo.

echo [1/2] Stopping Flask Server...
taskkill /FI "WINDOWTITLE eq Hattz Flask*" /F >nul 2>&1

echo [2/2] Stopping ngrok Tunnel...
taskkill /IM ngrok.exe /F >nul 2>&1

echo.
echo ============================================
echo   All Hattz Empire services stopped.
echo ============================================
pause
