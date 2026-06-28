# -*- coding: utf-8 -*-
"""
Ejecuta los bots existentes como subprocesos en un hilo de fondo.
El estado del Job se actualiza en BD conforme avanza.
"""
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app


def run_job_async(app, job_id: int):
    """Lanza el job en un hilo de fondo sin bloquear la petición web."""
    thread = threading.Thread(target=_execute_job, args=(app, job_id), daemon=True)
    thread.start()


def _execute_job(app, job_id: int):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from app.models.notification import Notification

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5
        db.session.commit()

        bots_dir = Path(current_app.config['BOTS_DIR'])
        script_path = bots_dir / job.service.bot_script if job.service.bot_script else None

        try:
            if not script_path or not script_path.exists():
                raise FileNotFoundError(f'Script no encontrado: {script_path}')

            params = job.get_params()
            cmd = [sys.executable, str(script_path)]
            if params.get('fecha'):
                cmd.append(params['fecha'])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
                cwd=str(script_path.parent),
                encoding='utf-8',
                errors='replace',
            )

            job.progress = 100
            if result.returncode == 0:
                job.status = 'completed'
                job.set_output({'stdout': result.stdout[-3000:], 'returncode': 0})
                _notify(db, job.user_id, job_id, 'success')
            else:
                job.status = 'failed'
                job.error_message = result.stderr[-2000:] or 'Error desconocido'
                _notify(db, job.user_id, job_id, 'error')

        except subprocess.TimeoutExpired:
            job.status = 'failed'
            job.error_message = 'El proceso excedió el tiempo límite (1h).'
            _notify(db, job.user_id, job_id, 'error')
        except Exception as exc:
            job.status = 'failed'
            job.error_message = str(exc)
            _notify(db, job.user_id, job_id, 'error')
        finally:
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()


def _notify(db, user_id: int, job_id: int, status: str):
    from app.models.notification import Notification
    if status == 'success':
        notif = Notification(
            user_id=user_id,
            title='✅ Trabajo completado',
            message='Tu generación de contenido ha finalizado correctamente.',
            type='success',
            link=f'/dashboard/jobs/{job_id}',
        )
    else:
        notif = Notification(
            user_id=user_id,
            title='❌ Error en el trabajo',
            message='Hubo un error al procesar tu solicitud. Revisa los detalles.',
            type='error',
            link=f'/dashboard/jobs/{job_id}',
        )
    db.session.add(notif)
