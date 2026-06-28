# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models import User, Plan, Service, Payment, Job, Coupon, CreditTransaction, Notification
from app.services import credit_service

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            abort(403)
        return f(*args, **kwargs)
    return login_required(decorated)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@admin_bp.route('/')
@admin_required
def index():
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    stats = {
        'total_users': User.query.filter_by(role='user').count(),
        'new_users_month': User.query.filter(
            User.role == 'user', User.created_at >= month_start).count(),
        'total_revenue': db.session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed').scalar() or 0,
        'revenue_month': db.session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed', Payment.created_at >= month_start).scalar() or 0,
        'total_jobs': Job.query.count(),
        'jobs_today': Job.query.filter(Job.created_at >= now.replace(hour=0, minute=0, second=0)).count(),
        'credits_sold': db.session.query(func.sum(Payment.credits_granted)).filter(
            Payment.status == 'completed').scalar() or 0,
        'active_users': User.query.filter(
            User.last_login >= now - timedelta(days=30)).count(),
    }

    # Ingresos por mes (últimos 6 meses)
    revenue_chart = []
    for i in range(5, -1, -1):
        d = (now - timedelta(days=30 * i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_d = (d + timedelta(days=32)).replace(day=1)
        rev = db.session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= d,
            Payment.created_at < end_d
        ).scalar() or 0
        revenue_chart.append({'month': d.strftime('%b %Y'), 'revenue': float(rev)})

    # Top servicios
    top_services = db.session.query(
        Service.name, func.count(Job.id).label('count')
    ).join(Job, Job.service_id == Service.id).group_by(Service.id).order_by(
        func.count(Job.id).desc()).limit(5).all()

    recent_payments = Payment.query.filter_by(status='completed').order_by(
        Payment.created_at.desc()).limit(10).all()

    return render_template('admin/index.html',
                           stats=stats,
                           revenue_chart=json.dumps(revenue_chart),
                           top_services=top_services,
                           recent_payments=recent_payments)


# ─── Usuarios ─────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@admin_required
def users():
    q = request.args.get('q', '')
    query = User.query
    if q:
        query = query.filter(
            db.or_(User.email.ilike(f'%{q}%'), User.username.ilike(f'%{q}%'))
        )
    page = request.args.get('page', 1, type=int)
    users_pag = query.order_by(User.created_at.desc()).paginate(page=page, per_page=25)
    return render_template('admin/users.html', users=users_pag, q=q)


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    recent_payments = user.payments.order_by(Payment.created_at.desc()).limit(10).all()
    recent_jobs = user.jobs.order_by(Job.created_at.desc()).limit(10).all()
    return render_template('admin/user_detail.html', user=user,
                           payments=recent_payments, jobs=recent_jobs)


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({'error': 'No puedes desactivarte a ti mismo'}), 400
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'active': user.is_active})


@admin_bp.route('/users/<int:user_id>/add-credits', methods=['POST'])
@admin_required
def add_credits_admin(user_id):
    user = User.query.get_or_404(user_id)
    amount = request.json.get('amount', 0)
    note = request.json.get('note', 'Créditos agregados por administrador')
    if not isinstance(amount, int) or amount <= 0:
        return jsonify({'error': 'Cantidad inválida'}), 400
    credit_service.grant_credits(user, amount, note)
    db.session.commit()
    return jsonify({'credits': user.credits})


@admin_bp.route('/users/<int:user_id>/make-admin', methods=['POST'])
@admin_required
def make_admin(user_id):
    user = User.query.get_or_404(user_id)
    user.role = 'admin' if user.role == 'user' else 'user'
    db.session.commit()
    return jsonify({'role': user.role})


# ─── Planes ───────────────────────────────────────────────────────────────────

@admin_bp.route('/plans')
@admin_required
def plans():
    all_plans = Plan.query.order_by(Plan.sort_order).all()
    return render_template('admin/plans.html', plans=all_plans)


