@echo off
echo Stopping old backend on port 8010...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8010" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting backend on port 8010...
cd /d "%~dp0backend"
set PYTHONUTF8=1
venv\Scripts\uvicorn app.main:app --port 8010 --reload
