# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from app.extensions import db


class UserBotConfig(db.Model):
    __tablename__ = 'user_bot_configs'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    bot_slug   = db.Column(db.String(50), nullable=False)
    slot       = db.Column(db.Integer, nullable=False, default=1)  # 1-4 instancias por bot

    # Credenciales de este slot
    yt_email   = db.Column(db.String(200), default='')
    yt_canal   = db.Column(db.String(200), default='')
    fb_url     = db.Column(db.String(300), default='')

    # Configuración del canal (JSON)
    _config    = db.Column('config', db.Text, default='{}')

    # Configuración de automatización (JSON)
    _auto      = db.Column('auto_config', db.Text, default='{}')

    # Ruta al workspace en disco
    workspace  = db.Column(db.String(500), default='')

    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('bot_configs', lazy='dynamic',
                                                       cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'bot_slug', 'slot', name='uq_user_bot_slug_slot'),
    )

    # ── JSON helpers ──────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        try:
            return json.loads(self._config or '{}')
        except Exception:
            return {}

    def set_config(self, d: dict):
        self._config = json.dumps(d, ensure_ascii=False)

    def get_auto(self) -> dict:
        defaults = {
            'activo': False, 'videos_por_dia': 3,
            'hora_inicio': '08:00', 'intervalo_horas': 4,
            'dias': ['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom'],
        }
        try:
            stored = json.loads(self._auto or '{}')
            defaults.update(stored)
            return defaults
        except Exception:
            return defaults

    def set_auto(self, d: dict):
        self._auto = json.dumps(d, ensure_ascii=False)

    @property
    def fb_configured(self) -> bool:
        return bool(self.fb_url and self.fb_url.strip())

    @property
    def yt_configured(self) -> bool:
        return bool(self.yt_email and self.yt_email.strip())

    # ── Clase factory ────────────────────────────────────────────────────────

    @classmethod
    def get_or_create(cls, user_id: int, bot_slug: str, slot: int = 1):
        obj = cls.query.filter_by(user_id=user_id, bot_slug=bot_slug, slot=slot).first()
        if not obj:
            obj = cls(user_id=user_id, bot_slug=bot_slug, slot=slot)
            db.session.add(obj)
        return obj

    @classmethod
    def get_all_slots(cls, user_id: int, bot_slug: str):
        """Devuelve todos los slots configurados para este usuario+bot."""
        return cls.query.filter_by(user_id=user_id, bot_slug=bot_slug).order_by(cls.slot).all()
