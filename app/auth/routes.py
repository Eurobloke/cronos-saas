# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models.user import User
from app.auth.forms import LoginForm, RegisterForm, ForgotPasswordForm, ResetPasswordForm, ChangePasswordForm
from app.services import token_service, email_service, credit_service

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('20 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if not user:
            flash('Email o contraseña incorrectos.', 'danger')
            return render_template('auth/login.html', form=form)

        if user.is_locked():
            flash('Cuenta bloqueada temporalmente por múltiples intentos fallidos. Intenta en 15 minutos.', 'danger')
            return render_template('auth/login.html', form=form)

        if not user.check_password(form.password.data):
            user.login_attempts = (user.login_attempts or 0) + 1
            if user.login_attempts >= 5:
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                user.login_attempts = 0
                flash('Demasiados intentos fallidos. Cuenta bloqueada 15 minutos.', 'danger')
            else:
                remaining = 5 - user.login_attempts
                flash(f'Contraseña incorrecta. {remaining} intento(s) restante(s).', 'danger')
            db.session.commit()
            return render_template('auth/login.html', form=form)

        if not user.is_active:
            flash('Tu cuenta ha sido desactivada. Contacta soporte.', 'danger')
            return render_template('auth/login.html', form=form)

        user.login_attempts = 0
        user.locked_until = None
        user.last_login = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=form.remember.data)
        next_page = request.args.get('next')
        return redirect(next_page or url_for('dashboard.index'))

    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.lower().strip()
        if User.query.filter_by(email=email).first():
            flash('Ya existe una cuenta con ese email.', 'danger')
            return render_template('auth/register.html', form=form)

        user = User(
            email=email,
            username=form.username.data.strip(),
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.flush()

        credit_service.apply_welcome_credits(user)
        db.session.commit()

        # Crear workspace en disco para cada bot
        try:
            from app.services.workspace_service import create_user_workspaces
            create_user_workspaces(user.id)
        except Exception:
            pass

        token = token_service.generate_token(user.email, salt='email-verify')
        email_service.send_verify_email(user, token)
        email_service.send_welcome(user)

        flash('¡Cuenta creada! Revisa tu email para verificar tu cuenta.', 'success')
        login_user(user)
        return redirect(url_for('dashboard.index'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/verify/<token>')
def verify_email(token):
    email = token_service.verify_token(
        token, salt='email-verify',
        max_age=current_app.config['EMAIL_VERIFY_EXPIRY']
    )
    if not email:
        flash('El enlace de verificación es inválido o ha expirado.', 'danger')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first_or_404()
    if user.email_verified:
        flash('Tu email ya estaba verificado.', 'info')
    else:
        user.email_verified = True
        db.session.commit()
        flash('✅ Email verificado correctamente. ¡Bienvenido!', 'success')
    return redirect(url_for('dashboard.index'))


@auth_bp.route('/resend-verify')
@login_required
def resend_verify():
    if current_user.email_verified:
        flash('Tu email ya está verificado.', 'info')
        return redirect(url_for('dashboard.index'))
    token = token_service.generate_token(current_user.email, salt='email-verify')
    email_service.send_verify_email(current_user, token)
    flash('Email de verificación reenviado.', 'success')
    return redirect(url_for('dashboard.index'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per hour')
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user:
            token = token_service.generate_token(user.email, salt='password-reset')
            email_service.send_reset_password(user, token)
        flash('Si el email existe, recibirás un enlace para restablecer tu contraseña.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html', form=form)


@auth_bp.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = token_service.verify_token(
        token, salt='password-reset',
        max_age=current_app.config['PASSWORD_RESET_EXPIRY']
    )
    if not email:
        flash('El enlace es inválido o ha expirado.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first_or_404()
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.login_attempts = 0
        user.locked_until = None
        db.session.commit()
        email_service.send_password_changed(user)
        flash('Contraseña actualizada. Puedes iniciar sesión.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', form=form, token=token)


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('auth.login'))
