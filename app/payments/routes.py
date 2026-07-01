# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort
from flask_login import login_required, current_user

from app.extensions import db, csrf
from app.models import Plan, Payment, Subscription, Coupon
from app.services.paypal_service import paypal
from app.services.dlocal_service import dlocal
from app.services.stripe_service import stripe_svc
from app.services.lemonsqueezy_service import lemonsqueezy
from app.services import credit_service, email_service

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

# ─── Packs de créditos predefinidos ──────────────────────────────────────────
CREDIT_PACKS = [
    {'id': 'pack_50',  'credits': 50,   'price': 4.99,  'label': 'Pack Básico',   'popular': False},
    {'id': 'pack_150', 'credits': 150,  'price': 12.99, 'label': 'Pack Creator',  'popular': True},
    {'id': 'pack_500', 'credits': 500,  'price': 34.99, 'label': 'Pack Agency',   'popular': False},
]


@payments_bp.route('/plans')
@login_required
def plans():
    active_plans = Plan.query.filter_by(is_active=True).order_by(Plan.sort_order).all()
    return render_template('payments/plans.html',
                           plans=active_plans,
                           packs=CREDIT_PACKS,
                           dlocal_enabled=dlocal.is_configured(),
                           stripe_enabled=stripe_svc.is_configured(),
                           stripe_public_key=stripe_svc.public_key())


# ─── Compra de pack de créditos ───────────────────────────────────────────────

