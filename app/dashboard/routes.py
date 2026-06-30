# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, abort, jsonify
from flask_login import login_required, current_user
import io, json, subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from app.extensions import db, limiter
from app.models import Service, Job, CreditTransaction, Payment, Notification
from app.models.niche_profile import NicheProfile, Conversation
from app.services import credit_service
from app.services.bot_runner import run_job_async
from app.services.invoice_service import generate_invoice_pdf
from app.auth.forms import ChangePasswordForm
from app.services import email_service

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

HOROSCOPO_DIR = Path(r'C:\Users\franc\music\horoscopo_bot')
CHROME_EXE    = r'C:\Program Files\Google\Chrome\Application\chrome.exe'


STORAGE_BY_PLAN = {
    'free':    500,
    'starter': 2048,
    'creator': 10240,
    'agency':  51200,
    'admin':   999999,
}


def _calc_storage(user_id: int) -> tuple:
    """Calcula el almacenamiento del usuario desde su workspace aislado."""
    from app.services import workspace_service as ws_svc
    from flask_login import current_user as cu
    used_mb = ws_svc.storage_used_mb(user_id)
    plan_slug = 'free'
    if cu.is_authenticated:
        if cu.is_admin():
            plan_slug = 'admin'
        elif cu.plan:
            plan_slug = getattr(cu.plan, 'slug', 'free')
    limit_mb = STORAGE_BY_PLAN.get(plan_slug, 500)
    pct = min(int((used_mb / limit_mb) * 100), 100)
    return used_mb, limit_mb, pct


@dashboard_bp.route('/')
@login_required
def index():
    recent_jobs = current_user.jobs.order_by(Job.created_at.desc()).limit(5).all()
    recent_tx = current_user.credit_transactions.order_by(
        CreditTransaction.created_at.desc()).limit(5).all()
    unread_count = current_user.notifications.filter_by(is_read=False).count()
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order).all()
    storage_used_mb, storage_limit_mb, storage_pct = _calc_storage(current_user.id)
    return render_template('dashboard/index.html',
                           recent_jobs=recent_jobs,
                           recent_tx=recent_tx,
                           unread_count=unread_count,
                           services=services,
                           storage_used_mb=storage_used_mb,
                           storage_limit_mb=storage_limit_mb,
                           storage_pct=storage_pct)


@dashboard_bp.route('/services')
@login_required
def services():
    all_services = Service.query.filter_by(is_active=True).order_by(Service.sort_order).all()
    return render_template('dashboard/services.html', services=all_services)


@dashboard_bp.route('/services/<int:service_id>/run', methods=['POST'])
@login_required
@limiter.limit('30 per hour')
def run_service(service_id):
    service = Service.query.get_or_404(service_id)
    if not service.is_active:
        flash('Este servicio no está disponible.', 'warning')
        return redirect(url_for('dashboard.services'))

    if not current_user.is_admin() and current_user.credits < service.credit_cost:
        flash(f'No tienes suficientes créditos. Necesitas {service.credit_cost}, tienes {current_user.credits}.', 'danger')
        return redirect(url_for('payments.plans'))

    # Crear job
    job = Job(user_id=current_user.id, service_id=service.id, credits_used=service.credit_cost)
    params = {k: v for k, v in request.form.items() if k != 'csrf_token'}
    job.set_params(params)
    db.session.add(job)
    db.session.flush()

    # Descontar créditos
    ok = credit_service.consume_credits(
        current_user, service.credit_cost,
        f'Servicio: {service.name}', reference=f'job:{job.id}'
    )
    if not ok:
        db.session.rollback()
        flash('Error al descontar créditos.', 'danger')
        return redirect(url_for('dashboard.services'))

    db.session.commit()

    from flask import current_app
    run_job_async(current_app._get_current_object(), job.id)
    flash(f'✅ Trabajo iniciado. Créditos usados: {service.credit_cost}. Recibirás una notificación al terminar.', 'success')
    return redirect(url_for('dashboard.jobs'))


@dashboard_bp.route('/jobs')
@login_required
def jobs():
    page = request.args.get('page', 1, type=int)
    if current_user.is_admin():
        # Admin ve todos los trabajos de todos los usuarios
        q = Job.query.order_by(Job.created_at.desc())
        user_filter = request.args.get('user_id', type=int)
        if user_filter:
            q = q.filter_by(user_id=user_filter)
    else:
        q = current_user.jobs.order_by(Job.created_at.desc())
    jobs_pag = q.paginate(page=page, per_page=20)
    return render_template('dashboard/jobs.html', jobs=jobs_pag)


