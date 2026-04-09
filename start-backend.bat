@echo off
chcp 65001 >nul
echo Starting backend...
cd /d "%~dp0"

echo [1/3] Starting database...
docker compose up -d db

echo [2/3] Running migrations...
cd backend
..\backend\venv\Scripts\python migrate.py
if errorlevel 1 (
    echo ERROR: Migration failed. Please run setup.bat first.
    pause & exit /b 1
)

echo [3/3] Starting backend server on port 8010...
set PYTHONUTF8=1
..\backend\venv\Scripts\uvicorn app.main:app --port 8010 --reload
