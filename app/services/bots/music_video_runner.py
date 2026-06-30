# -*- coding: utf-8 -*-
"""Runner para Music Video Bot — genera video musical de la primera canción en cola."""
import subprocess
import sys
import threading
import json
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(r'C:\Users\franc\music\music_video_bot')


def run_pipeline_async(app, job_id: int, params: dict):
    thread = threading.Thread(target=_execute, args=(app, job_id, params), daemon=True)
    thread.start()


def _execute(app, job_id: int, params: dict):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5
        job.progress_message = 'Iniciando Music Video Bot...'
        db.session.commit()

        import os
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}

        # Leer cola de canciones
        cola_file = BOT_DIR / 'cola_videos.json'
        if not cola_file.exists():
            job.status = 'failed'
            job.error_message = 'No hay cola de videos. Genera la cola primero desde el bot local.'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        try:
            cola = json.loads(cola_file.read_text(encoding='utf-8'))
        except Exception as e:
            cola = []

        pendientes = [c for c in cola if not c.get('completado')]
        if not pendientes:
            job.status = 'failed'
            job.error_message = 'La cola de videos está vacía. Agrega canciones MP3 y genera la cola desde el bot local.'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        cancion = pendientes[0]
        ruta_mp3 = cancion.get('ruta', '')
        tema = cancion.get('tema', 'musica latina')

        job.progress = 20
        job.progress_message = f'Creando video para: {Path(ruta_mp3).name}'
        db.session.commit()

        script = BOT_DIR / 'crear_video_para_cancion.py'
        if not script.exists():
            job.status = 'failed'
            job.error_message = f'Script no encontrado: {script}'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        cmd = [sys.executable, str(script), ruta_mp3, tema]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=3600, cwd=str(BOT_DIR),
                encoding='utf-8', errors='replace', env=env,
            )
            output = result.stdout[-2000:] + result.stderr[-500:]

            if result.returncode == 0:
                # Publicar si se pidió
                _publicar(job, params, env, output)
            else:
                job.status = 'failed'
                job.error_message = output[:2000]
                job.progress_message = '❌ Error en Music Video Bot'
                _notify(db, job.user_id, job_id, False)

        except subprocess.TimeoutExpired:
            job.status = 'failed'
            job.error_message = 'Tiempo límite excedido (1h)'
            _notify(db, job.user_id, job_id, False)
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            _notify(db, job.user_id, job_id, False)
        finally:
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()


def _publicar(job, params, env, prev_output):
    from app.extensions import db
    import subprocess, sys

    pasos = []
    if params.get('subir_youtube') or params.get('yt_shorts'):
        pasos.append(('YouTube', BOT_DIR / 'subir_youtube.py'))
    if params.get('publicar_facebook') or params.get('fb_reels'):
        pasos.append(('Facebook', BOT_DIR / 'publicar_facebook.py'))

    salida_total = prev_output
    for nombre, script in pasos:
        if not script.exists():
            continue
        job.progress_message = f'Publicando en {nombre}...'
        db.session.commit()
        try:
            r = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=600,
                cwd=str(BOT_DIR), encoding='utf-8', errors='replace', env=env,
            )
            salida_total += r.stdout[-500:]
        except Exception as e:
            salida_total += f'\nError {nombre}: {e}'

    job.status = 'completed'
    job.progress = 100
    job.progress_message = '✅ Music Video generado'
    job.set_output({'stdout': salida_total})
    _notify(db, job.user_id, job.id, True)


def _notify(db, user_id, job_id, ok):
    from app.models.notification import Notification
    db.session.add(Notification(
        user_id=user_id,
        title='✅ Music Video Bot listo' if ok else '❌ Error en Music Video Bot',
        message='Video musical creado y publicado.' if ok else 'Error al generar video musical.',
        type='success' if ok else 'error',
        link=f'/dashboard/jobs/{job_id}',
    ))
    db.session.commit()
