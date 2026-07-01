# -*- coding: utf-8 -*-
"""
Integración con Stripe — pasarela de pago internacional.
Acepta tarjetas de crédito/débito de todo el mundo.
Credenciales: https://dashboard.stripe.com/apikeys
"""
import stripe
from flask import current_app


class StripeService:

    def _configure(self):
        stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY', '')

    def is_configured(self) -> bool:
        return bool(current_app.config.get('STRIPE_SECRET_KEY'))

    def public_key(self) -> str:
        return current_app.config.get('STRIPE_PUBLIC_KEY', '')

    def create_checkout_session(self, amount: float, description: str,
                                 success_url: str, cancel_url: str,
                                 metadata: dict = None) -> dict:
        self._configure()
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(round(amount * 100)),
                    'product_data': {'name': description},
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata or {},
        )
        return {
            'session_id': session.id,
            'checkout_url': session.url,
        }

    def retrieve_session(self, session_id: str) -> dict:
        self._configure()
        return stripe.checkout.Session.retrieve(session_id)

    def verify_webhook(self, payload: bytes, sig_header: str) -> dict:
        self._configure()
        secret = current_app.config.get('STRIPE_WEBHOOK_SECRET', '')
        if not secret:
            import json
            return json.loads(payload)
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        return event


stripe_svc = StripeService()
