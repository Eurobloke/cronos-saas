# -*- coding: utf-8 -*-
"""
Runner de cadenas personalizadas.
El usuario arma una cadena de pasos; este servicio los ejecuta en orden
actualizando progreso en BD después de cada uno.
"""
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


# ─── Bloques disponibles que el usuario puede encadenar ─────────────────────
AVAILABLE_BLOCKS = [
    # Pasos individuales (horoscopo_bot)
    {
        'slug': 'gen_guion',
        'label': 'Generar Guión',
        'desc': 'Crea el guión y textos del video con IA (Ollama)',
        'icon': '📝', 'credits': 5, 'category': 'Contenido',
        'script': 'horoscopo_bot/1_generar_textos.py',
        'params': [{'name': 'fecha', 'label': 'Fecha', 'type': 'date', 'default': 'hoy'}],
    },
    {
        'slug': 'gen_imagen',
        'label': 'Generar Imágenes',
        'desc': 'Crea imágenes artísticas para cada tema',
        'icon': '🖼️', 'credits': 4, 'category': 'Contenido',
        'script': 'horoscopo_bot/2_generar_imagenes.py',
        'params': [],
    },
    {
        'slug': 'gen_narracion',
        'label': 'Narración con IA',
        'desc': 'Genera voz narrada con Edge-TTS',
        'icon': '🎙️', 'credits': 5, 'category': 'Audio',
        'script': 'horoscopo_bot/3_generar_audio.py',
        'params': [],
    },
    {
        'slug': 'gen_subtitulos',
        'label': 'Subtítulos',
        'desc': 'Genera subtítulos sincronizados ASS/SRT',
        'icon': '💬', 'credits': 2, 'category': 'Audio',
        'script': 'horoscopo_bot/4_generar_subtitulos.py',
        'params': [],
    },
    {
        'slug': 'edicion_auto',
        'label': 'Ensamblar Video',
        'desc': 'Combina imágenes + audio + subtítulos → video MP4',
        'icon': '✂️', 'credits': 8, 'category': 'Video',
        'script': 'horoscopo_bot/5_ensamblar_videos.py',
        'params': [],
    },
    {
        'slug': 'pub_youtube',
        'label': 'Publicar en YouTube',
        'desc': 'Sube el video terminado a tu canal de YouTube',
        'icon': '▶️', 'credits': 5, 'category': 'Publicación',
        'script': 'horoscopo_bot/7_subir_youtube.py',
        'params': [],
    },
    {
        'slug': 'pub_facebook',
        'label': 'Publicar en Facebook',
        'desc': 'Publica el video en tu página de Facebook',
        'icon': '📘', 'credits': 3, 'category': 'Publicación',
        'script': 'motivacion_bot/3_publicar_facebook.py',
        'params': [],
    },
    # Pipelines completos (un solo bloque que hace todo)
    {
        'slug': 'horoscopo_completo',
        'label': 'Horóscopo Completo',
        'desc': 'Guión → Imágenes → Voz → Subtítulos → Video (12 signos)',
        'icon': '♈', 'credits': 20, 'category': 'Pipeline completo',
        'pipeline': 'horoscopo',
        'params': [{'name': 'fecha', 'label': 'Fecha', 'type': 'date', 'default': 'hoy'}],
    },
    {
        'slug': 'motivacion_completo',
        'label': 'Motivación Completo',
        'desc': 'Pipeline completo: frases motivacionales + voz + video',
        'icon': '💪', 'credits': 15, 'category': 'Pipeline completo',
        'script': 'motivacion_bot/MENU.py',
        'params': [],
    },
    {
        'slug': 'noticias_rd_completo',
        'label': 'Noticias RD Completo',
        'desc': 'Noticias dominicanas: scraping + imágenes + video',
        'icon': '📰', 'credits': 10, 'category': 'Pipeline completo',
        'script': 'noticias_rd_bot/MENU.py',
        'params': [],
    },
]

# Índice rápido por slug
BLOCKS_BY_SLUG = {b['slug']: b for b in AVAILABLE_BLOCKS}


def get_blocks():
    """Retorna los bloques agrupados por categoría."""
    cats = {}
    for b in AVAILABLE_BLOCKS:
        cats.setdefault(b['category'], []).append(b)
    return cats


def calc_total_credits(steps: list) -> int:
    total = 0
    for step in steps:
        block = BLOCKS_BY_SLUG.get(step.get('slug', ''))
        if block:
            total += block['credits']
    return total


# ─── Runner ──────────────────────────────────────────────────────────────────

def run_chain_async(app, job_id: int):
    thread = threading.Thread(target=_execute_chain, args=(app, job_id), daemon=True)
    thread.start()


def _update(db, job, progress: int, message: str, step_results: list):
    job.progress = progress
    job.progress_message = message
    params = job.get_params()
    params['_step_results'] = step_results
    job.set_params(params)
    db.session.commit()


