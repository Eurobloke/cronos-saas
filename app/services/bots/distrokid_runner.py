# -*- coding: utf-8 -*-
"""Runner para DistroKid Bot — sube álbum WAV a DistroKid con portada generada."""
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(r'C:\Users\franc\music\proyecto_album_videos\distrokid_bot')


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
        job.progress_message = 'Iniciando DistroKid Bot...'
        db.session.commit()

        script = BOT_DIR / 'distrokid_bot.py'
        if not script.exists():
            job.status = 'failed'
            job.error_message = f'Script no encontrado: {script}'
            job.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        import os
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}

        job.progress = 15
        job.progress_message = 'Subiendo álbum a DistroKid...'
        db.session.commit()

        try:
            result = subprocess.run(
                [sys.executable, str(script), '--auto'],
                capture_output=True, text=True,
                timeout=3600, cwd=str(BOT_DIR),
                encoding='utf-8', errors='replace', env=env,
            )
            output = result.stdout[-2000:] + result.stderr[-500:]

            if result.returncode == 0:
                job.status = 'completed'
                job.progress = 100
                job.progress_message = '✅ Álbum subido a DistroKid'
                job.set_output({'stdout': output})
                _notify(db, job.user_id, job_id, True)
            else:
                job.status = 'failed'
                job.error_message = output[:2000]
                job.progress_message = '❌ Error en DistroKid Bot'
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
        title='✅ DistroKid Bot listo' if ok else '❌ Error en DistroKid Bot',
        message='Álbum subido a DistroKid correctamente.' if ok else 'Error al subir álbum.',
        type='success' if ok else 'error',
        link=f'/dashboard/jobs/{job_id}',
    ))
    db.session.commit()
