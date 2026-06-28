@echo off
chcp 65001 >nul
title Cronos SaaS — Instalador
echo.
echo  ╔════════════════════════════════════════════╗
echo  ║        CRONOS SAAS — INSTALACION          ║
echo  ╚════════════════════════════════════════════╝
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python no encontrado. Instala Python 3.11+
    pause & exit
)

:: Crear entorno virtual
echo  [1/4] Creando entorno virtual...
python -m venv venv
call venv\Scripts\activate.bat

:: Instalar dependencias
echo  [2/4] Instalando dependencias...
pip install -r requirements.txt -q

:: Crear archivo .env
if not exist .env (
    echo  [3/4] Creando archivo .env desde .env.example...
    copy .env.example .env
    echo.
    echo  IMPORTANTE: Edita el archivo .env y configura:
    echo    - SECRET_KEY (clave secreta larga y aleatoria)
    echo    - MAIL_USERNAME / MAIL_PASSWORD (tu Gmail)
    echo    - PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET
    echo    - ADMIN_EMAIL / ADMIN_PASSWORD
    echo.
    notepad .env
) else (
    echo  [3/4] Archivo .env ya existe.
)

:: Inicializar base de datos
echo  [4/4] Inicializando base de datos...
python init_db.py

echo.
echo  ╔════════════════════════════════════════════╗
echo  ║   Instalacion completada                   ║
echo  ║   Ejecuta INICIAR.bat para arrancar        ║
echo  ╚════════════════════════════════════════════╝
echo.
pause