def _execute_chain(app, job_id: int):
    with app.app_context():
        from app.extensions import db
        from app.models.job import Job
        from flask import current_app

        job = db.session.get(Job, job_id)
        if not job:
            return

        params = job.get_params()
        steps = params.get('steps', [])
        total = len(steps)
        if total == 0:
            job.status = 'failed'
            job.error_message = 'La cadena está vacía.'
            db.session.commit()
            return

        job.status = 'running'
        job.started_at = datetime.now(timezone.utc)
        db.session.commit()

        bots_dir = Path(current_app.config['BOTS_DIR'])

        # Inicializar resultados por paso
        step_results = [
            {'slug': s.get('slug'), 'label': s.get('label', s.get('slug')),
             'icon': BLOCKS_BY_SLUG.get(s.get('slug'), {}).get('icon', '⚙️'),
             'status': 'pending', 'duration': None}
            for s in steps
        ]

        for i, step in enumerate(steps):
            slug = step.get('slug', '')
            block = BLOCKS_BY_SLUG.get(slug)
            if not block:
                step_results[i]['status'] = 'skipped'
                continue

            label = step.get('label', block['label'])
            step_results[i]['status'] = 'running'
            prog_base = int(i / total * 100)
            prog_next = int((i + 1) / total * 100)

            _update(db, job, prog_base + 2, f'Paso {i+1} de {total}: {label}...', step_results)

            t_start = time.time()

            if block.get('pipeline') == 'horoscopo':
                success, out = _run_horoscopo_pipeline(bots_dir, step.get('params', {}), db, job, step_results, i, prog_base, prog_next, total)
            else:
                success, out = _run_script(block, bots_dir, step.get('params', {}))

            duration = round(time.time() - t_start)
            step_results[i]['duration'] = duration

            if success:
                step_results[i]['status'] = 'completed'
                _update(db, job, prog_next, f'✅ Paso {i+1} completado: {label}', step_results)
            else:
                step_results[i]['status'] = 'failed'
                job.status = 'failed'
                job.error_message = f'Error en paso {i+1} ({label}):\n{out[:1000]}'
                job.completed_at = datetime.now(timezone.utc)
                _update(db, job, prog_base, f'❌ Error en: {label}', step_results)
                _notify(db, job.user_id, job_id, False, label)
                return

        job.status = 'completed'
        job.completed_at = datetime.now(timezone.utc)
        _update(db, job, 100, '¡Cadena completada exitosamente!', step_results)
        _notify(db, job.user_id, job_id, True, None)


def _run_script(block: dict, bots_dir: Path, params: dict) -> tuple:
    script_rel = block.get('script')
    if not script_rel:
        return False, f'Bloque {block["slug"]} no tiene script configurado.'

    script = bots_dir / script_rel
    if not script.exists():
        return False, f'Script no encontrado: {script}'

    cmd = [sys.executable, str(script)]
    fecha = params.get('fecha')
    if fecha and fecha != 'hoy':
        cmd.append(fecha)

    result = subprocess.run(
        cmd,
        capture_output=True, text=True,
        timeout=3600,
        cwd=str(script.parent),
        encoding='utf-8', errors='replace',
    )
    if result.returncode == 0:
        return True, result.stdout[-1000:]
    return False, result.stderr[-1000:] or result.stdout[-500:]


def _run_horoscopo_pipeline(bots_dir, params, db, job, step_results, step_idx, prog_base, prog_next, total_steps):
    """Corre el pipeline completo del horóscopo como un solo bloque de cadena."""
    from app.services.bots.horoscopo_runner import PIPELINE_STEPS

    scripts = PIPELINE_STEPS
    n = len(scripts)
    skip_yt = not params.get('subir_youtube', False)

    for j, (script_name, msg, _, _) in enumerate(scripts):
        if script_name == '7_subir_youtube.py' and skip_yt:
            continue

        sub_prog = prog_base + int((j / n) * (prog_next - prog_base))
        job.progress = sub_prog
        job.progress_message = f'Horóscopo — {msg}'
        db.session.commit()

        bot_dir = bots_dir / 'horoscopo_bot'
        script = bot_dir / script_name
        if not script.exists():
            return False, f'Script no encontrado: {script}'

        cmd = [sys.executable, str(script)]
        if script_name == '1_generar_textos.py':
            fecha = params.get('fecha', 'hoy')
            if fecha and fecha != 'hoy':
                cmd.append(fecha)

        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=3600,
            cwd=str(bot_dir),
            encoding='utf-8', errors='replace',
        )
        if result.returncode != 0:
            return False, result.stderr[-1000:] or result.stdout[-500:]

    return True, 'Pipeline horóscopo completado.'


def _notify(db, user_id, job_id, success, step_name):
    from app.models.notification import Notification
    if success:
        n = Notification(user_id=user_id, title='Cadena completada',
                         message='Tu cadena de bots terminó con éxito.',
                         type='success', link=f'/dashboard/jobs/{job_id}')
    else:
        n = Notification(user_id=user_id, title='Error en cadena',
                         message=f'La cadena falló en el paso: {step_name}.',
                         type='error', link=f'/dashboard/jobs/{job_id}')
    db.session.add(n)
    db.session.commit()
