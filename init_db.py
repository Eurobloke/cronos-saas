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

        # Admin por defecto — crea o actualiza credenciales
        admin_email = app.config['ADMIN_EMAIL']
        admin_password = app.config['ADMIN_PASSWORD']
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            admin = User(
                email=admin_email,
                username='Administrador',
                role='admin',
                email_verified=True,
                credits=9999,
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.flush()
            print(f'✅ Admin creado: {admin_email}')
        else:
            admin.email = admin_email
            admin.set_password(admin_password)
            admin.credits = 9999
            admin.email_verified = True
            print(f'✅ Admin actualizado: {admin_email}')

        # Planes (precios competitivos — por debajo del mercado)
        planes = [
            Plan(name='Starter', slug='starter', description='Para creadores que empiezan',
                 price_monthly=4.99, price_annual=39.99, credits_monthly=150,
                 sort_order=1, is_active=True,
                 features='["150 créditos/mes","2 GB de almacenamiento","Todos los bots incluidos","50 peticiones de IA/día","1 canal de YouTube","Soporte por email"]'),
            Plan(name='Creator', slug='creator', description='Para creadores profesionales',
                 price_monthly=12.99, price_annual=99.99, credits_monthly=600,
                 sort_order=2, is_active=True, is_popular=True,
                 features='["600 créditos/mes","10 GB de almacenamiento","Todos los bots + prioridad","200 peticiones de IA/día","Hasta 5 canales","Soporte prioritario","Estadísticas avanzadas"]'),
            Plan(name='Agency', slug='agency', description='Para agencias y equipos',
                 price_monthly=29.99, price_annual=239.99, credits_monthly=2500,
                 sort_order=3, is_active=True,
                 features='["2500 créditos/mes","50 GB de almacenamiento","Canales ilimitados","Peticiones de IA ilimitadas","Soporte 24/7 dedicado","API de acceso","Reportes personalizados"]'),
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
