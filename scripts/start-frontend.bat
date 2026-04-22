@echo off
chcp 65001 >nul
echo Starting frontend on port 5174...
cd /d "%~dp0..\frontend"
npm run dev
