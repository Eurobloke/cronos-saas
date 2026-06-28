# -*- coding: utf-8 -*-
"""
Inicializa la base de datos con planes, servicios y usuario admin por defecto.
Ejecutar UNA sola vez: python init_db.py
"""
import sys, os
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

from app import create_app
from app.extensions import db
from app.models import User, Plan, Service, Coupon
from app.models.service import DEFAULT_SERVICES


def _migrate_columns(engine):
    """Agrega columnas nuevas a tablas existentes sin perder datos."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        inspector = sa.inspect(engine)

        # jobs.progress_message
        cols = [c['name'] for c in inspector.get_columns('jobs')]
        if 'progress_message' not in cols:
            conn.execute(sa.text('ALTER TABLE jobs ADD COLUMN progress_message VARCHAR(300)'))
            conn.commit()
            print('✅ Columna jobs.progress_message añadida.')


def init():
    app = create_app()
    with app.app_context():
        db.create_all()
        print('✅ Tablas creadas.')

        # Migración de columnas nuevas (segura, no borra datos)
        _migrate_columns(db.engine)

        # Admin por defecto
        admin_email = app.config['ADMIN_EMAIL']
        if not User.query.filter_by(email=admin_email).first():
            admin = User(
                email=admin_email,
                username='Administrador',
                role='admin',
                email_verified=True,
                credits=9999,
            )
            admin.set_password(app.config['ADMIN_PASSWORD'])
            db.session.add(admin)
            db.session.flush()
            print(f'✅ Admin creado: {admin_email}')
        else:
            print(f'ℹ️  Admin ya existe: {admin_email}')

        # Planes
        planes = [
            Plan(name='Starter', slug='starter', description='Para creadores individuales',
                 price_monthly=9.99, price_annual=89.99, credits_monthly=100,
                 sort_order=1, is_active=True,
                 features='["100 créditos/mes","Acceso a todos los servicios","Soporte por email","1 canal de YouTube"]'),
            Plan(name='Creator', slug='creator', description='Para creadores profesionales',
                 price_monthly=29.99, price_annual=269.99, credits_monthly=350,
                 sort_order=2, is_active=True, is_popular=True,
                 features='["350 créditos/mes","Todos los servicios + prioridad","Soporte prioritario","Hasta 5 canales","Estadísticas avanzadas"]'),
            Plan(name='Agency', slug='agency', description='Para agencias y equipos',
                 price_monthly=79.99, price_annual=719.99, credits_monthly=1200,
                 sort_order=3, is_active=True,
                 features='["1200 créditos/mes","Canales ilimitados","Soporte 24/7 dedicado","API de acceso","Panel de equipo","Reportes personalizados"]'),
        ]
        for plan in planes:
            if not Plan.query.filter_by(slug=plan.slug).first():
                db.session.add(plan)
                print(f'✅ Plan creado: {plan.name}')

        # Servicios
        for svc_data in DEFAULT_SERVICES:
            if not Service.query.filter_by(slug=svc_data['slug']).first():
                svc = Service(**svc_data)
                db.session.add(svc)
                print(f'✅ Servicio creado: {svc_data["name"]}')

        # Cupón de ejemplo
        if not Coupon.query.filter_by(code='BIENVENIDO20').first():
            coupon = Coupon(
                code='BIENVENIDO20',
                description='20% de descuento para nuevos usuarios',
                discount_type='percent',
                discount_value=20,
                max_uses=100,
                is_active=True,
            )
            db.session.add(coupon)
            print('✅ Cupón BIENVENIDO20 creado.')

        db.session.commit()
        print('\n🚀 Base de datos lista. Ejecuta: python run.py')
        print(f'   Admin: {admin_email} / {app.config["ADMIN_PASSWORD"]}')


if __name__ == '__main__':
    init()
