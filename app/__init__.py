# -*- coding: utf-8 -*-
import os
from flask import Flask, render_template
from app.config import config
from app.extensions import db, login_manager, mail, csrf, limiter


def create_app(config_name: str = None) -> Flask:
    config_name = config_name or os.environ.get('FLASK_ENV', 'default')
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Extensiones
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Login loader
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Blueprints
    from app.auth import auth_bp
    from app.dashboard import dashboard_bp
    from app.admin import admin_bp
    from app.payments import payments_bp
    from app.api import api_bp
    from app.public import public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(public_bp)

    # Ruta raíz
    @app.route('/')
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            from flask import redirect, url_for
            return redirect(url_for('dashboard.index'))
        return render_template('index.html',
                               app_name=app.config['APP_NAME'])

    # Manejadores de error
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    # Filtros Jinja2 útiles
    @app.template_filter('fecha')
    def fecha_filter(dt):
        if not dt:
            return '—'
        if hasattr(dt, 'strftime'):
            return dt.strftime('%d/%m/%Y %H:%M')
        return str(dt)

    @app.template_filter('moneda')
    def moneda_filter(value):
        try:
            return f'${float(value):.2f}'
        except (TypeError, ValueError):
            return '$0.00'

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        unread = 0
        if current_user.is_authenticated:
            from app.models.notification import Notification
            unread = current_user.notifications.filter_by(is_read=False).count()
        return {
            'app_name': app.config['APP_NAME'],
            'unread_notifications': unread,
        }

    # Al arrancar: marcar jobs huérfanos como fallidos
    with app.app_context():
        try:
            from datetime import datetime, timezone
            from app.models.job import Job
            stuck = Job.query.filter_by(status='running').all()
            for j in stuck:
                j.status = 'failed'
                j.error_message = 'El servidor se reinició mientras el trabajo estaba en progreso. Vuelve a ejecutarlo.'
                j.completed_at = datetime.now(timezone.utc)
            if stuck:
                db.session.commit()
        except Exception:
            pass

    # Scheduler automático de bots
    if not app.config.get('TESTING') and os.environ.get('WERKZEUG_RUN_MAIN') != 'false':
        try:
            from app.services.scheduler import start_scheduler
            start_scheduler(app)
        except Exception as e:
            app.logger.warning(f'Scheduler no iniciado: {e}')

    return app
