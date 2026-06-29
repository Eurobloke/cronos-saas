# -*- coding: utf-8 -*-
"""Runner del motivacion_bot — 4 pasos secuenciales con auto-fix."""
import threading
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_STEPS = [
    ('1_generar_frases.py',   'Generando frases motivacionales con IA...',   5,  28),
    ('2_crear_videos.py',     'Creando videos con frases y efectos...',       28, 72),
    ('3_publicar_facebook.py','Publicando en Facebook...',                    72, 87),
    ('4_subir_youtube.py',    'Subiendo a YouTube...',                        87, 100),
]


def run_pipeline_async(app, job_id: int, params: dict):
    thread = threading.Thread(target=_execute, args=(app, job_id, params), daemon=True)
    thread.start()


def _set_progress(db, job, pct, msg):
    job.progress = pct
    job.progress_message = msg
    db.session.commit()


def _execute(app, job_id: int, params: dict):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from app.models.notification import Notification
        from app.services.auto_fix import ejecutar_con_autofix
        from flask import current_app

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        _set_progress(db, job, 3, 'Iniciando Motivación Bot...')

        bot_dir = Path(current_app.config['BOTS_DIR']) / 'motivacion_bot'
        output_log = []

        skip_fb = not params.get('publicar_facebook', True)
        skip_yt = not params.get('subir_youtube', True)

        for script, msg, p_start, p_end in PIPELINE_STEPS:
            if script == '3_publicar_facebook.py' and skip_fb:
                output_log.append('[SKIP] 3_publicar_facebook.py')
                continue
            if script == '4_subir_youtube.py' and skip_yt:
                output_log.append('[SKIP] 4_subir_youtube.py')
                continue

            _set_progress(db, job, p_start, msg)

            def update_fn(m, _j=job, _db=db, _p=p_start):
                _set_progress(_db, _j, _p, f'🔧 {m}')

            success, output = ejecutar_con_autofix(script, bot_dir, timeout=3600, update_fn=update_fn)
            output_log.append(f'[{script}]\n{output[:500]}')

            if not success:
                job.status = 'failed'
                job.error_message = f'Error en {script}:\n{output[:1500]}'
                job.completed_at = datetime.now(timezone.utc)
                _set_progress(db, job, p_start, f'❌ Error en: {script}')
                _notify(db, job.user_id, job_id, False)
                return

            _set_progress(db, job, p_end, f'✅ Completado: {script}')

        job.status = 'completed'
        job.completed_at = datetime.now(timezone.utc)
        job.set_output({'steps': output_log, 'params': params})
        _set_progress(db, job, 100, '¡Videos motivacionales listos!')
        _notify(db, job.user_id, job_id, True)


def _notify(db, user_id, job_id, ok):
    from app.models.notification import Notification
    notif = Notification(
        user_id=user_id,
        title='✅ Motivación Bot listo' if ok else '❌ Error en Motivación Bot',
        message='Videos generados y publicados correctamente.' if ok else 'Revisa los detalles del error.',
        type='success' if ok else 'error',
        link=f'/dashboard/jobs/{job_id}',
    )
    db.session.add(notif)
    db.session.commit()