@payments_bp.route('/buy-credits/<pack_id>', methods=['POST'])
@login_required
def buy_credits(pack_id):
    pack = next((p for p in CREDIT_PACKS if p['id'] == pack_id), None)
    if not pack:
        abort(404)

    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    discount = 0.0
    final_price = pack['price']

    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(pack['price'])
            discount = round(pack['price'] - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))

    app_url = current_app.config['APP_URL']
    try:
        order_data = paypal.create_order(
            amount=final_price,
            description=f'{pack["credits"]} créditos - {pack["label"]}',
            return_url=f'{app_url}/payments/capture?pack_id={pack_id}&coupon={coupon_code}',
            cancel_url=f'{app_url}/payments/cancel',
        )
    except Exception as e:
        current_app.logger.error(f'PayPal create_order error: {e}')
        flash('Error al conectar con PayPal. Intenta de nuevo.', 'danger')
        return redirect(url_for('payments.plans'))

    # Guardar pago pendiente
    payment = Payment(
        user_id=current_user.id,
        amount=final_price,
        type='credit_pack',
        credits_granted=pack['credits'],
        coupon_id=coupon.id if coupon else None,
        discount_amount=discount,
        description=f'{pack["credits"]} créditos ({pack["label"]})',
        paypal_order_id=order_data['order_id'],
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()

    return redirect(order_data['approve_url'])


# ─── Compra de plan mensual/anual ─────────────────────────────────────────────

@payments_bp.route('/buy-plan/<int:plan_id>/<billing>', methods=['POST'])
@login_required
def buy_plan(plan_id, billing):
    if billing not in ('monthly', 'annual'):
        abort(400)
    plan = Plan.query.get_or_404(plan_id)
    if not plan.is_active:
        abort(404)

    price = plan.price_annual if billing == 'annual' else plan.price_monthly

    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    discount = 0.0
    final_price = price

    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(price)
            discount = round(price - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))

    app_url = current_app.config['APP_URL']
    label = f'Plan {plan.name} - {"Anual" if billing == "annual" else "Mensual"}'
    try:
        order_data = paypal.create_order(
            amount=final_price,
            description=label,
            return_url=f'{app_url}/payments/capture?plan_id={plan_id}&billing={billing}&coupon={coupon_code}',
            cancel_url=f'{app_url}/payments/cancel',
        )
    except Exception as e:
        current_app.logger.error(f'PayPal plan error: {e}')
        flash('Error al conectar con PayPal.', 'danger')
        return redirect(url_for('payments.plans'))

    payment = Payment(
        user_id=current_user.id,
        amount=final_price,
        type=f'plan_{billing}',
        credits_granted=plan.credits_monthly,
        plan_id=plan.id,
        coupon_id=coupon.id if coupon else None,
        discount_amount=discount,
        description=label,
        paypal_order_id=order_data['order_id'],
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()

    return redirect(order_data['approve_url'])


# ─── Captura del pago (PayPal nos redirige aquí tras aprobación) ──────────────

@payments_bp.route('/capture')
@login_required
def capture():
    order_id = request.args.get('token')  # PayPal pasa el order_id como "token"
    if not order_id:
        flash('Pago cancelado o parámetros inválidos.', 'warning')
        return redirect(url_for('payments.plans'))

    payment = Payment.query.filter_by(
        paypal_order_id=order_id, user_id=current_user.id, status='pending'
    ).first()
    if not payment:
        flash('No se encontró el pago pendiente.', 'danger')
        return redirect(url_for('dashboard.billing'))

    try:
        result = paypal.capture_order(order_id)
        cap = result.get('capture', {})
        if result.get('order_status') == 'COMPLETED' and cap.get('status') == 'COMPLETED':
            payment.status = 'completed'
            payment.paypal_capture_id = cap.get('capture_id')
            payment.paypal_payer_email = cap.get('payer_email')
            payment.completed_at = datetime.now(timezone.utc)

            # Otorgar créditos
            credit_service.grant_credits(
                current_user, payment.credits_granted,
                payment.description, reference=f'payment:{payment.id}'
            )

            # Si es plan, crear suscripción
            if payment.plan_id:
                months = 12 if payment.type == 'plan_annual' else 1
                expires = datetime.now(timezone.utc) + timedelta(days=30 * months)
                sub = Subscription(
                    user_id=current_user.id,
                    plan_id=payment.plan_id,
                    billing_cycle=payment.type.replace('plan_', ''),
                    status='active',
                    expires_at=expires,
                )
                db.session.add(sub)

            # Marcar cupón usado
            if payment.coupon_id:
                coupon = Coupon.query.get(payment.coupon_id)
                if coupon:
                    coupon.times_used += 1

            db.session.commit()

            email_service.send_purchase_confirmation(current_user, payment)
            flash(f'✅ ¡Pago completado! Se añadieron {payment.credits_granted} créditos a tu cuenta.', 'success')
            return redirect(url_for('payments.success', payment_id=payment.id))
        else:
            payment.status = 'failed'
            db.session.commit()
            flash('El pago no pudo ser procesado.', 'danger')
    except Exception as e:
        current_app.logger.error(f'PayPal capture error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al procesar el pago. Contacta soporte si se cobró.', 'danger')

    return redirect(url_for('payments.plans'))


@payments_bp.route('/success/<int:payment_id>')
@login_required
def success(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if payment.user_id != current_user.id:
        abort(403)
    return render_template('payments/success.html', payment=payment)


@payments_bp.route('/cancel')
@login_required
def cancel():
    flash('Pago cancelado. No se realizó ningún cargo.', 'info')
    return render_template('payments/cancel.html')


@payments_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def paypal_webhook():
    """
    PayPal llama aquí cuando un pago se completa, aunque el usuario
    cierre el navegador antes del redirect. Es la capa de seguridad extra.
    """
    import json as _json
    body = request.get_data()
    event = _json.loads(body) if body else {}
    event_type = event.get('event_type', '')

    # Verificar firma del webhook (si PAYPAL_WEBHOOK_ID está configurado)
    webhook_id = current_app.config.get('PAYPAL_WEBHOOK_ID', '')
    if webhook_id:
        valid = paypal.verify_webhook(dict(request.headers), body, webhook_id)
        if not valid:
            current_app.logger.warning('[Webhook] Firma inválida — ignorado')
            return jsonify({'ok': False}), 400

    # Solo procesamos captura completada
    if event_type != 'PAYMENT.CAPTURE.COMPLETED':
        return jsonify({'ok': True, 'skipped': event_type})

    try:
        resource = event.get('resource', {})
        order_id = (resource.get('supplementary_data', {})
                    .get('related_ids', {}).get('order_id'))
        capture_id = resource.get('id')
        payer_email = (event.get('resource', {})
                       .get('payer', {}).get('email_address', ''))
        amount = float(resource.get('amount', {}).get('value', 0))

        if not order_id and not capture_id:
            return jsonify({'ok': True, 'msg': 'sin order_id'})

        # Buscar pago pendiente por order_id o capture_id
        payment = None
        if order_id:
            payment = Payment.query.filter_by(paypal_order_id=order_id).first()
        if not payment and capture_id:
            payment = Payment.query.filter_by(paypal_capture_id=capture_id).first()

        if not payment:
            current_app.logger.info(f'[Webhook] Pago no encontrado: order={order_id} cap={capture_id}')
            return jsonify({'ok': True, 'msg': 'pago no encontrado'})

        if payment.status == 'completed':
            return jsonify({'ok': True, 'msg': 'ya procesado'})

        # Marcar como completado y otorgar créditos
        payment.status = 'completed'
        payment.paypal_capture_id = capture_id or payment.paypal_capture_id
        payment.paypal_payer_email = payer_email
        payment.completed_at = datetime.now(timezone.utc)

        user = payment.user
        credit_service.grant_credits(
            user, payment.credits_granted,
            f'[Webhook] {payment.description}',
            reference=f'payment:{payment.id}'
        )

        # Activar plan si aplica
        if payment.plan_id:
            months = 12 if payment.type == 'plan_annual' else 1
            expires = datetime.now(timezone.utc) + timedelta(days=30 * months)
            existing = Subscription.query.filter_by(
                user_id=user.id, plan_id=payment.plan_id, status='active'
            ).first()
            if not existing:
                sub = Subscription(
                    user_id=user.id, plan_id=payment.plan_id,
                    billing_cycle=payment.type.replace('plan_', ''),
                    status='active', expires_at=expires,
                )
                db.session.add(sub)

        db.session.commit()
        email_service.send_purchase_confirmation(user, payment)
        current_app.logger.info(f'[Webhook] Pago #{payment.id} procesado vía webhook. {payment.credits_granted} créditos a {user.email}')

    except Exception as e:
        current_app.logger.error(f'[Webhook] Error procesando: {e}')
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════════════════
# ─── dLocal Go — Pagos desde cualquier país ──────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

@payments_bp.route('/dlocal/buy-credits/<pack_id>', methods=['POST'])
@login_required
def dlocal_buy_credits(pack_id):
    pack = next((p for p in CREDIT_PACKS if p['id'] == pack_id), None)
    if not pack:
        abort(404)

    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    discount = 0.0
    final_price = pack['price']

    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(pack['price'])
            discount = round(pack['price'] - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))

    # Guardar pago pendiente primero para obtener el ID
    payment = Payment(
        user_id=current_user.id,
        amount=final_price,
        type='credit_pack',
        credits_granted=pack['credits'],
        coupon_id=coupon.id if coupon else None,
        discount_amount=discount,
        description=f'{pack["credits"]} créditos ({pack["label"]})',
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()

    app_url = current_app.config['APP_URL']
    try:
        result = dlocal.create_payment(
            amount=final_price,
            currency='USD',
            description=f'{pack["credits"]} créditos — {pack["label"]}',
            success_url=f'{app_url}/payments/dlocal/success?payment_id={payment.id}',
            back_url=f'{app_url}/payments/cancel',
            notification_url=f'{app_url}/payments/dlocal/webhook',
            order_id=str(payment.id),
        )
    except Exception as e:
        current_app.logger.error(f'dLocal create_payment error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al conectar con dLocal. Intenta con PayPal.', 'danger')
        return redirect(url_for('payments.plans'))

    payment.paypal_order_id = result['payment_id']  # reutilizamos campo para ID dLocal
    db.session.commit()
    return redirect(result['redirect_url'])


@payments_bp.route('/dlocal/buy-plan/<int:plan_id>/<billing>', methods=['POST'])
@login_required
def dlocal_buy_plan(plan_id, billing):
    if billing not in ('monthly', 'annual'):
        abort(400)
    plan = Plan.query.get_or_404(plan_id)
    if not plan.is_active:
        abort(404)

    price = plan.price_annual if billing == 'annual' else plan.price_monthly
    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    discount = 0.0
    final_price = price

    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(price)
            discount = round(price - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))

    label = f'Plan {plan.name} - {"Anual" if billing == "annual" else "Mensual"}'
    payment = Payment(
        user_id=current_user.id,
        amount=final_price,
        type=f'plan_{billing}',
        credits_granted=plan.credits_monthly,
        plan_id=plan.id,
        coupon_id=coupon.id if coupon else None,
        discount_amount=discount,
        description=label,
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()

    app_url = current_app.config['APP_URL']
    try:
        result = dlocal.create_payment(
            amount=final_price,
            currency='USD',
            description=label,
            success_url=f'{app_url}/payments/dlocal/success?payment_id={payment.id}',
            back_url=f'{app_url}/payments/cancel',
            notification_url=f'{app_url}/payments/dlocal/webhook',
            order_id=str(payment.id),
        )
    except Exception as e:
        current_app.logger.error(f'dLocal plan error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al conectar con dLocal. Intenta con PayPal.', 'danger')
        return redirect(url_for('payments.plans'))

    payment.paypal_order_id = result['payment_id']
    db.session.commit()
    return redirect(result['redirect_url'])


@payments_bp.route('/dlocal/success')
@login_required
def dlocal_success():
    """dLocal redirige aquí cuando el cliente completa el pago."""
    payment_id = request.args.get('payment_id', type=int)
    if not payment_id:
        flash('Parámetros inválidos.', 'warning')
        return redirect(url_for('payments.plans'))

    payment = Payment.query.get_or_404(payment_id)
    if payment.user_id != current_user.id:
        abort(403)

    if payment.status == 'completed':
        flash(f'✅ ¡Pago ya procesado! {payment.credits_granted} créditos en tu cuenta.', 'success')
        return redirect(url_for('payments.success', payment_id=payment.id))

    # Verificar estado en dLocal
    dlocal_id = payment.paypal_order_id  # campo reutilizado
    try:
        if dlocal_id:
            data = dlocal.get_payment(dlocal_id)
            status = data.get('status', '').upper()
            if status in ('PAID', 'COMPLETED', 'APPROVED'):
                _complete_dlocal_payment(payment, data)
                db.session.commit()
                flash(f'✅ ¡Pago completado! {payment.credits_granted} créditos añadidos.', 'success')
                return redirect(url_for('payments.success', payment_id=payment.id))
    except Exception as e:
        current_app.logger.error(f'dLocal verify error: {e}')

    # Pago pendiente — mostrar página de espera
    flash('Tu pago está siendo procesado. En unos minutos verás los créditos en tu cuenta.', 'info')
    return render_template('payments/dlocal_pending.html', payment=payment)


@payments_bp.route('/dlocal/webhook', methods=['POST'])
@csrf.exempt
def dlocal_webhook():
    """
    dLocal llama aquí cuando un pago se completa (notificación asíncrona).
    Es la fuente de verdad — no depende de que el usuario regrese al sitio.
    dLocal reintenta hasta 72h si respondemos algo que no sea 2xx.
    """
    import json as _json

    body = request.get_data()

    # dLocal puede enviar la firma en distintos headers — probamos los tres
    signature = (
        request.headers.get('X-DLocal-Signature') or
        request.headers.get('X-Signature') or
        request.headers.get('Signature') or ''
    )

    current_app.logger.info(
        f'[dLocal Webhook] Recibido: {len(body)} bytes | sig={signature[:30] if signature else "NONE"}'
    )

    if not dlocal.verify_signature(body, signature):
        current_app.logger.warning('[dLocal Webhook] Firma inválida — rechazado')
        return jsonify({'ok': False, 'error': 'invalid_signature'}), 400

    try:
        event = _json.loads(body) if body else {}
    except Exception:
        current_app.logger.error('[dLocal Webhook] Body no es JSON válido')
        return jsonify({'ok': False, 'error': 'invalid_json'}), 400

    current_app.logger.info(f'[dLocal Webhook] Evento: {_json.dumps(event)[:500]}')

    status = event.get('status', '').upper()

    # Solo procesamos pagos confirmados; dLocal usa distintos nombres
    ESTADOS_OK = {'PAID', 'COMPLETED', 'APPROVED', 'SUCCESS', 'CONFIRMED'}
    if status not in ESTADOS_OK:
        current_app.logger.info(f'[dLocal Webhook] Estado ignorado: {status}')
        return jsonify({'ok': True, 'skipped': status})

    try:
        # Buscar pago por múltiples campos que puede enviar dLocal
        dlocal_id   = event.get('id') or event.get('payment_id') or ''
        external_id = event.get('external_id') or event.get('order_id') or ''

        payment = None
        if dlocal_id:
            payment = Payment.query.filter_by(paypal_order_id=str(dlocal_id)).first()
        if not payment and external_id and str(external_id).isdigit():
            payment = Payment.query.get(int(external_id))

        if not payment:
            current_app.logger.warning(
                f'[dLocal Webhook] Pago no encontrado — dlocal_id={dlocal_id} external={external_id}'
            )
            # Devolvemos 200 para que dLocal no reintente indefinidamente
            return jsonify({'ok': True, 'msg': 'pago_no_encontrado'})

        if payment.status == 'completed':
            current_app.logger.info(f'[dLocal Webhook] Pago #{payment.id} ya estaba completado — ok')
            return jsonify({'ok': True, 'msg': 'ya_procesado'})

        _complete_dlocal_payment(payment, event)
        db.session.commit()

        try:
            email_service.send_purchase_confirmation(payment.user, payment)
        except Exception as mail_err:
            current_app.logger.warning(f'[dLocal Webhook] Error enviando email: {mail_err}')

        current_app.logger.info(
            f'[dLocal Webhook] ✅ Pago #{payment.id} completado — '
            f'${payment.amount} USD — {payment.credits_granted} créditos → {payment.user.email}'
        )

    except Exception as e:
        import traceback
        current_app.logger.error(f'[dLocal Webhook] Error procesando: {e}\n{traceback.format_exc()}')
        db.session.rollback()
        # 500 → dLocal reintentará (correcto para errores reales del servidor)
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({'ok': True})


def _complete_dlocal_payment(payment: Payment, data: dict):
    """Marca el pago como completado y otorga créditos / activa plan."""
    payment.status = 'completed'
    payment.paypal_capture_id = data.get('id', '') or payment.paypal_order_id
    payment.paypal_payer_email = (
        data.get('payer', {}).get('email') or
        data.get('payer_email') or ''
    )
    payment.completed_at = datetime.now(timezone.utc)

    user = payment.user
    credit_service.grant_credits(
        user, payment.credits_granted,
        payment.description,
        reference=f'payment:{payment.id}'
    )

    if payment.plan_id:
        months = 12 if payment.type == 'plan_annual' else 1
        expires = datetime.now(timezone.utc) + timedelta(days=30 * months)
        existing = Subscription.query.filter_by(
            user_id=user.id, plan_id=payment.plan_id, status='active'
        ).first()
        if not existing:
            db.session.add(Subscription(
                user_id=user.id,
                plan_id=payment.plan_id,
                billing_cycle=payment.type.replace('plan_', ''),
                status='active',
                expires_at=expires,
            ))

    if payment.coupon_id:
        coupon = Coupon.query.get(payment.coupon_id)
        if coupon:
            coupon.times_used += 1


# ═══════════════════════════════════════════════════════════════════════════
# ─── Venta de código fuente y bots individuales ──────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

BOTS_VENTA = {
    'horoscopo':   {'name': 'Horóscopo Bot',      'price': 1200.0},
    'motivacion':  {'name': 'Motivación Bot',      'price': 1000.0},
    'cristiano':   {'name': 'Cristiano Bot',       'price': 1200.0},
    'noticias':    {'name': 'Noticias RD Bot',     'price': 1500.0},
    'music_video': {'name': 'Music Video Bot',     'price': 1800.0},
    'vehiculos':   {'name': 'Vehículos Bot',       'price': 1400.0},
    'distrokid':   {'name': 'DistroKid Bot',       'price': 2000.0},
    'avatar':      {'name': 'Avatar Livestream',   'price': 2500.0},
}

CODIGO_FUENTE = {'name': 'Código Fuente Cronos AI (sistema completo)', 'price': 3800.0}


def _crear_pago_especial(nombre, precio, tipo, via):
    """Crea un pago único para bot o código fuente y redirige al procesador."""
    from flask_login import current_user as cu
    if not cu.is_authenticated:
        from flask import url_for as uf
        return redirect(uf('auth.login') + f'?next=/pagar')

    payment = Payment(
        user_id=cu.id,
        amount=precio,
        type=tipo,
        credits_granted=0,
        description=nombre,
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()

    app_url = current_app.config['APP_URL']
    if via == 'paypal':
        try:
            order_data = paypal.create_order(
                amount=precio,
                description=nombre,
                return_url=f'{app_url}/payments/special/capture?pid={payment.id}',
                cancel_url=f'{app_url}/payments/cancel',
            )
            payment.paypal_order_id = order_data['order_id']
            db.session.commit()
            return redirect(order_data['approve_url'])
        except Exception as e:
            current_app.logger.error(f'PayPal especial error: {e}')
            payment.status = 'failed'
            db.session.commit()
            flash('Error al conectar con PayPal. Intenta con dLocal.', 'danger')
            return redirect('/pagar')
    else:  # dlocal
        try:
            result = dlocal.create_payment(
                amount=precio,
                currency='USD',
                description=nombre,
                success_url=f'{app_url}/payments/dlocal/success?payment_id={payment.id}',
                back_url=f'{app_url}/payments/cancel',
                notification_url=f'{app_url}/payments/dlocal/webhook',
                order_id=str(payment.id),
            )
            payment.paypal_order_id = result['payment_id']
            db.session.commit()
            return redirect(result['redirect_url'])
        except Exception as e:
            current_app.logger.error(f'dLocal especial error: {e}')
            payment.status = 'failed'
            db.session.commit()
            flash('Error al conectar con dLocal. Intenta con PayPal.', 'danger')
            return redirect('/pagar')


@payments_bp.route('/buy-bot/<slug>/<via>')
@login_required
def buy_bot(slug, via):
    if slug not in BOTS_VENTA or via not in ('paypal', 'dlocal'):
        abort(404)
    bot = BOTS_VENTA[slug]
    return _crear_pago_especial(f'{bot["name"]} — código fuente', bot['price'], f'bot_{slug}', via)


@payments_bp.route('/buy-source/<via>')
@login_required
def buy_source(via):
    if via not in ('paypal', 'dlocal'):
        abort(404)
    return _crear_pago_especial(CODIGO_FUENTE['name'], CODIGO_FUENTE['price'], 'codigo_fuente', via)


@payments_bp.route('/special/capture')
@login_required
def special_capture():
    """Captura el pago PayPal para bot/código fuente."""
    order_id = request.args.get('token')
    pid = request.args.get('pid', type=int)
    if not order_id or not pid:
        flash('Pago cancelado.', 'warning')
        return redirect('/pagar')

    payment = Payment.query.filter_by(paypal_order_id=order_id, id=pid,
                                       user_id=current_user.id, status='pending').first()
    if not payment:
        flash('Pago no encontrado.', 'danger')
        return redirect('/pagar')

    try:
        result = paypal.capture_order(order_id)
        cap = result.get('capture', {})
        if result.get('order_status') == 'COMPLETED' and cap.get('status') == 'COMPLETED':
            payment.status = 'completed'
            payment.paypal_capture_id = cap.get('capture_id')
            payment.paypal_payer_email = cap.get('payer_email')
            payment.completed_at = datetime.now(timezone.utc)
            db.session.commit()
            email_service.send_purchase_confirmation(current_user, payment)
            flash(f'✅ ¡Pago de ${payment.amount:.2f} USD completado! Recibirás acceso por email en breve.', 'success')
            return redirect(url_for('payments.success', payment_id=payment.id))
        else:
            payment.status = 'failed'
            db.session.commit()
            flash('El pago no pudo ser procesado.', 'danger')
    except Exception as e:
        current_app.logger.error(f'PayPal special capture error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al procesar el pago.', 'danger')

    return redirect('/pagar')


# ═══════════════════════════════════════════════════════════════════════════
# ─── Stripe — Pago con tarjeta internacional ─────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

def _stripe_checkout(payment: Payment, description: str, precio: float,
                     success_path: str, cancel_path: str):
    """Crea sesión Stripe y redirige al checkout."""
    app_url = current_app.config['APP_URL']
    try:
        sess = stripe_svc.create_checkout_session(
            amount=precio,
            description=description,
            success_url=f'{app_url}{success_path}?session_id={{CHECKOUT_SESSION_ID}}&pid={payment.id}',
            cancel_url=f'{app_url}{cancel_path}',
            metadata={'payment_id': str(payment.id)},
        )
        payment.paypal_order_id = sess['session_id']
        db.session.commit()
        return redirect(sess['checkout_url'])
    except Exception as e:
        current_app.logger.error(f'Stripe checkout error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al conectar con Stripe. Intenta con otro método.', 'danger')
        return redirect(url_for('payments.plans'))


@payments_bp.route('/stripe/buy-credits/<pack_id>', methods=['POST'])
@login_required
def stripe_buy_credits(pack_id):
    pack = next((p for p in CREDIT_PACKS if p['id'] == pack_id), None)
    if not pack:
        abort(404)
    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    final_price = pack['price']
    discount = 0.0
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(pack['price'])
            discount = round(pack['price'] - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))
    payment = Payment(
        user_id=current_user.id, amount=final_price, type='credit_pack',
        credits_granted=pack['credits'], coupon_id=coupon.id if coupon else None,
        discount_amount=discount, description=f'{pack["credits"]} créditos ({pack["label"]})',
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _stripe_checkout(payment, payment.description, final_price,
                            '/payments/stripe/success', '/payments/cancel')


@payments_bp.route('/stripe/buy-plan/<int:plan_id>/<billing>', methods=['POST'])
@login_required
def stripe_buy_plan(plan_id, billing):
    if billing not in ('monthly', 'annual'):
        abort(400)
    plan = Plan.query.get_or_404(plan_id)
    price = plan.price_annual if billing == 'annual' else plan.price_monthly
    coupon_code = request.form.get('coupon', '').strip().upper()
    coupon = None
    final_price = price
    discount = 0.0
    if coupon_code:
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if coupon and coupon.is_valid():
            final_price = coupon.apply(price)
            discount = round(price - final_price, 2)
        else:
            flash('Cupón inválido o expirado.', 'warning')
            return redirect(url_for('payments.plans'))
    label = f'Plan {plan.name} - {"Anual" if billing == "annual" else "Mensual"}'
    payment = Payment(
        user_id=current_user.id, amount=final_price, type=f'plan_{billing}',
        credits_granted=plan.credits_monthly, plan_id=plan.id,
        coupon_id=coupon.id if coupon else None, discount_amount=discount,
        description=label, status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _stripe_checkout(payment, label, final_price,
                            '/payments/stripe/success', '/payments/cancel')


@payments_bp.route('/stripe/buy-bot/<slug>')
@login_required
def stripe_buy_bot(slug):
    if slug not in BOTS_VENTA:
        abort(404)
    bot = BOTS_VENTA[slug]
    payment = Payment(
        user_id=current_user.id, amount=bot['price'], type=f'bot_{slug}',
        credits_granted=0, description=f'{bot["name"]} — código fuente',
        status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _stripe_checkout(payment, payment.description, bot['price'],
                            '/payments/stripe/success', '/pagar')


@payments_bp.route('/stripe/buy-source')
@login_required
def stripe_buy_source():
    payment = Payment(
        user_id=current_user.id, amount=CODIGO_FUENTE['price'], type='codigo_fuente',
        credits_granted=0, description=CODIGO_FUENTE['name'], status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _stripe_checkout(payment, payment.description, CODIGO_FUENTE['price'],
                            '/payments/stripe/success', '/pagar')


@payments_bp.route('/stripe/success')
@login_required
def stripe_success():
    session_id = request.args.get('session_id', '')
    pid = request.args.get('pid', type=int)
    if not session_id or not pid:
        flash('Parámetros inválidos.', 'warning')
        return redirect(url_for('payments.plans'))

    payment = Payment.query.filter_by(id=pid, user_id=current_user.id).first()
    if not payment:
        flash('Pago no encontrado.', 'danger')
        return redirect(url_for('payments.plans'))

    if payment.status == 'completed':
        flash(f'✅ ¡Pago ya procesado!', 'success')
        return redirect(url_for('payments.success', payment_id=payment.id))

    try:
        sess = stripe_svc.retrieve_session(session_id)
        if sess.get('payment_status') == 'paid':
            payment.status = 'completed'
            payment.paypal_capture_id = sess.get('payment_intent', '')
            payment.paypal_payer_email = sess.get('customer_details', {}).get('email', '')
            payment.completed_at = datetime.now(timezone.utc)
            if payment.credits_granted:
                credit_service.grant_credits(
                    current_user, payment.credits_granted,
                    payment.description, reference=f'payment:{payment.id}'
                )
            if payment.plan_id:
                months = 12 if payment.type == 'plan_annual' else 1
                expires = datetime.now(timezone.utc) + timedelta(days=30 * months)
                existing = Subscription.query.filter_by(
                    user_id=current_user.id, plan_id=payment.plan_id, status='active'
                ).first()
                if not existing:
                    db.session.add(Subscription(
                        user_id=current_user.id, plan_id=payment.plan_id,
                        billing_cycle=payment.type.replace('plan_', ''),
                        status='active', expires_at=expires,
                    ))
            db.session.commit()
            email_service.send_purchase_confirmation(current_user, payment)
            msg = (f'✅ ¡Pago completado! {payment.credits_granted} créditos añadidos.'
                   if payment.credits_granted else
                   f'✅ ¡Pago de ${payment.amount:.2f} USD completado! Recibirás acceso por email.')
            flash(msg, 'success')
            return redirect(url_for('payments.success', payment_id=payment.id))
        else:
            flash('El pago está siendo procesado. Espera unos minutos.', 'info')
    except Exception as e:
        current_app.logger.error(f'Stripe success error: {e}')
        flash('Error verificando el pago. Contacta soporte.', 'danger')

    return redirect(url_for('payments.plans'))


@payments_bp.route('/stripe/webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature', '')
    try:
        event = stripe_svc.verify_webhook(payload, sig)
    except Exception as e:
        current_app.logger.error(f'[Stripe Webhook] Error: {e}')
        return jsonify({'ok': False}), 400

    if event.get('type') != 'checkout.session.completed':
        return jsonify({'ok': True, 'skipped': event.get('type')})

    sess = event.get('data', {}).get('object', {})
    pid = sess.get('metadata', {}).get('payment_id')
    if not pid:
        return jsonify({'ok': True, 'msg': 'sin payment_id'})

    try:
        payment = Payment.query.get(int(pid))
        if not payment or payment.status == 'completed':
            return jsonify({'ok': True, 'msg': 'ya procesado'})
        payment.status = 'completed'
        payment.paypal_capture_id = sess.get('payment_intent', '')
        payment.paypal_payer_email = sess.get('customer_details', {}).get('email', '')
        payment.completed_at = datetime.now(timezone.utc)
        if payment.credits_granted:
            credit_service.grant_credits(
                payment.user, payment.credits_granted,
                payment.description, reference=f'payment:{payment.id}'
            )
        db.session.commit()
        current_app.logger.info(f'[Stripe Webhook] ✅ Pago #{payment.id} completado')
    except Exception as e:
        current_app.logger.error(f'[Stripe Webhook] Error: {e}')
        db.session.rollback()
        return jsonify({'ok': False}), 500

    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════════════════
# ─── Lemon Squeezy — Pago global con tarjeta ─────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════

# Mapa: pack_id / plan_slug / bot_slug → variant_id de Lemon Squeezy
# Se configura en Railway como variable o aquí directamente tras crear los productos
LS_VARIANTS = {
    'pack_50':        '',   # Pack Básico $4.99
    'pack_150':       '',   # Pack Creator $12.99
    'pack_500':       '',   # Pack Agency $34.99
    'horoscopo':      '',
    'motivacion':     '',
    'cristiano':      '',
    'noticias':       '',
    'music_video':    '',
    'vehiculos':      '',
    'distrokid':      '',
    'avatar':         '',
    'codigo_fuente':  '',
}


def _ls_variant(key: str) -> str:
    """Obtiene el variant_id desde config de Railway o el dict local."""
    env_key = f'LS_VARIANT_{key.upper()}'
    return current_app.config.get(env_key, '') or LS_VARIANTS.get(key, '')


def _ls_checkout(payment: Payment, description: str, key: str):
    """Crea checkout Lemon Squeezy y redirige."""
    app_url = current_app.config['APP_URL']
    variant_id = _ls_variant(key)
    if not variant_id:
        flash('Producto no configurado aún. Usa PayPal por ahora.', 'warning')
        return redirect(url_for('payments.plans'))
    try:
        result = lemonsqueezy.create_checkout(
            variant_id=variant_id,
            amount_override=payment.amount,
            description=description,
            success_url=f'{app_url}/payments/ls/success?pid={payment.id}',
            custom_data={'payment_id': str(payment.id)},
        )
        payment.paypal_order_id = result['checkout_id']
        db.session.commit()
        return redirect(result['checkout_url'])
    except Exception as e:
        current_app.logger.error(f'LemonSqueezy checkout error: {e}')
        payment.status = 'failed'
        db.session.commit()
        flash('Error al crear el checkout. Intenta con PayPal.', 'danger')
        return redirect(url_for('payments.plans'))


@payments_bp.route('/ls/buy-credits/<pack_id>', methods=['POST'])
@login_required
def ls_buy_credits(pack_id):
    pack = next((p for p in CREDIT_PACKS if p['id'] == pack_id), None)
    if not pack:
        abort(404)
    payment = Payment(
        user_id=current_user.id, amount=pack['price'], type='credit_pack',
        credits_granted=pack['credits'],
        description=f'{pack["credits"]} créditos ({pack["label"]})', status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _ls_checkout(payment, payment.description, pack_id)


@payments_bp.route('/ls/buy-plan/<int:plan_id>/<billing>', methods=['POST'])
@login_required
def ls_buy_plan(plan_id, billing):
    if billing not in ('monthly', 'annual'):
        abort(400)
    plan = Plan.query.get_or_404(plan_id)
    price = plan.price_annual if billing == 'annual' else plan.price_monthly
    label = f'Plan {plan.name} - {"Anual" if billing == "annual" else "Mensual"}'
    payment = Payment(
        user_id=current_user.id, amount=price, type=f'plan_{billing}',
        credits_granted=plan.credits_monthly, plan_id=plan.id,
        description=label, status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _ls_checkout(payment, label, f'plan_{plan.slug}_{billing}')


@payments_bp.route('/ls/buy-bot/<slug>')
@login_required
def ls_buy_bot(slug):
    if slug not in BOTS_VENTA:
        abort(404)
    bot = BOTS_VENTA[slug]
    payment = Payment(
        user_id=current_user.id, amount=bot['price'], type=f'bot_{slug}',
        credits_granted=0, description=f'{bot["name"]} — código fuente', status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _ls_checkout(payment, payment.description, slug)


@payments_bp.route('/ls/buy-source')
@login_required
def ls_buy_source():
    payment = Payment(
        user_id=current_user.id, amount=CODIGO_FUENTE['price'], type='codigo_fuente',
        credits_granted=0, description=CODIGO_FUENTE['name'], status='pending',
    )
    payment.generate_invoice_number()
    db.session.add(payment)
    db.session.commit()
    return _ls_checkout(payment, payment.description, 'codigo_fuente')


@payments_bp.route('/ls/success')
@login_required
def ls_success():
    pid = request.args.get('pid', type=int)
    if not pid:
        return redirect(url_for('payments.plans'))
    payment = Payment.query.filter_by(id=pid, user_id=current_user.id).first()
    if not payment:
        flash('Pago no encontrado.', 'danger')
        return redirect(url_for('payments.plans'))
    if payment.status == 'completed':
        flash('✅ ¡Pago ya procesado!', 'success')
        return redirect(url_for('payments.success', payment_id=payment.id))
    # El webhook confirmará el pago; mostramos pantalla de espera
    flash('✅ ¡Gracias! Tu pago está siendo confirmado. Los créditos aparecerán en segundos.', 'success')
    return redirect(url_for('payments.success', payment_id=payment.id))


@payments_bp.route('/ls/webhook', methods=['POST'])
@csrf.exempt
def ls_webhook():
    payload = request.get_data()
    sig = request.headers.get('X-Signature', '')
    if not lemonsqueezy.verify_webhook(payload, sig):
        current_app.logger.warning('[LS Webhook] Firma inválida')
        return jsonify({'ok': False}), 400

    import json as _json
    try:
        event = _json.loads(payload)
    except Exception:
        return jsonify({'ok': False}), 400

    event_name = event.get('meta', {}).get('event_name', '')
    if event_name != 'order_created':
        return jsonify({'ok': True, 'skipped': event_name})

    try:
        custom = event.get('meta', {}).get('custom_data', {})
        pid = custom.get('payment_id')
        if not pid:
            return jsonify({'ok': True, 'msg': 'sin payment_id'})

        payment = Payment.query.get(int(pid))
        if not payment or payment.status == 'completed':
            return jsonify({'ok': True, 'msg': 'ya procesado'})

        data = event.get('data', {}).get('attributes', {})
        payment.status = 'completed'
        payment.paypal_payer_email = data.get('user_email', '')
        payment.completed_at = datetime.now(timezone.utc)

        if payment.credits_granted:
            credit_service.grant_credits(
                payment.user, payment.credits_granted,
                payment.description, reference=f'payment:{payment.id}'
            )
        db.session.commit()
        current_app.logger.info(f'[LS Webhook] ✅ Pago #{payment.id} completado')
    except Exception as e:
        current_app.logger.error(f'[LS Webhook] Error: {e}')
        db.session.rollback()
        return jsonify({'ok': False}), 500

    return jsonify({'ok': True})


# ═══════════════════════════════════════════════════════════════════════════

@payments_bp.route('/validate-coupon', methods=['POST'])
@login_required
def validate_coupon():
    code = request.json.get('code', '').strip().upper()
    coupon = Coupon.query.filter_by(code=code).first()
    if coupon and coupon.is_valid():
        return jsonify({
            'valid': True,
            'type': coupon.discount_type,
            'value': coupon.discount_value,
            'description': coupon.description,
        })
    return jsonify({'valid': False})
