# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class NicheProfile(db.Model):
    """Perfil del canal/nicho del usuario — la IA lo usa para entender su contexto."""
    __tablename__ = 'niche_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)

    # Información del canal
    channel_name = db.Column(db.String(200))
    channel_url = db.Column(db.String(300))
    niche = db.Column(db.String(200))           # ej: "horóscopo", "motivación", "noticias RD"
    audience = db.Column(db.String(200))        # ej: "mujeres 25-45 hispanohablantes"
    style = db.Column(db.String(200))           # ej: "profesional y espiritual"
    language = db.Column(db.String(20), default='es')
    country = db.Column(db.String(100), default='República Dominicana')

    # Contexto adicional que el usuario escribe libremente
    description = db.Column(db.Text)

    # YouTube OAuth tokens (por usuario)
    youtube_access_token = db.Column(db.Text)
    youtube_refresh_token = db.Column(db.Text)
    youtube_token_expiry = db.Column(db.DateTime)
    youtube_channel_id = db.Column(db.String(100))
    youtube_channel_name = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_context_string(self) -> str:
        """Genera un resumen para que la IA entienda el contexto del usuario."""
        parts = []
        if self.channel_name:
            parts.append(f"Canal: {self.channel_name}")
        if self.niche:
            parts.append(f"Nicho: {self.niche}")
        if self.audience:
            parts.append(f"Audiencia: {self.audience}")
        if self.style:
            parts.append(f"Estilo: {self.style}")
        if self.language:
            parts.append(f"Idioma: {self.language}")
        if self.country:
            parts.append(f"País/región: {self.country}")
        if self.description:
            parts.append(f"Descripción: {self.description}")
        return " | ".join(parts) if parts else "Perfil no configurado"

    def has_youtube(self) -> bool:
        return bool(self.youtube_refresh_token)

    def __repr__(self):
        return f'<NicheProfile user={self.user_id} niche={self.niche}>'


class Conversation(db.Model):
    """Historial de mensajes entre el usuario y el orquestador IA."""
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)   # 'user' | 'assistant'
    content = db.Column(db.Text, nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'))  # si generó un job
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f'<Conversation {self.role} user={self.user_id}>'
