# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from flask_login import UserMixin
import bcrypt
from app.extensions import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # 'user' | 'admin'
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    credits = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime)
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)

    # Relaciones
    subscriptions = db.relationship('Subscription', backref='user', lazy='dynamic')
    credit_transactions = db.relationship('CreditTransaction', backref='user', lazy='dynamic')
    payments = db.relationship('Payment', backref='user', lazy='dynamic')
    jobs = db.relationship('Job', backref='user', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    def is_admin(self) -> bool:
        return self.role == 'admin'

    def is_locked(self) -> bool:
        if self.locked_until and datetime.now(timezone.utc) < self.locked_until.replace(tzinfo=timezone.utc):
            return True
        return False

    def add_credits(self, amount: int, description: str, reference: str = None):
        from app.models.credit_transaction import CreditTransaction
        self.credits += amount
        tx = CreditTransaction(
            user_id=self.id,
            amount=amount,
            type='credit',
            description=description,
            reference=reference,
            balance_after=self.credits
        )
        db.session.add(tx)

    def consume_credits(self, amount: int, description: str, reference: str = None) -> bool:
        from app.models.credit_transaction import CreditTransaction
        if self.credits < amount:
            return False
        self.credits -= amount
        tx = CreditTransaction(
            user_id=self.id,
            amount=amount,
            type='debit',
            description=description,
            reference=reference,
            balance_after=self.credits
        )
        db.session.add(tx)
        return True

    @property
    def active_subscription(self):
        now = datetime.now(timezone.utc)
        return self.subscriptions.filter(
            db.text("expires_at > :now AND status = 'active'")
        ).params(now=now).first()

    def __repr__(self):
        return f'<User {self.email}>'
