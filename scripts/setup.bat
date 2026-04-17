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
..\backend\venv\Scripts\python init_db.py
if errorlevel 1 (
    echo ERROR: Database init failed. Check if database is running.
    pause & exit /b 1
)
..\backend\venv\Scripts\python seed_config.py
cd ..

echo.
echo ========================================
echo  Setup complete!
echo  Admin account : admin / admin123456
echo  Doctor account: doctor01 / doctor123
echo  Next: run start-backend.bat and start-frontend.bat
echo ========================================
pause
