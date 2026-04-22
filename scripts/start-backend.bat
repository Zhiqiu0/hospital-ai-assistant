@echo off
chcp 65001 >nul
echo Starting backend...

echo [1/3] Starting database...
cd /d "%~dp0.."
docker compose up -d db

echo [2/3] Running migrations...
cd /d "%~dp0..\backend"
venv\Scripts\python migrate.py
if errorlevel 1 (
    echo ERROR: Migration failed. Please run setup.bat first.
    pause & exit /b 1
)

echo [3/3] Starting backend server on port 8010...
set PYTHONUTF8=1
venv\Scripts\uvicorn app.main:app --port 8010 --reload
pause
