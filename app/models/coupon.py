# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class Coupon(db.Model):
    __tablename__ = 'coupons'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200))
    discount_type = db.Column(db.String(20), default='percent')  # 'percent' | 'fixed'
    discount_value = db.Column(db.Float, nullable=False)
    max_uses = db.Column(db.Integer)           # None = ilimitado
    times_used = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    valid_from = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    valid_until = db.Column(db.DateTime)       # None = sin expiración
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def is_valid(self) -> bool:
        if not self.is_active:
            return False
        now = datetime.now(timezone.utc)
        if self.valid_until and now > self.valid_until.replace(tzinfo=timezone.utc):
            return False
        if self.max_uses and self.times_used >= self.max_uses:
            return False
        return True

    def apply(self, amount: float) -> float:
        if self.discount_type == 'percent':
            return round(amount * (1 - self.discount_value / 100), 2)
        else:
            return max(0.0, round(amount - self.discount_value, 2))

    def __repr__(self):
        return f'<Coupon {self.code}>'
