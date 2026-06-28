@echo off
chcp 65001 >nul
title Cronos SaaS

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

echo.
echo  CRONOS SAAS - Iniciando servidor...
echo  URL: http://localhost:5000
echo  Presiona Ctrl+C para detener
echo.

set FLASK_ENV=development
python run.py
pause
