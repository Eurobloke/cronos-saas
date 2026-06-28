# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, abort
from flask_login import login_required, current_user
import io

from app.extensions import db, limiter
from app.models import Service, Job, CreditTransaction, Payment, Notification
from app.models.niche_profile import NicheProfile, Conversation
from app.services import credit_service
from app.services.bot_runner import run_job_async
from app.services.invoice_service import generate_invoice_pdf
from app.auth.forms import ChangePasswordForm
from app.services import email_service

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.route('/')
@login_required
def index():
    recent_jobs = current_user.jobs.order_by(Job.created_at.desc()).limit(5).all()
    recent_tx = current_user.credit_transactions.order_by(
        CreditTransaction.created_at.desc()).limit(5).all()
    unread_count = current_user.notifications.filter_by(is_read=False).count()
    services = Service.query.filter_by(is_active=True).order_by(Service.sort_order).all()
    return render_template('dashboard/index.html',
                           recent_jobs=recent_jobs,
                           recent_tx=recent_tx,
                           unread_count=unread_count,
                           services=services)


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

    if current_user.credits < service.credit_cost:
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
    jobs_pag = current_user.jobs.order_by(Job.created_at.desc()).paginate(page=page, per_page=20)
    return render_template('dashboard/jobs.html', jobs=jobs_pag)


@dashboard_bp.route('/jobs/<int:job_id>')
@login_required
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    if job.user_id != current_user.id:
        abort(403)
    return render_template('dashboard/job_detail.html', job=job)


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
