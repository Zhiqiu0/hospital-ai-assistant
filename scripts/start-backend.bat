@echo off
chcp 65001 >nul
echo Starting backend...

echo [1/3] Starting database...
cd /d "%~dp0.."
docker compose up -d db

echo [2/3] Running migrations...
cd /d "%~dp0..\backend"
REM 迁移单通道（2026-08-12 收口）：alembic 是唯一 schema 真源
venv\Scripts\python alembic_guard.py
venv\Scripts\python -m alembic upgrade head
if errorlevel 1 (
    echo ERROR: Migration failed. Please run setup.bat first.
    pause & exit /b 1
)

echo [3/3] Starting backend server on port 8010...
set PYTHONUTF8=1
venv\Scripts\uvicorn app.main:app --port 8010 --reload
pause
