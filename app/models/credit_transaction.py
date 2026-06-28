# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from app.extensions import db


class CreditTransaction(db.Model):
    __tablename__ = 'credit_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)   # 'credit' | 'debit' | 'refund'
    description = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(200))             # payment_id, job_id, etc.
    balance_after = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f'<CreditTx {self.type} {self.amount} user={self.user_id}>'
