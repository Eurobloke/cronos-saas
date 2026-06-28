# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone
from app.extensions import db


class Job(db.Model):
    __tablename__ = 'jobs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    status = db.Column(db.String(30), default='queued')  # queued|running|completed|failed|cancelled
    credits_used = db.Column(db.Integer, default=0)
    input_params = db.Column(db.Text, default='{}')   # JSON con parámetros de entrada
    output_data = db.Column(db.Text)                  # JSON con resultado/rutas de archivos
    error_message = db.Column(db.Text)
    progress = db.Column(db.Integer, default=0)       # 0-100
    progress_message = db.Column(db.String(300))      # mensaje legible del paso actual
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)

    def get_params(self) -> dict:
        try:
            return json.loads(self.input_params or '{}')
        except Exception:
            return {}

    def set_params(self, params: dict):
        self.input_params = json.dumps(params, ensure_ascii=False)

    def get_output(self) -> dict:
        try:
            return json.loads(self.output_data or '{}')
        except Exception:
            return {}

    def set_output(self, data: dict):
        self.output_data = json.dumps(data, ensure_ascii=False)

    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            start = self.started_at.replace(tzinfo=timezone.utc)
            end = self.completed_at.replace(tzinfo=timezone.utc)
            return (end - start).total_seconds()
        return None

    def __repr__(self):
        return f'<Job {self.id} {self.status}>'
