@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM MediScribe Desktop Agent launcher
REM
REM First run: auto create venv + pip install (3-5 min)
REM Next runs: just python main.py
REM
REM Agent listens on 127.0.0.1:7788 (fallback 7789-7792)
REM Stop: press Ctrl+C in this window
REM ============================================================

title MediScribe Desktop Agent

REM cd to script dir (in case user double-clicked from elsewhere)
cd /d %~dp0

echo.
echo ====================================================
echo   MediScribe Desktop Agent
echo ====================================================
echo.

REM ---- 1. locate python ----
REM try in this order: PATH 'python' -> Windows launcher 'py' -> common install paths
set "PYTHON_EXE="

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=python"
    goto :found_python
)

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py -3"
    goto :found_python
)

REM try common install locations on this machine
for %%P in (
    "D:\APP\DevelopApp\Python\Python312\python.exe"
    "D:\APP\DevelopApp\Python\Python311\python.exe"
    "D:\APP\DevelopApp\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
) do (
    if exist %%P (
        set "PYTHON_EXE=%%~P"
        goto :found_python
    )
)

echo [ERROR] python not found in PATH or common locations
echo Set PYTHON_EXE env var to the absolute path of python.exe, e.g.
echo   set PYTHON_EXE=D:\APP\DevelopApp\Python\Python312\python.exe
echo   run.bat
pause
exit /b 1

:found_python
echo [OK] using python: %PYTHON_EXE%
%PYTHON_EXE% --version

REM ---- 2. ensure venv ----
if not exist "venv\Scripts\python.exe" (
    echo [SETUP] creating venv ...
    %PYTHON_EXE% -m venv venv
    if errorlevel 1 (
        echo [ERROR] venv create failed
        pause
        exit /b 1
    )

    echo [SETUP] installing deps, takes 3-5 min, please wait ...
    venv\Scripts\python.exe -m pip install --upgrade pip
    venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] pip install failed, check network
        pause
        exit /b 1
    )
    echo [OK] deps installed
    echo.
)

REM ---- 3. run ----
REM Dev/test mode: pretend HIS is detected so AutoFillButton can complete
REM Remove or set to 0 when deploying to a real doctor PC that has HIS installed
set MEDISCRIBE_AGENT_MOCK_HIS=1

REM Dev/test mode: enable uvicorn auto-reload on file changes
REM (edit http_server.py / his/*.py without restarting this window)
set MEDISCRIBE_AGENT_RELOAD=1

echo [RUN] Agent listening on 127.0.0.1:7788
echo [MOCK] MEDISCRIBE_AGENT_MOCK_HIS=1 (pretend HIS detected)
echo [RELOAD] MEDISCRIBE_AGENT_RELOAD=1 (uvicorn hot reload)
echo [HINT] close window or Ctrl+C to stop
echo.

venv\Scripts\python.exe main.py

REM pause on abnormal exit for error inspection
if errorlevel 1 (
    echo.
    echo [WARN] Agent exited with error
    pause
)
