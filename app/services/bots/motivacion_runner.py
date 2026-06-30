# -*- coding: utf-8 -*-
"""Runner del motivacion_bot — 4 pasos secuenciales.
Los pasos de publicacion (FB/YT) son opcionales: si fallan se registra el error
pero el pipeline continua y el job queda como completado.
"""
import threading
from datetime import datetime, timezone
from pathlib import Path

# Pasos criticos: si fallan, abortan. Pasos blandos: si fallan, continuan.
PIPELINE_STEPS = [
    # (script, mensaje, p_inicio, p_fin, es_critico)
    ('1_generar_frases.py',    'Generando frases motivacionales con IA...',  5,  28, True),
    ('2_crear_videos.py',      'Creando videos con frases y efectos...',      28, 72, True),
    ('3_publicar_facebook.py', 'Publicando en Facebook...',                   72, 87, False),
    ('4_subir_youtube.py',     'Subiendo a YouTube...',                       87, 100, False),
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
        user_workspace = params.get('user_workspace', '')
        output_log = []
        warnings = []

        skip_fb = not (params.get('publicar_facebook') or params.get('fb_reels') or params.get('fb_fotos'))
        skip_yt = not (params.get('subir_youtube') or params.get('yt_shorts'))

        # Env vars para que los scripts usen el workspace del usuario
        extra_env = {}
        if user_workspace:
            extra_env['CRONOS_USER_WORKSPACE'] = user_workspace
            extra_env['CRONOS_USER_ID'] = str(params.get('user_id', ''))
        if params.get('fb_url'):
            extra_env['CRONOS_FB_URL'] = params['fb_url']
        # Opciones de publicación
        extra_env['CRONOS_FB_REELS']  = '1' if params.get('fb_reels') else '0'
        extra_env['CRONOS_FB_FOTOS']  = '1' if params.get('fb_fotos') else '0'
        extra_env['CRONOS_YT_SHORTS'] = '1' if params.get('yt_shorts') else '0'

        for script, msg, p_start, p_end, es_critico in PIPELINE_STEPS:
            # Verificar cancelación entre pasos
            db.session.refresh(job)
            if job.status == 'cancelled':
                return

            if script == '3_publicar_facebook.py' and skip_fb:
                output_log.append('[SKIP] 3_publicar_facebook.py')
                continue
            if script == '4_subir_youtube.py' and skip_yt:
                output_log.append('[SKIP] 4_subir_youtube.py')
                continue

            _set_progress(db, job, p_start, msg)

            def update_fn(m, _j=job, _db=db, _p=p_start):
                _set_progress(_db, _j, _p, f'🔧 {m}')

            success, output = ejecutar_con_autofix(
                script, bot_dir, timeout=3600,
                update_fn=update_fn, extra_env=extra_env,
            )
            output_log.append(f'[{script}]\n{output[:500]}')

            if not success:
                if es_critico:
                    # Paso critico fallo — abortar
                    job.status = 'failed'
                    job.error_message = f'Error en {script}:\n{output[:1500]}'
                    job.completed_at = datetime.now(timezone.utc)
                    _set_progress(db, job, p_start, f'❌ Error en: {script}')
                    _notify(db, job.user_id, job_id, False)
                    return
                else:
                    # Paso de publicacion fallo — advertencia y continuar
                    warn = f'⚠️ {script} falló (publicación omitida): {output[:300]}'
                    warnings.append(warn)
                    _set_progress(db, job, p_end, f'⚠️ {script} falló — continuando...')
                    continue

            _set_progress(db, job, p_end, f'✅ Completado: {script}')

        job.status = 'completed'
        job.completed_at = datetime.now(timezone.utc)
        job.set_output({'steps': output_log, 'warnings': warnings, 'params': params})

        msg_final = '✅ ¡Videos motivacionales listos!'
        if warnings:
            msg_final += f' ⚠️ {len(warnings)} publicación(es) con error.'
        _set_progress(db, job, 100, msg_final)
        _notify(db, job.user_id, job_id, True, warnings)


def _notify(db, user_id, job_id, ok, warnings=None):
    from app.models.notification import Notification
    if ok:
        if warnings:
            title = '✅ Motivación Bot — contenido listo (publicación con errores)'
            msg = f'Videos generados. {len(warnings)} paso(s) de publicación fallaron.'
            ntype = 'warning'
        else:
            title = '✅ Motivación Bot listo'
            msg = 'Videos generados y publicados correctamente.'
            ntype = 'success'
    else:
        title = '❌ Error en Motivación Bot'
        msg = 'Error en la generación de contenido. Revisa los detalles.'
        ntype = 'error'

    notif = Notification(
        user_id=user_id, title=title, message=msg,
        type=ntype, link=f'/dashboard/jobs/{job_id}',
    )
    db.session.add(notif)
    db.session.commit()
