# -*- coding: utf-8 -*-
"""
API routes para el sistema de dos agentes:
- POST /api/chat            — manda mensaje al orquestador IA
- GET  /api/jobs/<id>/stream — SSE de progreso en tiempo real
- GET/POST /api/niche-profile — lee/guarda el perfil de nicho del usuario
"""
import json
import time
from datetime import datetime, timezone

from flask import Response, jsonify, request, stream_with_context
from flask_login import current_user, login_required

from app.api import api_bp
from app.extensions import db
from app.models.job import Job
from app.models.niche_profile import Conversation, NicheProfile
from app.models.service import Service
from app.services import credit_service
from app.services import orchestrator
from app.services.bots.horoscopo_runner import run_pipeline_async
from app.services.chain_runner import AVAILABLE_BLOCKS, calc_total_credits, run_chain_async


# ─── Mapa: nombre de bot → slug del servicio en BD ──────────────────────────
BOT_SERVICE_MAP = {
    'HOROSCOPO': 'horoscopo_completo',
    'MOTIVACION': 'motivacion_completo',
    'NOTICIAS_RD': 'noticias_rd_completo',
}


def _get_or_create_niche(user_id: int) -> NicheProfile:
    profile = NicheProfile.query.filter_by(user_id=user_id).first()
    if not profile:
        profile = NicheProfile(user_id=user_id)
        db.session.add(profile)
        db.session.commit()
    return profile


# ─── Chat con el orquestador ─────────────────────────────────────────────────

@api_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    user_message = (data.get('message') or '').strip()
    if not user_message:
        return jsonify({'error': 'Mensaje vacío'}), 400

    profile = _get_or_create_niche(current_user.id)
    niche_ctx = profile.to_context_string()

    # Cargar historial reciente (últimos 10 intercambios)
    recent = (Conversation.query
              .filter_by(user_id=current_user.id)
              .order_by(Conversation.created_at.desc())
              .limit(20).all())
    recent.reverse()
    history = [{'role': c.role, 'content': c.content} for c in recent]

    # Guardar mensaje del usuario
    user_conv = Conversation(user_id=current_user.id, role='user', content=user_message)
    db.session.add(user_conv)
    db.session.commit()

    # Llamar al orquestador
    result = orchestrator.process_message(user_message, history, niche_ctx)

    # ── Si el orquestador quiere ejecutar un bot ────────────────────────────
    if result.get('type') == 'action':
        bot_name = result.get('bot', '').upper()
        params = result.get('params', {})
        ai_message = result.get('message', f'Ejecutando {bot_name}...')

        job_id, error = _launch_bot(bot_name, params)
        if error:
            reply = f"No pude iniciar el bot: {error}"
            ai_conv = Conversation(user_id=current_user.id, role='assistant', content=reply)
            db.session.add(ai_conv)
            db.session.commit()
            return jsonify({'type': 'message', 'content': reply})

        # Guardar respuesta de la IA con referencia al job
        ai_conv = Conversation(user_id=current_user.id, role='assistant',
                               content=ai_message, job_id=job_id)
        db.session.add(ai_conv)
        db.session.commit()
        return jsonify({'type': 'action', 'content': ai_message, 'job_id': job_id})

    # ── Respuesta de texto normal ────────────────────────────────────────────
    reply = result.get('content', 'No entendí la solicitud.')
    ai_conv = Conversation(user_id=current_user.id, role='assistant', content=reply)
    db.session.add(ai_conv)
    db.session.commit()
    return jsonify({'type': 'message', 'content': reply})


def _launch_bot(bot_name: str, params: dict) -> tuple:
    """Crea el job y lanza el runner correspondiente. Retorna (job_id, error_str)."""
    from flask import current_app

    # Buscar o crear el servicio en BD
    service = Service.query.filter_by(slug=BOT_SERVICE_MAP.get(bot_name, '')).first()

    # Si el servicio no existe aún, crear uno temporal para tracking
    if not service:
        service = Service.query.filter_by(slug='video_completo').first()
    if not service:
        return None, f'Servicio {bot_name} no configurado aún.'

    cost = service.credit_cost
    if current_user.credits < cost:
        return None, f'Créditos insuficientes. Necesitas {cost}, tienes {current_user.credits}.'

    job = Job(user_id=current_user.id, service_id=service.id, credits_used=cost)
    job.set_params(params)
    db.session.add(job)
    db.session.flush()

    ok = credit_service.consume_credits(
        current_user, cost,
        f'Bot {bot_name}', reference=f'job:{job.id}'
    )
    if not ok:
        db.session.rollback()
        return None, 'Error al descontar créditos.'

    db.session.commit()

    # Lanzar el runner del bot correcto
    if bot_name == 'HOROSCOPO':
        run_pipeline_async(current_app._get_current_object(), job.id, params)
    else:
        from app.services.bot_runner import run_job_async
        run_job_async(current_app._get_current_object(), job.id)

    return job.id, None


# ─── SSE: stream de progreso en tiempo real ──────────────────────────────────

