@echo off
chcp 65001 >nul
echo Stopping Hattz Empire services...

taskkill /F /IM ngrok.exe 2>nul
for /f "tokens=2" %%a in ('tasklist ^| findstr python') do (
    taskkill /F /PID %%a 2>nul
)

echo Done.
timeout /t 2
