# -*- coding: utf-8 -*-
"""
Agente 2 — Runner del horoscopo_bot.
Ejecuta el pipeline completo paso a paso con actualizaciones de progreso en BD.
"""
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


# Pasos del pipeline: (script, mensaje_legible, progreso_inicio, progreso_fin)
PIPELINE_STEPS = [
    ('1_generar_textos.py',    'Investigando horóscopo y generando guiones...',  5,  28),
    ('2_generar_imagenes.py',  'Creando imágenes para cada signo zodiacal...',   28, 52),
    ('3_generar_audio.py',     'Generando narración con voz IA...',              52, 68),
    ('4_generar_subtitulos.py','Generando subtítulos...',                        68, 78),
    ('5_ensamblar_videos.py',  'Ensamblando los videos finales...',              78, 93),
    ('7_subir_youtube.py',     'Subiendo a YouTube...',                          93, 100),
]


def run_pipeline_async(app, job_id: int, params: dict):
    """Lanza el pipeline en un hilo de fondo."""
    thread = threading.Thread(
        target=_execute_pipeline,
        args=(app, job_id, params),
        daemon=True,
    )
    thread.start()


def _set_progress(db, job, pct: int, msg: str):
    """Actualiza progreso y mensaje en BD."""
    job.progress = pct
    job.progress_message = msg
    db.session.commit()


def _run_step(script_name: str, bot_dir: Path, params: dict, update_fn=None) -> tuple[bool, str]:
    """
    Ejecuta un paso del pipeline con auto-corrección en tiempo real.
    Retorna (exito, salida/error).
    """
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
    )


def _execute_pipeline(app, job_id: int, params: dict):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from app.models.notification import Notification
        from flask import current_app

        job = db.session.get(Job, job_id)
        if not job:
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        _set_progress(db, job, 3, 'Iniciando pipeline de horóscopo...')

        bots_dir = Path(current_app.config['BOTS_DIR'])
        bot_dir = bots_dir / 'horoscopo_bot'

        output_log = []
        skip_upload = not params.get('subir_youtube', False)

        for script_name, msg, prog_start, prog_end in PIPELINE_STEPS:
            # Si el usuario no quiere subir, saltar el paso de YouTube
            if script_name == '7_subir_youtube.py' and skip_upload:
                _set_progress(db, job, 95, 'Subida a YouTube omitida (no configurada).')
                output_log.append('[SKIP] 7_subir_youtube.py')
                continue

            _set_progress(db, job, prog_start, msg)

            # update_fn reporta mensajes de auto-fix en tiempo real al usuario
            def update_fn(mensaje, _job=job, _db=db, _pct=prog_start):
                _set_progress(_db, _job, _pct, f'🔧 {mensaje}')

            success, output = _run_step(script_name, bot_dir, params, update_fn=update_fn)
            output_log.append(f'[{script_name}]\n{output[:500]}')

            if not success:
                job.status = 'failed'
                job.error_message = f'Error en {script_name}:\n{output[:1500]}'
                job.completed_at = datetime.now(timezone.utc)
                _set_progress(db, job, prog_start, f'❌ No se pudo corregir el error en: {script_name}')
                _notify(db, job.user_id, job_id, 'error', script_name)
                return

            _set_progress(db, job, prog_end, f'✅ Completado: {script_name}')

        # Todo OK
        job.status = 'completed'
        job.completed_at = datetime.now(timezone.utc)
        job.set_output({'steps': output_log, 'params': params})
        _set_progress(db, job, 100, '¡Horóscopo completado exitosamente!')
        _notify(db, job.user_id, job_id, 'success', None)


def _notify(db, user_id: int, job_id: int, status: str, failed_step: str):
    from app.models.notification import Notification
    if status == 'success':
        notif = Notification(
            user_id=user_id,
            title='Horóscopo listo',
            message='Tu horóscopo se generó y publicó correctamente en YouTube.',
            type='success',
            link=f'/dashboard/jobs/{job_id}',
        )
    else:
        notif = Notification(
            user_id=user_id,
            title='Error en horóscopo',
            message=f'Hubo un error en el paso {failed_step}. Revisa los detalles.',
            type='error',
            link=f'/dashboard/jobs/{job_id}',
        )
    db.session.add(notif)
    db.session.commit()
