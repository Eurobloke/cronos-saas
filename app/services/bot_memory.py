# -*- coding: utf-8 -*-
"""
Memoria y conciencia del bot.
Antes de ejecutar cualquier tarea, el bot:
1. Revisa qué hizo antes (historial de jobs)
2. Verifica si ya existe ese contenido generado
3. Analiza si tiene sentido repetirlo
4. Pregunta al usuario si puede arrancar
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def get_bot_memory(user_id: int, bot_name: str, limit: int = 10) -> list:
    """Devuelve el historial reciente de jobs del usuario para este bot."""
    from app.models.job import Job
    from app.models.service import Service

    slug_map = {
        'HOROSCOPO': 'horoscopo_completo',
        'MOTIVACION': 'motivacion_completo',
        'NOTICIAS_RD': 'noticias_rd_completo',
    }
    slug = slug_map.get(bot_name.upper(), '')
    svc = Service.query.filter_by(slug=slug).first()
    if not svc:
        return []

    jobs = (Job.query
            .filter_by(user_id=user_id, service_id=svc.id)
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all())

    historial = []
    for j in jobs:
        params = j.get_params()
        historial.append({
            'job_id': j.id,
            'status': j.status,
            'fecha_ejecucion': j.created_at.strftime('%d/%m/%Y %H:%M') if j.created_at else '?',
            'params': params,
            'completado': j.status == 'completed',
        })
    return historial


def check_already_done(user_id: int, bot_name: str, params: dict) -> dict | None:
    """
    Verifica si ya existe una tarea idéntica completada recientemente.
    Retorna el job anterior si existe, None si no.
    """
    from app.models.job import Job
    from app.models.service import Service

    slug_map = {
        'HOROSCOPO': 'horoscopo_completo',
        'MOTIVACION': 'motivacion_completo',
        'NOTICIAS_RD': 'noticias_rd_completo',
    }
    slug = slug_map.get(bot_name.upper(), '')
    svc = Service.query.filter_by(slug=slug).first()
    if not svc:
        return None

    # Buscar en las últimas 24 horas
    hace_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = (Job.query
              .filter_by(user_id=user_id, service_id=svc.id, status='completed')
              .filter(Job.created_at >= hace_24h)
              .order_by(Job.created_at.desc())
              .limit(5)
              .all())

    for j in recent:
        j_params = j.get_params()
        # Comparar parámetros clave
        if bot_name.upper() == 'HOROSCOPO':
            fecha_nueva = params.get('fecha', 'hoy')
            fecha_vieja = j_params.get('fecha', '')
            if fecha_nueva == fecha_vieja or (fecha_nueva == 'hoy' and fecha_vieja == datetime.now().strftime('%Y-%m-%d')):
                return {
                    'job_id': j.id,
                    'fecha_ejecucion': j.created_at.strftime('%d/%m/%Y %H:%M'),
                    'params': j_params,
                }
    return None


def get_output_files(bot_name: str, bots_dir: Path) -> dict:
    """Verifica qué archivos generados existen en disco."""
    dirs_map = {
        'HOROSCOPO': bots_dir / 'horoscopo_bot' / 'output',
        'MOTIVACION': bots_dir / 'motivacion_bot' / 'output',
        'NOTICIAS_RD': bots_dir / 'noticias_rd_bot' / 'output',
    }
    output_dir = dirs_map.get(bot_name.upper())
    if not output_dir or not output_dir.exists():
        return {'total': 0, 'videos': 0, 'audios': 0, 'imagenes': 0, 'size_mb': 0}

    videos = list(output_dir.rglob('*.mp4'))
    audios = list(output_dir.rglob('*.mp3')) + list(output_dir.rglob('*.wav'))
    imagenes = list(output_dir.rglob('*.jpg')) + list(output_dir.rglob('*.png'))

    total_bytes = sum(f.stat().st_size for f in output_dir.rglob('*') if f.is_file())

    return {
        'total': len(videos) + len(audios) + len(imagenes),
        'videos': len(videos),
        'audios': len(audios),
        'imagenes': len(imagenes),
        'size_mb': round(total_bytes / (1024 * 1024), 1),
        'ultimo_video': videos[-1].name if videos else None,
    }


def build_awareness_message(user_id: int, bot_name: str, params: dict, bots_dir: Path) -> dict:
    """
    Construye el resumen de conciencia del bot:
    - Qué ha hecho antes
    - Si ya existe ese contenido
    - Los archivos en disco
    - Solicita confirmación del usuario

    Retorna dict con:
      - 'needs_confirmation': True/False
      - 'message': texto para mostrar al usuario
      - 'duplicate': job anterior si existe
    """
    historial = get_bot_memory(user_id, bot_name, limit=5)
    archivos = get_output_files(bot_name, bots_dir)
    duplicado = check_already_done(user_id, bot_name, params)

    partes = []

    # Resumen de lo que tiene en disco
    if archivos['total'] > 0:
        partes.append(
            f"📁 Tienes {archivos['videos']} videos, {archivos['audios']} audios y "
            f"{archivos['imagenes']} imágenes guardados ({archivos['size_mb']} MB en disco)."
        )

    # Historial reciente
    completados = [h for h in historial if h['completado']]
    if completados:
        ultimo = completados[0]
        partes.append(f"🕐 Último trabajo completado: {ultimo['fecha_ejecucion']}.")

    # Advertencia de duplicado
    if duplicado:
        partes.append(
            f"⚠️ Ya generé este mismo contenido hoy a las {duplicado['fecha_ejecucion']} "
            f"(Job #{duplicado['job_id']}). ¿Seguro que quieres generarlo de nuevo?"
        )
        return {
            'needs_confirmation': True,
            'message': '\n'.join(partes),
            'duplicate': duplicado,
        }

    # Sin duplicado — puede proceder pero informa
    if partes:
        partes.append("✅ Puedo proceder. ¿Confirmas que quieres ejecutarlo ahora?")
        return {
            'needs_confirmation': True,
            'message': '\n'.join(partes),
            'duplicate': None,
        }

    # Primera vez — procede directamente
    return {
        'needs_confirmation': False,
        'message': '',
        'duplicate': None,
    }
