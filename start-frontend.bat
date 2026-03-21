@echo off
echo Stopping old frontend on port 5174...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5174" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting frontend on port 5174...
cd /d "%~dp0frontend"
npm run dev
