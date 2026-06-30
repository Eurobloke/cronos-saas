# -*- coding: utf-8 -*-
"""Runner del horoscopo_bot — pipeline completo con pasos criticos y blandos."""
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


# (script, mensaje, p_inicio, p_fin, es_critico)
PIPELINE_STEPS = [
    ('1_generar_textos.py',    'Investigando horóscopo y generando guiones...',  5,  28, True),
    ('2_generar_imagenes.py',  'Creando imágenes para cada signo zodiacal...',   28, 52, True),
    ('3_generar_audio.py',     'Generando narración con voz IA...',              52, 68, True),
    ('4_generar_subtitulos.py','Generando subtítulos...',                        68, 78, True),
    ('5_ensamblar_videos.py',  'Ensamblando los videos finales...',              78, 90, True),
    ('6_generar_shorts.py',    'Generando shorts de tarot...',                   90, 95, False),
    ('7_subir_youtube.py',     'Subiendo a YouTube (videos + shorts)...',        95, 100, False),
]


def run_pipeline_async(app, job_id: int, params: dict):
    thread = threading.Thread(target=_execute_pipeline, args=(app, job_id, params), daemon=True)
    thread.start()


def _set_progress(db, job, pct: int, msg: str):
    job.progress = pct
    job.progress_message = msg
    db.session.commit()


def _run_step(script_name: str, bot_dir: Path, params: dict,
              update_fn=None, extra_env: dict = None) -> tuple:
    from app.services.auto_fix import ejecutar_con_autofix
    cmd_extra = []
    if script_name == '1_generar_textos.py':
        fecha = params.get('fecha', 'hoy')
        if fecha and fecha != 'hoy':
            cmd_extra.append(fecha)
    return ejecutar_con_autofix(
        script_name=script_name,
        bot_dir=bot_dir,
        cmd_extra=cmd_extra,
        timeout=3600,
        update_fn=update_fn,
        extra_env=extra_env or {},
    )


def _execute_pipeline(app, job_id: int, params: dict):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from flask import current_app

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        _set_progress(db, job, 3, 'Iniciando pipeline de horóscopo...')

        bots_dir = Path(current_app.config['BOTS_DIR'])
        bot_dir = bots_dir / 'horoscopo_bot'
        user_workspace = params.get('user_workspace', '')
        output_log = []
        warnings = []

        skip_yt  = not params.get('subir_youtube', False)
        skip_fb  = not (params.get('publicar_facebook') or params.get('fb_reels') or params.get('fb_fotos'))

        # Variables de entorno para que scripts usen workspace del usuario
        extra_env = {}
        if user_workspace:
            extra_env['CRONOS_USER_WORKSPACE'] = user_workspace
            extra_env['CRONOS_USER_ID'] = str(params.get('user_id', ''))
        if params.get('fb_url'):
            extra_env['CRONOS_FB_URL'] = params['fb_url']
        extra_env['CRONOS_FB_REELS']  = '1' if params.get('fb_reels')  else '0'
        extra_env['CRONOS_FB_FOTOS']  = '1' if params.get('fb_fotos')  else '0'
        extra_env['CRONOS_YT_SHORTS'] = '1' if params.get('yt_shorts') else '0'

        for script_name, msg, prog_start, prog_end, es_critico in PIPELINE_STEPS:
            # Verificar si el usuario canceló el trabajo
            db.session.refresh(job)
            if job.status == 'cancelled':
                return

            if script_name == '7_subir_youtube.py' and skip_yt:
                output_log.append('[SKIP] 7_subir_youtube.py')
                continue
            if script_name == '6_generar_shorts.py' and not params.get('yt_shorts'):
                output_log.append('[SKIP] 6_generar_shorts.py')
                continue

            # Si el script no existe en el bot, saltarlo sin error
            if not (bot_dir / script_name).exists():
                output_log.append(f'[SKIP] {script_name} — no encontrado')
                continue

            _set_progress(db, job, prog_start, msg)

            def update_fn(mensaje, _job=job, _db=db, _pct=prog_start):
                _set_progress(_db, _job, _pct, f'🔧 {mensaje}')

            success, output = _run_step(script_name, bot_dir, params,
                                        update_fn=update_fn, extra_env=extra_env)
            output_log.append(f'[{script_name}]\n{output[:500]}')

            if not success:
                if es_critico:
                    job.status = 'failed'
                    job.error_message = f'Error en {script_name}:\n{output[:1500]}'
                    job.completed_at = datetime.now(timezone.utc)
                    _set_progress(db, job, prog_start, f'❌ Error en: {script_name}')
                    _notify(db, job.user_id, job_id, False, script_name, [])
                    return
                else:
                    warnings.append(f'⚠️ {script_name}: {output[:300]}')
                    _set_progress(db, job, prog_end, f'⚠️ {script_name} falló — continuando...')
                    continue

            _set_progress(db, job, prog_end, f'✅ {script_name}')

        job.status = 'completed'
        job.completed_at = datetime.now(timezone.utc)
        job.set_output({'steps': output_log, 'warnings': warnings, 'params': params})
        msg_final = '¡Horóscopo completado!'
        if warnings:
            msg_final += f' ⚠️ {len(warnings)} publicación(es) con error.'
        _set_progress(db, job, 100, msg_final)
        _notify(db, job.user_id, job_id, True, None, warnings)


def _notify(db, user_id: int, job_id: int, ok: bool, failed_step: str, warnings: list):
    from app.models.notification import Notification
    if ok:
        if warnings:
            title = '✅ Horóscopo listo (publicación con errores)'
            msg = f'Videos generados. {len(warnings)} publicación(es) fallaron.'
            ntype = 'warning'
        else:
            title = '✅ Horóscopo listo'
            msg = 'Horóscopo generado y publicado en YouTube correctamente.'
            ntype = 'success'
    else:
        title = '❌ Error en horóscopo'
        msg = f'Error en el paso: {failed_step}. Revisa los detalles.'
        ntype = 'error'
    notif = Notification(
        user_id=user_id, title=title, message=msg,
        type=ntype, link=f'/dashboard/jobs/{job_id}',
    )
    db.session.add(notif)
    db.session.commit()
