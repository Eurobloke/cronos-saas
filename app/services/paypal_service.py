# -*- coding: utf-8 -*-
"""
Integración completa con PayPal REST API v2.
Solo necesitas tu Client ID y Client Secret del panel de PayPal.
"""
import requests
from flask import current_app


class PayPalService:

    def __init__(self):
        self._access_token = None

    def _base_url(self) -> str:
        mode = current_app.config.get('PAYPAL_MODE', 'sandbox')
        if mode == 'live':
            return 'https://api-m.paypal.com'
        return 'https://api-m.sandbox.paypal.com'

    def _get_token(self) -> str:
        url = f'{self._base_url()}/v1/oauth2/token'
        resp = requests.post(
            url,
            data={'grant_type': 'client_credentials'},
            auth=(
                current_app.config['PAYPAL_CLIENT_ID'],
                current_app.config['PAYPAL_CLIENT_SECRET'],
            ),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    def _headers(self) -> dict:
        return {
            'Authorization': f'Bearer {self._get_token()}',
            'Content-Type': 'application/json',
        }

    # ─── Órdenes (pagos únicos: packs de créditos, planes) ───────────────────

    def create_order(self, amount: float, description: str, return_url: str, cancel_url: str) -> dict:
        """Crea una orden de PayPal y devuelve {order_id, approve_url}."""
        payload = {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'amount': {
                    'currency_code': 'USD',
                    'value': f'{amount:.2f}',
                },
                'description': description,
            }],
            'application_context': {
                'brand_name': current_app.config.get('APP_NAME', 'Cronos AI'),
                'return_url': return_url,
                'cancel_url': cancel_url,
                'user_action': 'PAY_NOW',
                'landing_page': 'BILLING',
            },
        }
        resp = requests.post(
            f'{self._base_url()}/v2/checkout/orders',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        approve_url = next(
            (link['href'] for link in data.get('links', []) if link['rel'] == 'approve'),
            None,
        )
        return {'order_id': data['id'], 'approve_url': approve_url}

    def capture_order(self, order_id: str) -> dict:
        """Captura el pago de una orden aprobada. Devuelve los datos de la captura."""
        resp = requests.post(
            f'{self._base_url()}/v2/checkout/orders/{order_id}/capture',
            json={},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        capture = {}
        try:
            unit = data['purchase_units'][0]
            cap = unit['payments']['captures'][0]
            capture = {
                'capture_id': cap['id'],
                'status': cap['status'],
                'amount': float(cap['amount']['value']),
                'currency': cap['amount']['currency_code'],
                'payer_email': data.get('payer', {}).get('email_address', ''),
            }
        except (KeyError, IndexError):
            pass

        return {'order_status': data.get('status'), 'capture': capture}

    def get_order(self, order_id: str) -> dict:
        resp = requests.get(
            f'{self._base_url()}/v2/checkout/orders/{order_id}',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def verify_webhook(self, headers: dict, body: bytes, webhook_id: str) -> bool:
        """Verifica la firma del webhook llamando a la API de PayPal."""
        try:
            payload = {
                'auth_algo':         headers.get('PAYPAL-AUTH-ALGO', ''),
                'cert_url':          headers.get('PAYPAL-CERT-URL', ''),
                'transmission_id':   headers.get('PAYPAL-TRANSMISSION-ID', ''),
                'transmission_sig':  headers.get('PAYPAL-TRANSMISSION-SIG', ''),
                'transmission_time': headers.get('PAYPAL-TRANSMISSION-TIME', ''),
                'webhook_id':        webhook_id,
                'webhook_event':     body.decode('utf-8'),
            }
            resp = requests.post(
                f'{self._base_url()}/v1/notifications/verify-webhook-signature',
                json=payload, headers=self._headers(), timeout=15,
            )
            data = resp.json()
            return data.get('verification_status') == 'SUCCESS'
        except Exception:
            return False

    def refund_capture(self, capture_id: str, amount: float | None = None) -> dict:
        payload = {}
        if amount:
            payload['amount'] = {'value': f'{amount:.2f}', 'currency_code': 'USD'}
        resp = requests.post(
            f'{self._base_url()}/v2/payments/captures/{capture_id}/refund',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


paypal = PayPalService()
