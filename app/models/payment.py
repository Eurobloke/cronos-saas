# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='USD')
    status = db.Column(db.String(30), default='pending')  # pending|completed|failed|refunded|cancelled
    type = db.Column(db.String(30), nullable=False)        # credit_pack|plan_monthly|plan_annual
    credits_granted = db.Column(db.Integer, default=0)
    plan_id = db.Column(db.Integer, db.ForeignKey('plans.id'))
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupons.id'))
    discount_amount = db.Column(db.Float, default=0.0)

    # PayPal
    paypal_order_id = db.Column(db.String(200), unique=True, index=True)
    paypal_capture_id = db.Column(db.String(200))
    paypal_payer_email = db.Column(db.String(150))

    description = db.Column(db.String(255))
    invoice_number = db.Column(db.String(50), unique=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    completed_at = db.Column(db.DateTime)

    plan = db.relationship('Plan', foreign_keys=[plan_id])
    coupon = db.relationship('Coupon', foreign_keys=[coupon_id])

    def generate_invoice_number(self):
        ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        self.invoice_number = f'INV-{ts}-{self.user_id}'

    def __repr__(self):
        return f'<Payment {self.invoice_number} ${self.amount} {self.status}>'
