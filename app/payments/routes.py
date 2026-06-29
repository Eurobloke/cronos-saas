# -*- coding: utf-8 -*-
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort
from flask_login import login_required, current_user

from app.extensions import db, csrf
from app.models import Plan, Payment, Subscription, Coupon
from app.services.paypal_service import paypal
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
    return render_template('payments/plans.html', plans=active_plans, packs=CREDIT_PACKS)


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
