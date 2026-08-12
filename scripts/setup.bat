@echo off
chcp 65001 >nul
echo ========================================
echo  MediScribe Setup (Run once)
echo ========================================
cd /d "%~dp0"

echo.
echo [1/5] Creating Python virtual environment...
python -m venv backend\venv
if errorlevel 1 (
    echo ERROR: Failed to create venv. Make sure Python is installed.
    pause & exit /b 1
)

echo.
echo [2/5] Installing backend dependencies...
backend\venv\Scripts\pip install -r backend\requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install backend dependencies.
    pause & exit /b 1
)

echo.
echo [3/5] Installing frontend dependencies...
cd frontend
npm install
if errorlevel 1 (
    echo ERROR: Failed to install frontend dependencies.
    pause & exit /b 1
)
cd ..

echo.
echo [4/5] Starting database...
docker compose up -d db
echo Waiting for database to be ready...
timeout /t 8 /nobreak >nul

echo.
echo [5/5] Initializing database tables and default data...
cd backend
REM 表结构统一走 alembic（2026-08-12 迁移收口）：guard 只打标记，upgrade 建/改表
venv\Scripts\python alembic_guard.py
venv\Scripts\python -m alembic upgrade head
if errorlevel 1 (
    echo ERROR: Database migration failed. Check if database is running.
    pause & exit /b 1
)
REM init_db 现在只播种子（admin/doctor01/科室/Prompt 模板）
venv\Scripts\python init_db.py
if errorlevel 1 (
    echo ERROR: Database seed failed.
    pause & exit /b 1
)
venv\Scripts\python seed_config.py
cd ..

echo.
echo ========================================
echo  Setup complete!
echo  Admin account : admin / admin123456
echo  Doctor account: doctor01 / doctor123
echo  Next: run start-backend.bat and start-frontend.bat
echo ========================================
pause