@dashboard_bp.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin():
        abort(403)
    return render_template('dashboard/job_detail.html', job=job)


@dashboard_bp.route('/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
def job_cancel(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin():
        abort(403)
    if job.status in ('queued', 'running'):
        job.status = 'cancelled'
        job.progress_message = 'Cancelado por el usuario'
        job.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash('Trabajo cancelado.', 'success')
    else:
        flash('Este trabajo ya no se puede cancelar.', 'warning')
    return redirect(url_for('dashboard.jobs'))


@dashboard_bp.route('/credits')
@login_required
def credits():
    page = request.args.get('page', 1, type=int)
    transactions = current_user.credit_transactions.order_by(
        CreditTransaction.created_at.desc()).paginate(page=page, per_page=30)
    return render_template('dashboard/credits.html', transactions=transactions)


@dashboard_bp.route('/billing')
@login_required
def billing():
    page = request.args.get('page', 1, type=int)
    payments_pag = current_user.payments.order_by(
        Payment.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('dashboard/billing.html', payments=payments_pag)


@dashboard_bp.route('/billing/<int:payment_id>/invoice')
@login_required
def download_invoice(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.user_id != current_user.id:
        abort(403)
    pdf_bytes = generate_invoice_pdf(payment, current_user)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'factura-{payment.invoice_number or payment_id}.pdf',
    )


@dashboard_bp.route('/notifications')
@login_required
def notifications():
    notifs = current_user.notifications.order_by(Notification.created_at.desc()).limit(50).all()
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return render_template('dashboard/notifications.html', notifications=notifs)


@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('La contraseña actual es incorrecta.', 'danger')
        else:
            current_user.set_password(form.new_password.data)
            db.session.commit()
            email_service.send_password_changed(current_user)
            flash('Contraseña actualizada correctamente.', 'success')
    return render_template('dashboard/settings.html', form=form)


@dashboard_bp.route('/cadena')
@login_required
def cadena():
    from app.services.chain_runner import get_blocks
    blocks_by_cat = get_blocks()
    return render_template('dashboard/cadena.html', blocks_by_cat=blocks_by_cat)


@dashboard_bp.route('/asistente')
@login_required
def chat():
    profile = NicheProfile.query.filter_by(user_id=current_user.id).first()
    history = (Conversation.query
               .filter_by(user_id=current_user.id)
               .order_by(Conversation.created_at.asc())
               .limit(100).all())
    return render_template('dashboard/chat.html', profile=profile, history=history)


@dashboard_bp.route('/youtube/connect')
@login_required
def youtube_connect():
    from flask import current_app
    client_id = current_app.config.get('YOUTUBE_CLIENT_ID', '')
    redirect_uri = current_app.config.get('YOUTUBE_REDIRECT_URI', '')
    if not client_id:
        flash('YouTube no está configurado. Agrega YOUTUBE_CLIENT_ID en el archivo .env.', 'warning')
        return redirect(url_for('dashboard.niche_setup'))
    scopes = 'https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly'
    auth_url = (
        'https://accounts.google.com/o/oauth2/v2/auth'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        f'&response_type=code'
        f'&scope={scopes}'
        '&access_type=offline&prompt=consent'
    )
    from flask import redirect as flask_redirect
    return flask_redirect(auth_url)


@dashboard_bp.route('/youtube/callback')
@login_required
def youtube_callback():
    from flask import current_app, request as req
    code = req.args.get('code')
    if not code:
        flash('Error al conectar YouTube. Intenta de nuevo.', 'danger')
        return redirect(url_for('dashboard.niche_setup'))

    client_id = current_app.config.get('YOUTUBE_CLIENT_ID', '')
    client_secret = current_app.config.get('YOUTUBE_CLIENT_SECRET', '')
    redirect_uri = current_app.config.get('YOUTUBE_REDIRECT_URI', '')

    import requests as req_lib
    token_resp = req_lib.post('https://oauth2.googleapis.com/token', data={
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }, timeout=30)

    if token_resp.status_code != 200:
        flash('Error al obtener tokens de YouTube.', 'danger')
        return redirect(url_for('dashboard.niche_setup'))

    tokens = token_resp.json()
    profile = NicheProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = NicheProfile(user_id=current_user.id)
        db.session.add(profile)

    profile.youtube_access_token = tokens.get('access_token')
    profile.youtube_refresh_token = tokens.get('refresh_token')

    # Obtener info del canal
    ch_resp = req_lib.get(
        'https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true',
        headers={'Authorization': f'Bearer {tokens["access_token"]}'},
        timeout=15,
    )
    if ch_resp.status_code == 200:
        items = ch_resp.json().get('items', [])
        if items:
            profile.youtube_channel_id = items[0]['id']
            profile.youtube_channel_name = items[0]['snippet']['title']

    db.session.commit()
    flash(f'Canal de YouTube "{profile.youtube_channel_name}" conectado correctamente.', 'success')
    return redirect(url_for('dashboard.niche_setup'))


@dashboard_bp.route('/youtube/disconnect', methods=['POST'])
@login_required
def youtube_disconnect():
    profile = NicheProfile.query.filter_by(user_id=current_user.id).first()
    if profile:
        profile.youtube_access_token = None
        profile.youtube_refresh_token = None
        profile.youtube_channel_id = None
        profile.youtube_channel_name = None
        db.session.commit()
    flash('Canal de YouTube desconectado.', 'info')
    return redirect(url_for('dashboard.niche_setup'))


@dashboard_bp.route('/mi-canal', methods=['GET', 'POST'])
@login_required
def niche_setup():
    profile = NicheProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = NicheProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    if request.method == 'POST':
        profile.channel_name = request.form.get('channel_name', '').strip()
        profile.channel_url = request.form.get('channel_url', '').strip()
        profile.niche = request.form.get('niche', '').strip()
        profile.audience = request.form.get('audience', '').strip()
        profile.style = request.form.get('style', '').strip()
        profile.language = request.form.get('language', 'es')
        profile.country = request.form.get('country', '').strip()
        profile.description = request.form.get('description', '').strip()
        db.session.commit()
        flash('Perfil de canal guardado correctamente.', 'success')
        return redirect(url_for('dashboard.niche_setup'))

    return render_template('dashboard/niche_setup.html', profile=profile)


# ─── Registro central de bots ────────────────────────────────────────────────

BOTS_REGISTRY = {
    'motivacion': {
        'slug': 'motivacion',
        'icon': '💪',
        'name': 'Motivación Bot',
        'dir': Path(r'C:\Users\franc\music\motivacion_bot'),
        'credit_cost': 15,
        'service_slug': 'motivacion_completo',
        'chrome_port': 9229,
        'has_voz': True,
        'default_hashtags': '#Motivacion #Exito #MentalidadGanadora #DesarrolloPersonal',
    },
    'noticias': {
        'slug': 'noticias',
        'icon': '📰',
        'name': 'Noticias RD Bot',
        'dir': Path(r'C:\Users\franc\music\noticias_rd_bot'),
        'credit_cost': 10,
        'service_slug': 'noticias_rd_completo',
        'chrome_port': 9231,
        'has_voz': False,
        'default_hashtags': '#NoticiasRD #RepublicaDominicana #NoticiasLatinas',
    },
    'cristiano': {
        'slug': 'cristiano',
        'icon': '✝️',
        'name': 'Cristiano Bot',
        'dir': Path(r'C:\Users\franc\music\cristiano_bot'),
        'credit_cost': 15,
        'service_slug': 'cristiano_completo',
        'chrome_port': 9232,
        'has_voz': True,
        'default_hashtags': '#Fe #Dios #Cristiano #Biblia #PalabraDeDios',
    },
}

VOCES_ES = [
    'es-MX-DaliaNeural', 'es-MX-JorgeNeural', 'es-AR-ElenaNeural',
    'es-ES-XimenaNeural', 'es-ES-AlvaroNeural', 'es-CO-GonzaloNeural',
    'es-CO-SalomeNeural', 'es-CL-CatalinaNeural',
]


def _bot_load_cfg(user_id: int, bot_slug: str, slot: int = 1) -> tuple:
    from app.models.user_bot_config import UserBotConfig
    obj = UserBotConfig.query.filter_by(user_id=user_id, bot_slug=bot_slug, slot=slot).first()
    if obj:
        return obj.get_config(), obj.get_auto()
    return {}, {
        'activo': False, 'videos_por_dia': 3,
        'hora_inicio': '08:00', 'intervalo_horas': 4,
        'dias': ['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom'],
    }


def _bot_save_cfg(user_id: int, bot_slug: str, cfg: dict, auto: dict, slot: int = 1):
    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    obj = UserBotConfig.get_or_create(user_id, bot_slug, slot)
    obj.set_config(cfg)
    obj.set_auto(auto)
    db.session.commit()
    ws_svc.write_user_config(user_id, bot_slug, cfg, auto,
                             yt_email=obj.yt_email, yt_canal=obj.yt_canal,
                             fb_url=obj.fb_url, slot=slot)


def _bot_sesion_activa(user_id: int, bot_slug: str, slot: int = 1) -> bool:
    from app.services import workspace_service as ws_svc
    return ws_svc.session_active(user_id, bot_slug, slot)


def _bot_fb_sesion_activa(user_id: int, bot_slug: str, slot: int = 1) -> bool:
    from app.services import workspace_service as ws_svc
    return ws_svc.fb_session_active(user_id, bot_slug, slot)


def _bot_load_accounts(user_id: int, bot_slug: str, slot: int = 1) -> tuple:
    from app.models.user_bot_config import UserBotConfig
    obj = UserBotConfig.query.filter_by(user_id=user_id, bot_slug=bot_slug, slot=slot).first()
    if obj:
        return obj.yt_email or '', obj.yt_canal or '', obj.fb_url or ''
    return '', '', ''


def _bot_get_stats(user_id: int, bot_slug: str, slot: int = 1) -> dict:
    from app.services import workspace_service as ws_svc
    return ws_svc.get_stats(user_id, bot_slug, slot)


def _get_slots_info(user_id: int, bot_slug: str, max_slots: int) -> list:
    """Devuelve info de cada slot para las tabs del template."""
    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    result = []
    for s in range(1, max_slots + 1):
        obj = UserBotConfig.query.filter_by(user_id=user_id, bot_slug=bot_slug, slot=s).first()
        result.append({
            'slot': s,
            'yt_email': obj.yt_email if obj else '',
            'fb_url':   obj.fb_url   if obj else '',
            'activo':   obj.get_auto().get('activo', False) if obj else False,
            'yt_ok':    bool(obj and obj.yt_email) and ws_svc.session_active(user_id, bot_slug, s),
            'fb_ok':    bool(obj and obj.fb_url) and ws_svc.fb_session_active(user_id, bot_slug, s),
            'yt_cfg':   bool(obj and obj.yt_email),
            'fb_cfg':   bool(obj and obj.fb_url),
        })
    return result


@dashboard_bp.route('/bots/<slug>', methods=['GET', 'POST'])
@login_required
def bot_config(slug):
    bot = BOTS_REGISTRY.get(slug)
    if not bot:
        abort(404)
    uid = current_user.id
    max_slots = current_user.max_bot_slots
    slot = min(max(request.args.get('slot', 1, type=int), 1), max_slots)
    cfg, auto_cfg = _bot_load_cfg(uid, slug, slot)

    if request.method == 'POST':
        slot = min(max(request.form.get('slot', 1, type=int), 1), max_slots)
        cfg['canal_nombre']   = request.form.get('canal_nombre', '').strip()
        cfg['persona_nombre'] = request.form.get('persona_nombre', '').strip()
        cfg['persona_estilo'] = request.form.get('persona_estilo', '').strip()
        cfg['voz_es']         = request.form.get('voz_es', 'es-MX-JorgeNeural')
        cfg['velocidad']      = request.form.get('velocidad', '-6%')
        cfg['hashtags_base']  = [h.strip() for h in request.form.get('hashtags', '').split() if h.strip()]
        auto_cfg['hora_inicio']    = request.form.get('hora_inicio', '08:00')
        auto_cfg['videos_por_dia'] = int(request.form.get('videos_por_dia', 3))
        auto_cfg['dias']           = request.form.getlist('dias') or ['lun','mar','mie','jue','vie','sab','dom']
        _bot_save_cfg(uid, slug, cfg, auto_cfg, slot)
        flash(f'Cuenta {slot} guardada.', 'success')
        return redirect(url_for('dashboard.bot_config', slug=slug, slot=slot))

    yt_email, yt_canal, fb_url = _bot_load_accounts(uid, slug, slot)
    from types import SimpleNamespace
    bot_obj = SimpleNamespace(**bot)
    return render_template('dashboard/bot_generic.html',
        bot=bot_obj,
        cfg=cfg, auto_cfg=auto_cfg,
        sesion_activa=_bot_sesion_activa(uid, slug, slot),
        fb_sesion_activa=_bot_fb_sesion_activa(uid, slug, slot),
        auto_activo=auto_cfg.get('activo', False),
        yt_email=yt_email, yt_canal=yt_canal, fb_url=fb_url,
        stats=_bot_get_stats(uid, slug, slot),
        voces=VOCES_ES,
        slot=slot,
        max_slots=max_slots,
        slots_info=_get_slots_info(uid, slug, max_slots),
    )


@dashboard_bp.route('/bots/<slug>/save-accounts', methods=['POST'])
@login_required
def bot_save_accounts(slug):
    bot = BOTS_REGISTRY.get(slug)
    if not bot:
        return jsonify({'ok': False, 'error': 'Bot no encontrado'}), 404
    uid = current_user.id
    max_slots = current_user.max_bot_slots
    data = request.get_json(silent=True) or {}
    slot = min(max(data.get('slot', 1), 1), max_slots)
    cfg, auto_cfg = _bot_load_cfg(uid, slug, slot)

    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    obj = UserBotConfig.get_or_create(uid, slug, slot)

    fb_url   = data.get('fb_url', '').strip()
    yt_email = data.get('yt_email', '').strip()
    yt_canal = data.get('yt_canal', '').strip()

    obj.fb_url   = fb_url   or obj.fb_url
    obj.yt_email = yt_email or obj.yt_email
    obj.yt_canal = yt_canal or obj.yt_canal
    if fb_url:   cfg['facebook_page_url'] = fb_url
    if yt_email: cfg['youtube_email']     = yt_email
    if yt_canal: cfg['youtube_canal']     = yt_canal

    obj.set_config(cfg)
    obj.set_auto(auto_cfg)
    db.session.commit()
    ws_svc.write_user_config(uid, slug, cfg, auto_cfg,
                             yt_email=obj.yt_email, yt_canal=obj.yt_canal,
                             fb_url=obj.fb_url, slot=slot)
    return jsonify({'ok': True, 'slot': slot})


@dashboard_bp.route('/bots/<slug>/login', methods=['POST'])
@login_required
def bot_login(slug):
    bot = BOTS_REGISTRY.get(slug)
    if not bot:
        return jsonify({'ok': False, 'error': 'Bot no encontrado'}), 404
    uid = current_user.id
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip()

    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    max_slots = current_user.max_bot_slots
    slot = min(max(data.get('slot', 1), 1), max_slots)
    if email:
        obj = UserBotConfig.get_or_create(uid, slug, slot)
        obj.yt_email = email
        db.session.commit()

    # Chrome profile aislado por usuario+bot+slot
    plataforma = data.get('plataforma', 'youtube')
    if plataforma == 'facebook':
        profile_dir = str(ws_svc.user_workspace(uid, slug, slot) / 'fb_profile')
        url_inicio = 'https://www.facebook.com/login'
    else:
        profile_dir = str(ws_svc.user_workspace(uid, slug, slot) / 'chrome_profile')
        url_inicio = 'https://studio.youtube.com'
    try:
        subprocess.Popen([
            CHROME_EXE,
            f'--remote-debugging-port={bot["chrome_port"]}',
            f'--user-data-dir={profile_dir}',
            '--no-first-run', '--no-default-browser-check',
            url_inicio
        ])
        return jsonify({'ok': True})
    except FileNotFoundError:
        return jsonify({'ok': False, 'error': 'Chrome no encontrado.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@dashboard_bp.route('/bots/<slug>/toggle', methods=['POST'])
@login_required
def bot_toggle(slug):
    bot = BOTS_REGISTRY.get(slug)
    if not bot:
        abort(404)
    uid = current_user.id
    max_slots = current_user.max_bot_slots
    slot = min(max(request.form.get('slot', 1, type=int), 1), max_slots)
    cfg, auto_cfg = _bot_load_cfg(uid, slug, slot)
    auto_cfg['activo'] = not auto_cfg.get('activo', False)
    _bot_save_cfg(uid, slug, cfg, auto_cfg, slot)
    estado = 'activado' if auto_cfg['activo'] else 'pausado'
    flash(f'{bot["name"]} (Cuenta {slot}) {estado}.', 'success')
    return redirect(url_for('dashboard.bot_config', slug=slug, slot=slot))


@dashboard_bp.route('/bots/<slug>/run', methods=['POST'])
@login_required
def bot_run_now(slug):
    bot = BOTS_REGISTRY.get(slug)
    if not bot:
        abort(404)
    from flask import current_app
    from app.services import workspace_service as ws_svc
    uid = current_user.id
    cost = bot['credit_cost']
    if not current_user.is_admin() and current_user.credits < cost:
        flash(f'No tienes suficientes créditos. Necesitas {cost}.', 'danger')
        return redirect(url_for('dashboard.bot_config', slug=slug))

    service = Service.query.filter_by(slug=bot['service_slug']).first()
    if not service:
        flash('Servicio no configurado. Contacta al administrador.', 'danger')
        return redirect(url_for('dashboard.bot_config', slug=slug))

    max_slots = current_user.max_bot_slots
    slot = min(max(request.form.get('slot', 1, type=int), 1), max_slots)

    _, _, fb_url = _bot_load_accounts(uid, slug, slot)
    cfg, auto_cfg = _bot_load_cfg(uid, slug, slot)
    workspace = str(ws_svc.user_workspace(uid, slug, slot))

    ws_svc.write_user_config(uid, slug, cfg, auto_cfg,
                             yt_email=cfg.get('youtube_email', ''),
                             yt_canal=cfg.get('youtube_canal', ''),
                             fb_url=fb_url, slot=slot)

    params = {
        'fecha': date.today().strftime('%Y-%m-%d'),
        'subir_youtube':     bool(request.form.get('subir_youtube')),
        'yt_shorts':         bool(request.form.get('yt_shorts')),
        'publicar_facebook': bool(request.form.get('publicar_facebook')),
        'fb_reels':          bool(request.form.get('fb_reels')),
        'fb_fotos':          bool(request.form.get('fb_fotos')),
        'user_id': uid,
        'user_workspace': workspace,
        'bot_slug': slug,
        'slot': slot,
    }
    if fb_url:
        params['fb_url'] = fb_url

    job = Job(user_id=uid, service_id=service.id, credits_used=cost)
    job.set_params(params)
    db.session.add(job)
    db.session.flush()

    ok = credit_service.consume_credits(current_user, cost, f'{bot["name"]} (Cuenta {slot})', reference=f'job:{job.id}')
    if not ok:
        db.session.rollback()
        flash('Error al descontar créditos.', 'danger')
        return redirect(url_for('dashboard.bot_config', slug=slug, slot=slot))

    job.status = 'queued'
    db.session.commit()

    flash(f'✅ {bot["name"]} en cola — Job #{job.id}. El worker procesará el trabajo en segundos.', 'success')
    return redirect(url_for('dashboard.jobs'))


@dashboard_bp.route('/bots/<slug>/download')
@login_required
def bot_download(slug):
    from app.services import workspace_service as ws_svc
    import zipfile, tempfile, os
    uid = current_user.id
    ws = ws_svc.user_workspace(uid, slug)
    output_dir = ws / 'output'
    if not output_dir.exists():
        flash('No hay contenido generado todavía.', 'warning')
        return redirect(url_for('dashboard.bot_config', slug=slug))

    archivos = list(output_dir.rglob('*'))
    archivos = [f for f in archivos if f.is_file()]
    if not archivos:
        flash('La carpeta de contenido está vacía.', 'warning')
        return redirect(url_for('dashboard.bot_config', slug=slug))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp.close()
    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in archivos:
            zf.write(f, f.relative_to(output_dir))

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name=f'{slug}_contenido.zip',
        mimetype='application/zip',
    )


@dashboard_bp.route('/bots/horoscopo/download')
@login_required
def bot_horoscopo_download():
    from app.services import workspace_service as ws_svc
    import zipfile, tempfile
    uid = current_user.id
    ws = ws_svc.user_workspace(uid, 'horoscopo')
    output_dir = ws / 'output'
    if not output_dir.exists():
        flash('No hay contenido generado todavía.', 'warning')
        return redirect(url_for('dashboard.bot_horoscopo'))

    archivos = [f for f in output_dir.rglob('*') if f.is_file()]
    if not archivos:
        flash('La carpeta de contenido está vacía.', 'warning')
        return redirect(url_for('dashboard.bot_horoscopo'))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    tmp.close()
    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in archivos:
            zf.write(f, f.relative_to(output_dir))

    return send_file(
        tmp.name,
        as_attachment=True,
        download_name='horoscopo_contenido.zip',
        mimetype='application/zip',
    )


# ─── Horóscopo Bot ───────────────────────────────────────────────────────────

def _load_horoscopo_cfg():
    cfg_path = HOROSCOPO_DIR / 'config.json'
    auto_path = HOROSCOPO_DIR / 'auto_config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else {}
    auto = json.loads(auto_path.read_text(encoding='utf-8')) if auto_path.exists() else {}
    return cfg, auto


def _save_horoscopo_cfg(cfg, auto):
    (HOROSCOPO_DIR / 'config.json').write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    (HOROSCOPO_DIR / 'auto_config.json').write_text(
        json.dumps(auto, ensure_ascii=False, indent=2), encoding='utf-8')


def _sesion_activa():
    """Verifica si el perfil de Chrome del bot tiene sesión de YouTube guardada."""
    cookies_path = HOROSCOPO_DIR / 'youtube_bot_profile' / 'Default' / 'Cookies'
    return cookies_path.exists() and cookies_path.stat().st_size > 50000


def _load_yt_email():
    email_file = HOROSCOPO_DIR / 'yt_account.txt'
    return email_file.read_text(encoding='utf-8').strip() if email_file.exists() else ''

def _load_fb_url():
    fb_file = HOROSCOPO_DIR / 'fb_page.txt'
    return fb_file.read_text(encoding='utf-8').strip() if fb_file.exists() else ''

def _load_yt_canal():
    f = HOROSCOPO_DIR / 'yt_canal.txt'
    return f.read_text(encoding='utf-8').strip() if f.exists() else ''


def _get_stats():
    output = HOROSCOPO_DIR / 'diario'
    videos = list(output.rglob('*.mp4')) if output.exists() else []
    hoy = date.today().strftime('%Y-%m-%d')
    videos_hoy = [v for v in videos if hoy in v.name]
    cola = [v for v in (HOROSCOPO_DIR / 'diario').rglob('*.json')
            if hoy in v.name and 'pendiente' in v.read_text(errors='replace')] if output.exists() else []
    total_bytes = sum(f.stat().st_size for f in (HOROSCOPO_DIR / 'diario').rglob('*')
                      if f.is_file()) if output.exists() else 0
    return {
        'videos_hoy': len(videos_hoy),
        'en_cola': len(cola),
        'total_videos': len(videos),
        'size_mb': round(total_bytes / (1024 * 1024), 1),
    }


@dashboard_bp.route('/bots/horoscopo', methods=['GET', 'POST'])
@login_required
def bot_horoscopo():
    uid = current_user.id
    cfg, auto_cfg = _bot_load_cfg(uid, 'horoscopo')

    if request.method == 'POST':
        cfg['canal_nombre']   = request.form.get('canal_nombre', '').strip()
        cfg['persona_nombre'] = request.form.get('persona_nombre', '').strip()
        cfg['persona_estilo'] = request.form.get('persona_estilo', '').strip()
        cfg['voz_es']         = request.form.get('voz_es', 'es-MX-DaliaNeural')
        cfg['velocidad']      = request.form.get('velocidad', '-6%')
        hashtags_raw          = request.form.get('hashtags', '')
        cfg['hashtags_base']  = [h.strip() for h in hashtags_raw.split() if h.strip()]
        auto_cfg['hora_inicio']     = request.form.get('hora_inicio', '07:00')
        auto_cfg['videos_por_dia']  = int(request.form.get('videos_por_dia', 12))
        auto_cfg['dias']            = request.form.getlist('dias') or ['lun','mar','mie','jue','vie','sab','dom']
        _bot_save_cfg(uid, 'horoscopo', cfg, auto_cfg)
        flash('Configuración guardada correctamente.', 'success')
        return redirect(url_for('dashboard.bot_horoscopo'))

    voces = [
        'es-MX-DaliaNeural', 'es-MX-JorgeNeural', 'es-AR-ElenaNeural',
        'es-ES-XimenaNeural', 'es-ES-AlvaroNeural', 'es-CO-GonzaloNeural',
        'es-CO-SalomeNeural', 'es-CL-CatalinaNeural',
    ]
    yt_email, yt_canal, fb_url = _bot_load_accounts(uid, 'horoscopo')
    return render_template('dashboard/bot_horoscopo.html',
        cfg=cfg, auto_cfg=auto_cfg, voces=voces,
        sesion_activa=_bot_sesion_activa(uid, 'horoscopo'),
        auto_activo=auto_cfg.get('activo', False),
        yt_email=yt_email, yt_canal=yt_canal, fb_url=fb_url,
        stats=_bot_get_stats(uid, 'horoscopo'),
        hoy=date.today().strftime('%Y-%m-%d'),
    )


@dashboard_bp.route('/bots/horoscopo/save-fb', methods=['POST'])
@login_required
def bot_horoscopo_save_fb():
    data = request.get_json(silent=True) or {}
    fb_url   = data.get('fb_url', '').strip()
    yt_email = data.get('yt_email', '').strip()
    yt_canal = data.get('yt_canal', '').strip()

    uid = current_user.id
    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    obj = UserBotConfig.get_or_create(uid, 'horoscopo')
    cfg = obj.get_config()
    auto_cfg = obj.get_auto()

    if fb_url:
        obj.fb_url = fb_url
        cfg['facebook_page_url'] = fb_url
    if yt_email:
        obj.yt_email = yt_email
        cfg['youtube_email'] = yt_email
    if yt_canal:
        obj.yt_canal = yt_canal
        cfg['youtube_canal'] = yt_canal

    obj.set_config(cfg)
    db.session.commit()
    ws_svc.write_user_config(uid, 'horoscopo', cfg, auto_cfg,
                             yt_email=obj.yt_email, yt_canal=obj.yt_canal, fb_url=obj.fb_url)
    return jsonify({'ok': True})


@dashboard_bp.route('/bots/horoscopo/login', methods=['POST'])
@login_required
def bot_horoscopo_login():
    uid = current_user.id
    from app.models.user_bot_config import UserBotConfig
    from app.services import workspace_service as ws_svc
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip()
    if email:
        obj = UserBotConfig.get_or_create(uid, 'horoscopo')
        obj.yt_email = email
        db.session.commit()

    profile_dir = str(ws_svc.user_workspace(uid, 'horoscopo') / 'chrome_profile')
    try:
        subprocess.Popen([
            CHROME_EXE,
            '--remote-debugging-port=9225',
            f'--user-data-dir={profile_dir}',
            '--no-first-run', '--no-default-browser-check',
            'https://studio.youtube.com'
        ])
        return jsonify({'ok': True})
    except FileNotFoundError:
        return jsonify({'ok': False, 'error': 'Chrome no encontrado.'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@dashboard_bp.route('/bots/horoscopo/toggle', methods=['POST'])
@login_required
def bot_horoscopo_toggle():
    uid = current_user.id
    cfg, auto_cfg = _bot_load_cfg(uid, 'horoscopo')
    auto_cfg['activo'] = not auto_cfg.get('activo', False)
    _bot_save_cfg(uid, 'horoscopo', cfg, auto_cfg)
    estado = 'activado' if auto_cfg['activo'] else 'pausado'
    flash(f'Bot de horóscopo {estado}.', 'success')
    return redirect(url_for('dashboard.bot_horoscopo'))


@dashboard_bp.route('/bots/horoscopo/run', methods=['POST'])
@login_required
def bot_horoscopo_run():
    from app.services.bots.horoscopo_runner import run_pipeline_async
    from app.services import workspace_service as ws_svc
    from flask import current_app
    uid = current_user.id

    if not current_user.is_admin() and current_user.credits < 20:
        flash('No tienes suficientes créditos. Necesitas 20.', 'danger')
        return redirect(url_for('dashboard.bot_horoscopo'))

    service = Service.query.filter_by(slug='horoscopo_completo').first()
    if not service:
        flash('Servicio no configurado.', 'danger')
        return redirect(url_for('dashboard.bot_horoscopo'))

    cfg, auto_cfg = _bot_load_cfg(uid, 'horoscopo')
    _, _, fb_url = _bot_load_accounts(uid, 'horoscopo')
    workspace = str(ws_svc.user_workspace(uid, 'horoscopo'))
    ws_svc.write_user_config(uid, 'horoscopo', cfg, auto_cfg,
                             yt_email=cfg.get('youtube_email', ''),
                             yt_canal=cfg.get('youtube_canal', ''),
                             fb_url=fb_url)

    params = {
        'fecha': request.form.get('fecha', date.today().strftime('%Y-%m-%d')),
        'signos': 'todos',
        'subir_youtube':     bool(request.form.get('subir_youtube')),
        'yt_shorts':         bool(request.form.get('yt_shorts')),
        'publicar_facebook': bool(request.form.get('publicar_facebook')),
        'fb_reels':          bool(request.form.get('fb_reels')),
        'fb_fotos':          bool(request.form.get('fb_fotos')),
        'user_id': uid,
        'user_workspace': workspace,
        'bot_slug': 'horoscopo',
    }
    if fb_url:
        params['fb_url'] = fb_url

    job = Job(user_id=uid, service_id=service.id, credits_used=20)
    job.set_params(params)
    db.session.add(job)
    db.session.flush()

    ok = credit_service.consume_credits(current_user, 20, 'Horóscopo completo', reference=f'job:{job.id}')
    if not ok:
        db.session.rollback()
        flash('Error al descontar créditos.', 'danger')
        return redirect(url_for('dashboard.bot_horoscopo'))

    job.status = 'queued'
    db.session.commit()

    flash(f'✅ Horóscopo en cola — Job #{job.id}. El worker procesará el trabajo en segundos.', 'success')
    return redirect(url_for('dashboard.jobs'))
