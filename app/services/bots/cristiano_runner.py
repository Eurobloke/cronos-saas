# -*- coding: utf-8 -*-
"""Runner dedicado para cristiano_bot.
main.py usa: --ahora  --pack N  --solo-generar
"""
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

STEPS = [
    # (script_o_flag, mensaje, p_inicio, p_fin, es_critico)
    # El cristiano_bot tiene un main.py que hace todo en un solo proceso
    # Pasos individuales opcionales via flags
]


def run_pipeline_async(app, job_id: int, params: dict):
    thread = threading.Thread(target=_execute, args=(app, job_id, params), daemon=True)
    thread.start()


def _execute(app, job_id: int, params: dict):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from flask import current_app

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5
        job.progress_message = 'Iniciando Cristiano Bot...'
        db.session.commit()

        bot_dir = Path(current_app.config['BOTS_DIR']) / 'cristiano_bot'
        script = bot_dir / 'main.py'

        if not script.exists():
            job.status = 'failed'
            job.error_message = f'Script no encontrado: {script}'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        import os
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        if params.get('user_workspace'):
            env['CRONOS_USER_WORKSPACE'] = params['user_workspace']
        if params.get('fb_url'):
            env['CRONOS_FB_URL'] = params['fb_url']
        env['CRONOS_FB_REELS']  = '1' if params.get('fb_reels') else '0'
        env['CRONOS_FB_FOTOS']  = '1' if params.get('fb_fotos') else '0'
        env['CRONOS_YT_SHORTS'] = '1' if params.get('yt_shorts') else '0'

        # Determinar si se publica o solo se genera
        solo_generar = not (params.get('publicar_facebook') or params.get('fb_reels')
                            or params.get('fb_fotos') or params.get('subir_youtube')
                            or params.get('yt_shorts'))

        cmd = [sys.executable, str(script), '--ahora']
        if solo_generar:
            cmd.append('--solo-generar')

        job.progress = 15
        job.progress_message = 'Generando contenido cristiano...'
        db.session.commit()

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=3600, cwd=str(bot_dir),
                encoding='utf-8', errors='replace', env=env,
            )
            output = result.stdout[-2000:] + result.stderr[-500:]

            if result.returncode == 0:
                job.status = 'completed'
                job.progress = 100
                job.progress_message = '✅ Contenido cristiano generado'
                job.set_output({'stdout': output})
                _notify(db, job.user_id, job_id, True)
            else:
                job.status = 'failed'
                job.error_message = output[:2000]
                job.progress_message = '❌ Error en Cristiano Bot'
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


def _notify(db, user_id, job_id, ok):
    from app.models.notification import Notification
    db.session.add(Notification(
        user_id=user_id,
        title='✅ Cristiano Bot listo' if ok else '❌ Error en Cristiano Bot',
        message='Contenido generado y publicado.' if ok else 'Error al generar contenido.',
        type='success' if ok else 'error',
        link=f'/dashboard/jobs/{job_id}',
    ))
    db.session.commit()
