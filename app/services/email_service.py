# -*- coding: utf-8 -*-
from flask import current_app, render_template
from flask_mail import Message
from app.extensions import mail


def _send(subject: str, recipients: list[str], html_body: str, text_body: str = ''):
    try:
        msg = Message(
            subject=subject,
            recipients=recipients,
            html=html_body,
            body=text_body or html_body,
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error(f'Error enviando email a {recipients}: {e}')
        return False


def send_welcome(user):
    html = render_template('emails/welcome.html', user=user,
                           app_name=current_app.config['APP_NAME'],
                           app_url=current_app.config['APP_URL'])
    return _send(f'¡Bienvenido a {current_app.config["APP_NAME"]}!', [user.email], html)


def send_verify_email(user, token: str):
    verify_url = f'{current_app.config["APP_URL"]}/auth/verify/{token}'
    html = render_template('emails/verify_email.html', user=user, verify_url=verify_url,
                           app_name=current_app.config['APP_NAME'])
    return _send('Verifica tu correo electrónico', [user.email], html)


def send_reset_password(user, token: str):
    reset_url = f'{current_app.config["APP_URL"]}/auth/reset/{token}'
    html = render_template('emails/reset_password.html', user=user, reset_url=reset_url,
                           app_name=current_app.config['APP_NAME'])
    return _send('Restablecer contraseña', [user.email], html)


def send_purchase_confirmation(user, payment):
    html = render_template('emails/purchase_confirmation.html', user=user, payment=payment,
                           app_name=current_app.config['APP_NAME'],
                           app_url=current_app.config['APP_URL'])
    return _send('Confirmación de compra', [user.email], html)


def send_low_credits(user):
    html = render_template('emails/low_credits.html', user=user,
                           app_name=current_app.config['APP_NAME'],
                           app_url=current_app.config['APP_URL'])
    return _send('⚠️ Te quedan pocos créditos', [user.email], html)


def send_subscription_renewal(user, subscription):
    html = render_template('emails/subscription_renewal.html', user=user,
                           subscription=subscription,
                           app_name=current_app.config['APP_NAME'])
    return _send('Tu suscripción ha sido renovada', [user.email], html)


def send_password_changed(user):
    html = render_template('emails/password_changed.html', user=user,
                           app_name=current_app.config['APP_NAME'])
    return _send('Tu contraseña fue cambiada', [user.email], html)
