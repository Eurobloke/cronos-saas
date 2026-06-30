# -*- coding: utf-8 -*-
from flask import render_template
from . import public_bp


@public_bp.route('/nosotros')
def about():
    return render_template('public/about.html')


@public_bp.route('/precios')
def pricing():
    from app.models.plan import Plan
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.sort_order).all()
    return render_template('public/pricing.html', plans=plans)


@public_bp.route('/contacto')
def contact():
    return render_template('public/contact.html')


@public_bp.route('/faq')
def faq():
    return render_template('public/faq.html')


@public_bp.route('/privacidad')
def privacy():
    return render_template('public/privacy.html')


@public_bp.route('/terminos')
def terms():
    return render_template('public/terms.html')


@public_bp.route('/reembolsos')
def refunds():
    return render_template('public/refunds.html')


@public_bp.route('/pagar')
def pagar():
    """Link de pagos público — no requiere login."""
    from app.models.plan import Plan
    plans = Plan.query.filter_by(is_active=True).order_by(Plan.sort_order).all()
    return render_template('public/pagar.html', plans=plans)