@api_bp.route('/jobs/<int:job_id>/stream')
@login_required
def job_stream(job_id):
    """Server-Sent Events: envía progreso cada 1.5 s hasta que el job termine."""

    def generate():
        last_progress = -1
        retries = 0
        while True:
            try:
                db.session.expire_all()
                job = db.session.get(Job, job_id)
                retries = 0
            except Exception:
                db.session.rollback()
                retries += 1
                if retries > 5:
                    yield _sse({'error': 'Error de base de datos'})
                    return
                time.sleep(2)
                continue

            if not job or job.user_id != current_user.id:
                yield _sse({'error': 'Job no encontrado'})
                return

            pct = job.progress
            msg = job.progress_message or ''
            status = job.status

            if pct != last_progress or status in ('completed', 'failed'):
                last_progress = pct
                payload = {
                    'progress': pct,
                    'message': msg,
                    'status': status,
                }
                # Para cadenas: incluir estado de cada paso
                params = job.get_params()
                if params.get('_type') == 'chain':
                    payload['step_results'] = params.get('_step_results', [])
                if status == 'completed':
                    payload['output'] = job.get_output()
                if status == 'failed':
                    payload['error'] = job.error_message or 'Error desconocido'
                yield _sse(payload)

            if status in ('completed', 'failed', 'cancelled'):
                return

            time.sleep(1.5)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


def _sse(data: dict) -> str:
    return f'data: {json.dumps(data, ensure_ascii=False)}\n\n'


# ─── Perfil de nicho ──────────────────────────────────────────────────────────

@api_bp.route('/niche-profile', methods=['GET'])
@login_required
def get_niche_profile():
    profile = _get_or_create_niche(current_user.id)
    return jsonify({
        'channel_name': profile.channel_name,
        'channel_url': profile.channel_url,
        'niche': profile.niche,
        'audience': profile.audience,
        'style': profile.style,
        'language': profile.language,
        'country': profile.country,
        'description': profile.description,
        'has_youtube': profile.has_youtube(),
        'youtube_channel_name': profile.youtube_channel_name,
    })


@api_bp.route('/niche-profile', methods=['POST'])
@login_required
def save_niche_profile():
    data = request.get_json(silent=True) or {}
    profile = _get_or_create_niche(current_user.id)

    fields = ['channel_name', 'channel_url', 'niche', 'audience', 'style',
              'language', 'country', 'description']
    for f in fields:
        if f in data:
            setattr(profile, f, data[f])

    profile.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'ok': True, 'message': 'Perfil guardado correctamente.'})


@api_bp.route('/chat/history', methods=['GET'])
@login_required
def chat_history():
    convs = (Conversation.query
             .filter_by(user_id=current_user.id)
             .order_by(Conversation.created_at.asc())
             .limit(100).all())
    return jsonify([{
        'role': c.role,
        'content': c.content,
        'job_id': c.job_id,
        'created_at': c.created_at.isoformat() if c.created_at else None,
    } for c in convs])


@api_bp.route('/chat/clear', methods=['POST'])
@login_required
def clear_history():
    Conversation.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({'ok': True})


# ─── Cadenas personalizadas ───────────────────────────────────────────────────

@api_bp.route('/chain/run', methods=['POST'])
@login_required
def run_chain():
    """Valida y lanza una cadena de pasos elegida por el usuario."""
    from flask import current_app
    data = request.get_json(silent=True) or {}
    steps = data.get('steps', [])

    if not steps:
        return jsonify({'error': 'La cadena está vacía.'}), 400
    if len(steps) > 15:
        return jsonify({'error': 'Máximo 15 pasos por cadena.'}), 400

    total_credits = calc_total_credits(steps)
    if current_user.credits < total_credits:
        return jsonify({'error': f'Créditos insuficientes. Necesitas {total_credits}, tienes {current_user.credits}.'}), 400

    # Usar servicio genérico "video_completo" para el tracking del job
    service = Service.query.filter_by(slug='video_completo').first()
    if not service:
        return jsonify({'error': 'Configuración incorrecta en la plataforma.'}), 500

    job = Job(user_id=current_user.id, service_id=service.id, credits_used=total_credits)
    chain_params = {
        '_type': 'chain',
        'name': data.get('name', 'Cadena personalizada'),
        'steps': steps,
        '_step_results': [],
    }
    job.set_params(chain_params)
    db.session.add(job)
    db.session.flush()

    ok = credit_service.consume_credits(
        current_user, total_credits,
        f'Cadena: {len(steps)} pasos', reference=f'job:{job.id}'
    )
    if not ok:
        db.session.rollback()
        return jsonify({'error': 'Error al descontar créditos.'}), 500

    db.session.commit()
    run_chain_async(current_app._get_current_object(), job.id)

    return jsonify({'ok': True, 'job_id': job.id, 'credits_used': total_credits})


@api_bp.route('/chain/blocks')
@login_required
def get_chain_blocks():
    """Lista de bloques disponibles con su costo."""
    return jsonify(AVAILABLE_BLOCKS)
