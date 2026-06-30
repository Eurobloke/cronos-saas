# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class Plan(db.Model):
    __tablename__ = 'plans'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    price_monthly = db.Column(db.Float, default=0.0)
    price_annual = db.Column(db.Float, default=0.0)
    credits_monthly = db.Column(db.Integer, default=0)
    features = db.Column(db.Text, default='[]')   # JSON list of feature strings
    max_bot_slots = db.Column(db.Integer, default=1)  # cuántas instancias por bot
    is_active = db.Column(db.Boolean, default=True)
    is_popular = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    subscriptions = db.relationship('Subscription', backref='plan', lazy='dynamic')

    def get_features(self):
        import json
        try:
            return json.loads(self.features)
        except Exception:
            return []

    def set_features(self, features_list: list):
        import json
        self.features = json.dumps(features_list, ensure_ascii=False)

    def annual_savings_percent(self) -> int:
        if not self.price_monthly or not self.price_annual:
            return 0
        monthly_total = self.price_monthly * 12
        if monthly_total == 0:
            return 0
        return int((1 - self.price_annual / monthly_total) * 100)

    def __repr__(self):
        return f'<Plan {self.name}>'


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'), nullable=False)
    billing_cycle = db.Column(db.String(20), default='monthly')  # 'monthly' | 'annual'
    status = db.Column(db.String(20), default='active')  # 'active' | 'cancelled' | 'expired'
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    paypal_subscription_id = db.Column(db.String(200))

    def is_active(self) -> bool:
        if self.status != 'active':
            return False
        if self.expires_at:
            return datetime.now(timezone.utc) < self.expires_at.replace(tzinfo=timezone.utc)
        return True

    def __repr__(self):
        return f'<Subscription user={self.user_id} plan={self.plan_id}>'
