# -*- coding: utf-8 -*-
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'cronos-dev-key-insegura')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{BASE_DIR}/cronos.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True}

    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'Cronos AI <noreply@cronos.ai>')

    # PayPal
    PAYPAL_CLIENT_ID = os.environ.get('PAYPAL_CLIENT_ID', '')
    PAYPAL_CLIENT_SECRET = os.environ.get('PAYPAL_CLIENT_SECRET', '')
    PAYPAL_MODE = os.environ.get('PAYPAL_MODE', 'sandbox')
    PAYPAL_WEBHOOK_ID = os.environ.get('PAYPAL_WEBHOOK_ID', '')

    # dLocal Go — pagos internacionales con métodos locales
    DLOCAL_API_KEY    = os.environ.get('DLOCAL_API_KEY', '')
    DLOCAL_SECRET_KEY = os.environ.get('DLOCAL_SECRET_KEY', '')

    # Lemon Squeezy
    LEMONSQUEEZY_API_KEY       = os.environ.get('LEMONSQUEEZY_API_KEY', '')
    LEMONSQUEEZY_STORE_ID      = os.environ.get('LEMONSQUEEZY_STORE_ID', '')
    LEMONSQUEEZY_WEBHOOK_SECRET = os.environ.get('LEMONSQUEEZY_WEBHOOK_SECRET', '')
    LS_VARIANT_PACK_50         = os.environ.get('LS_VARIANT_PACK_50', '')
    LS_VARIANT_PACK_150        = os.environ.get('LS_VARIANT_PACK_150', '')
    LS_VARIANT_PACK_500        = os.environ.get('LS_VARIANT_PACK_500', '')
    LS_VARIANT_HOROSCOPO       = os.environ.get('LS_VARIANT_HOROSCOPO', '')
    LS_VARIANT_MOTIVACION      = os.environ.get('LS_VARIANT_MOTIVACION', '')
    LS_VARIANT_CRISTIANO       = os.environ.get('LS_VARIANT_CRISTIANO', '')
    LS_VARIANT_NOTICIAS        = os.environ.get('LS_VARIANT_NOTICIAS', '')
    LS_VARIANT_MUSIC_VIDEO     = os.environ.get('LS_VARIANT_MUSIC_VIDEO', '')
    LS_VARIANT_VEHICULOS       = os.environ.get('LS_VARIANT_VEHICULOS', '')
    LS_VARIANT_DISTROKID       = os.environ.get('LS_VARIANT_DISTROKID', '')
    LS_VARIANT_AVATAR          = os.environ.get('LS_VARIANT_AVATAR', '')
    LS_VARIANT_CODIGO_FUENTE   = os.environ.get('LS_VARIANT_CODIGO_FUENTE', '')

    # App — Railway detecta RAILWAY_PUBLIC_DOMAIN automáticamente
    APP_NAME = os.environ.get('APP_NAME', 'Cronos AI')
    _railway_domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    APP_URL = (
        os.environ.get('APP_URL') or
        (f'https://{_railway_domain}' if _railway_domain else None) or
        'http://localhost:5000'
    )
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@cronos.ai')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'Admin123!')

    # Bots
    BOTS_DIR = Path(os.environ.get('BOTS_DIR', str(BASE_DIR.parent)))

    # IA Orquestador
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

    # YouTube OAuth (Google Cloud Console)
    YOUTUBE_CLIENT_ID = os.environ.get('YOUTUBE_CLIENT_ID', '')
    YOUTUBE_CLIENT_SECRET = os.environ.get('YOUTUBE_CLIENT_SECRET', '')
    YOUTUBE_REDIRECT_URI = os.environ.get('YOUTUBE_REDIRECT_URI', 'http://localhost:5000/dashboard/youtube/callback')

    # Seguridad
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    RATELIMIT_DEFAULT = '200 per day;50 per hour;10 per minute'
    RATELIMIT_STORAGE_URL = 'memory://'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Tokens de expiración (segundos)
    EMAIL_VERIFY_EXPIRY = 86400       # 24h
    PASSWORD_RESET_EXPIRY = 3600      # 1h

    # Créditos de bienvenida
    WELCOME_CREDITS = 10


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
