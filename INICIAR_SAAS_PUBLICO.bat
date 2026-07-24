@echo off
chcp 65001 >nul
title CRONOS SaaS - Servidor Publico

echo.
echo  ==========================================
echo   CRONOS SaaS - Iniciando servidor publico
echo  ==========================================
echo.

cd /d "%~dp0"

REM Instalar dependencias si faltan
echo  Verificando dependencias...
pip install -r requirements.txt -q

REM Inicializar base de datos (seguro correrlo varias veces)
echo  Verificando base de datos...
python init_db.py

echo.
echo  Iniciando servidor Flask en puerto 5000...
start "CRONOS SaaS Flask" /B python run.py > saas_out.log 2>&1

REM Esperar que Flask arranque
timeout /t 4 /nobreak >nul

REM Crear tunel Cloudflare para el SaaS (puerto 5000)
echo  Creando tunel Cloudflare para el SaaS...
echo  La URL publica aparecera abajo en unos segundos.
echo.

REM Correr cloudflared y capturar la URL
cloudflared.exe tunnel --url http://localhost:5000 2>&1 | findstr /i "trycloudflare.com cfargotunnel.com"

echo.
echo  Tunel cerrado. Presiona cualquier tecla para salir.
pause >nul
