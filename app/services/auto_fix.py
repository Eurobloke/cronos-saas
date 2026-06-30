# -*- coding: utf-8 -*-
"""
Sistema de auto-corrección en tiempo real para los bots.
Detecta errores comunes, aplica el fix y reintenta automáticamente.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

MAX_REINTENTOS = 3

# ─── Patrones de error y su corrección ──────────────────────────────────────

ERROR_PATTERNS = [
    {
        'nombre': 'UnicodeEncodeError',
        'patron': r'UnicodeEncodeError|charmap.*encode|cp1252',
        'mensaje': 'Error de codificación de caracteres — aplicando UTF-8...',
        'fix': 'encoding',
    },
    {
        'nombre': 'ModuleNotFoundError',
        'patron': r"ModuleNotFoundError: No module named '([^']+)'",
        'mensaje': 'Módulo faltante — instalando automáticamente...',
        'fix': 'install_module',
    },
    {
        'nombre': 'FileNotFoundError',
        'patron': r'FileNotFoundError|No such file or directory',
        'mensaje': 'Archivo no encontrado — creando carpetas necesarias...',
        'fix': 'create_dirs',
    },
    {
        'nombre': 'ConnectionError',
        'patron': r'ConnectionError|ConnectTimeout|ReadTimeout|requests\.exceptions',
        'mensaje': 'Error de conexión — reintentando en 5 segundos...',
        'fix': 'retry_wait',
    },
    {
        'nombre': 'JSONDecodeError',
        'patron': r'JSONDecodeError|json\.decoder|Expecting value',
        'mensaje': 'Error al leer respuesta de IA — reintentando...',
        'fix': 'retry_wait',
    },
    {
        'nombre': 'RateLimitError',
        'patron': r'RateLimitError|rate.limit|429|Too Many Requests',
        'mensaje': 'Límite de API alcanzado — esperando 30 segundos...',
        'fix': 'retry_long_wait',
    },
    {
        'nombre': 'OutOfMemory',
        'patron': r'MemoryError|out of memory|Cannot allocate',
        'mensaje': 'Memoria insuficiente — liberando recursos...',
        'fix': 'retry_wait',
    },
    {
        'nombre': 'PermissionError',
        'patron': r'PermissionError|Access is denied|WinError 5',
        'mensaje': 'Permiso denegado en archivo — reintentando...',
        'fix': 'retry_wait',
    },
    {
        'nombre': 'APIKeyError',
        'patron': r'AuthenticationError|Invalid API key|api.key',
        'mensaje': 'Error de clave de API — verifica tu configuración en .env',
        'fix': 'no_retry',
    },
    {
        'nombre': 'TimeoutExpired',
        'patron': r'TimeoutExpired|timed out|Timeout',
        'mensaje': 'El proceso tardó demasiado — reintentando con más tiempo...',
        'fix': 'retry_wait',
    },
]


def _detectar_error(stderr: str, stdout: str) -> dict | None:
    """Analiza la salida del proceso y detecta el tipo de error."""
    texto = (stderr or '') + '\n' + (stdout or '')
    for patron in ERROR_PATTERNS:
        match = re.search(patron['patron'], texto, re.IGNORECASE)
        if match:
            resultado = dict(patron)
            resultado['match'] = match
            resultado['texto_error'] = texto[-1500:]
            return resultado
    return None


def _aplicar_fix(error_info: dict, script: Path, bot_dir: Path, env_extra: dict) -> bool:
    """Intenta corregir el error. Retorna True si el fix fue aplicado."""
    fix = error_info['fix']

    if fix == 'encoding':
        env_extra['PYTHONIOENCODING'] = 'utf-8'
        env_extra['PYTHONUTF8'] = '1'
        return True

    elif fix == 'install_module':
        match = error_info['match']
        modulo = match.group(1) if match.lastindex else None
        if modulo:
            # Mapeo de nombres de módulo a paquete pip
            pip_map = {
                'cv2': 'opencv-python',
                'PIL': 'Pillow',
                'sklearn': 'scikit-learn',
                'bs4': 'beautifulsoup4',
                'dotenv': 'python-dotenv',
                'anthropic': 'anthropic',
                'openai': 'openai',
                'gtts': 'gTTS',
                'moviepy': 'moviepy',
            }
            paquete = pip_map.get(modulo, modulo)
            try:
                subprocess.run(
                    [sys.executable, '-m', 'pip', 'install', paquete, '-q'],
                    timeout=120, check=True
                )
                return True
            except Exception:
                return False
        return False

    elif fix == 'create_dirs':
        # Crear carpetas comunes que suelen faltar
        for carpeta in ['output', 'temp', 'audios', 'imagenes', 'videos', 'subtitulos']:
            (bot_dir / carpeta).mkdir(exist_ok=True)
        return True

    elif fix == 'retry_wait':
        time.sleep(5)
        return True

    elif fix == 'retry_long_wait':
        time.sleep(30)
        return True

    elif fix == 'no_retry':
        return False  # No se puede auto-corregir

    return True


def ejecutar_con_autofix(
    script_name: str,
    bot_dir: Path,
    cmd_extra: list = None,
    timeout: int = 3600,
    update_fn=None,
    extra_env: dict = None,
) -> tuple:
    """
    Ejecuta un script con auto-corrección en tiempo real.

    Args:
        script_name: nombre del archivo .py
        bot_dir: directorio del bot
        cmd_extra: argumentos adicionales al script
        timeout: tiempo máximo en segundos
        update_fn: función opcional update_fn(mensaje) para reportar estado

    Returns:
        (exito, salida_o_error)
    """
    script = bot_dir / script_name
    if not script.exists():
        return False, f'Script no encontrado: {script}'

    env_extra = {
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
    }
    if extra_env:
        env_extra.update(extra_env)

    for intento in range(1, MAX_REINTENTOS + 1):
        import os
        env = {**os.environ, **env_extra}

        cmd = [sys.executable, str(script)] + (cmd_extra or [])

        if intento > 1 and update_fn:
            update_fn(f'Reintento {intento}/{MAX_REINTENTOS}: {script_name}...')

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(bot_dir),
                encoding='utf-8',
                errors='replace',
                env=env,
            )

            if result.returncode == 0:
                return True, result.stdout[-2000:]

            # Detectar qué tipo de error ocurrió
            error_info = _detectar_error(result.stderr, result.stdout)

            if error_info:
                if update_fn:
                    update_fn(f'[Auto-fix] {error_info["mensaje"]}')

                fix_ok = _aplicar_fix(error_info, script, bot_dir, env_extra)

                if not fix_ok or error_info['fix'] == 'no_retry':
                    # Error no recuperable
                    return False, (
                        f'Error ({error_info["nombre"]}): {error_info["texto_error"]}'
                    )
                # Fix aplicado → reintentar en el siguiente loop
                continue
            else:
                # Error desconocido — reintentar igual
                if intento < MAX_REINTENTOS:
                    if update_fn:
                        update_fn(f'Error inesperado — reintentando ({intento}/{MAX_REINTENTOS})...')
                    time.sleep(3)
                    continue
                return False, result.stderr[-2000:] or result.stdout[-1000:]

        except subprocess.TimeoutExpired:
            if intento < MAX_REINTENTOS:
                if update_fn:
                    update_fn(f'Timeout — reintentando con más tiempo ({intento}/{MAX_REINTENTOS})...')
                timeout = int(timeout * 1.5)  # Aumentar timeout en cada reintento
                continue
            return False, f'El proceso excedió el tiempo límite ({timeout}s).'

        except Exception as exc:
            return False, str(exc)

    return False, f'Falló después de {MAX_REINTENTOS} intentos.'
