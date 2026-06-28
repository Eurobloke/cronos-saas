# -*- coding: utf-8 -*-
from flask import current_app
from app.extensions import db
from app.models.notification import Notification


LOW_CREDITS_THRESHOLD = 5


def grant_credits(user, amount: int, description: str, reference: str = None) -> bool:
    user.add_credits(amount, description, reference)
    db.session.flush()
    _notify_balance(user)
    return True


def consume_credits(user, amount: int, description: str, reference: str = None) -> bool:
    ok = user.consume_credits(amount, description, reference)
    if not ok:
        return False
    db.session.flush()
    _notify_balance(user)
    return True


def _notify_balance(user):
    if user.credits <= LOW_CREDITS_THRESHOLD:
        notif = Notification(
            user_id=user.id,
            title='⚠️ Créditos bajos',
            message=f'Te quedan solo {user.credits} créditos. Recarga para seguir usando los servicios.',
            type='warning',
            link='/dashboard/credits',
        )
        db.session.add(notif)
        try:
            from app.services.email_service import send_low_credits
            send_low_credits(user)
        except Exception as e:
            current_app.logger.warning(f'No se pudo enviar email de créditos bajos: {e}')


def apply_welcome_credits(user):
    credits = current_app.config.get('WELCOME_CREDITS', 10)
    grant_credits(user, credits, 'Créditos de bienvenida')
    notif = Notification(
        user_id=user.id,
        title='🎉 ¡Bienvenido!',
        message=f'Recibiste {credits} créditos de bienvenida para probar la plataforma.',
        type='success',
        link='/dashboard',
    )
    db.session.add(notif)