@admin_bp.route('/plans/new', methods=['GET', 'POST'])
@admin_bp.route('/plans/<int:plan_id>/edit', methods=['GET', 'POST'])
@admin_required
def plan_edit(plan_id=None):
    plan = Plan.query.get_or_404(plan_id) if plan_id else Plan()
    if request.method == 'POST':
        plan.name = request.form['name'].strip()
        plan.slug = request.form['slug'].strip().lower()
        plan.description = request.form.get('description', '')
        plan.price_monthly = float(request.form.get('price_monthly', 0))
        plan.price_annual = float(request.form.get('price_annual', 0))
        plan.credits_monthly = int(request.form.get('credits_monthly', 0))
        plan.is_active = 'is_active' in request.form
        plan.is_popular = 'is_popular' in request.form
        plan.sort_order = int(request.form.get('sort_order', 0))
        features = [f.strip() for f in request.form.get('features', '').split('\n') if f.strip()]
        plan.set_features(features)
        if not plan_id:
            db.session.add(plan)
        db.session.commit()
        flash('Plan guardado.', 'success')
        return redirect(url_for('admin.plans'))
    return render_template('admin/plan_edit.html', plan=plan)


@admin_bp.route('/plans/<int:plan_id>/toggle', methods=['POST'])
@admin_required
def toggle_plan(plan_id):
    plan = Plan.query.get_or_404(plan_id)
    plan.is_active = not plan.is_active
    db.session.commit()
    return jsonify({'active': plan.is_active})


# ─── Servicios ────────────────────────────────────────────────────────────────

@admin_bp.route('/services')
@admin_required
def services():
    all_services = Service.query.order_by(Service.sort_order).all()
    return render_template('admin/services.html', services=all_services)


@admin_bp.route('/services/<int:service_id>/edit', methods=['POST'])
@admin_required
def service_edit(service_id):
    service = Service.query.get_or_404(service_id)
    service.credit_cost = int(request.json.get('credit_cost', service.credit_cost))
    service.price_usd = float(request.json.get('price_usd', service.price_usd))
    service.is_active = request.json.get('is_active', service.is_active)
    service.name = request.json.get('name', service.name)
    db.session.commit()
    return jsonify({'ok': True})


# ─── Pagos ────────────────────────────────────────────────────────────────────

@admin_bp.route('/payments')
@admin_required
def payments():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    query = Payment.query
    if status:
        query = query.filter_by(status=status)
    payments_pag = query.order_by(Payment.created_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/payments.html', payments=payments_pag, status=status)


# ─── Cupones ──────────────────────────────────────────────────────────────────

@admin_bp.route('/coupons')
@admin_required
def coupons():
    all_coupons = Coupon.query.order_by(Coupon.created_at.desc()).all()
    return render_template('admin/coupons.html', coupons=all_coupons)


@admin_bp.route('/coupons/new', methods=['POST'])
@admin_required
def coupon_new():
    data = request.json or request.form
    coupon = Coupon(
        code=str(data.get('code', '')).strip().upper(),
        description=data.get('description', ''),
        discount_type=data.get('discount_type', 'percent'),
        discount_value=float(data.get('discount_value', 10)),
        max_uses=int(data['max_uses']) if data.get('max_uses') else None,
    )
    if data.get('valid_until'):
        try:
            coupon.valid_until = datetime.fromisoformat(str(data['valid_until']))
        except ValueError:
            pass
    db.session.add(coupon)
    db.session.commit()
    return jsonify({'ok': True, 'id': coupon.id})


@admin_bp.route('/coupons/<int:coupon_id>/toggle', methods=['POST'])
@admin_required
def toggle_coupon(coupon_id):
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    return jsonify({'active': coupon.is_active})


# ─── Logs / Jobs ──────────────────────────────────────────────────────────────

@admin_bp.route('/jobs')
@admin_required
def jobs():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', '')
    query = Job.query
    if status:
        query = query.filter_by(status=status)
    jobs_pag = query.order_by(Job.created_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/jobs.html', jobs=jobs_pag, status=status)


# ─── API de estadísticas ──────────────────────────────────────────────────────

@admin_bp.route('/api/stats')
@admin_required
def api_stats():
    days = int(request.args.get('days', 30))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    data = []
    for i in range(days, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
        day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        rev = db.session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed',
            Payment.created_at >= day_start,
            Payment.created_at < day_end,
        ).scalar() or 0
        jobs = Job.query.filter(
            Job.created_at >= day_start, Job.created_at < day_end).count()
        data.append({'date': str(day), 'revenue': float(rev), 'jobs': jobs})
    return jsonify(data)
