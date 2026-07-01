# -*- coding: utf-8 -*-
"""
Integración con Lemon Squeezy — pasarela de pago global.
Acepta tarjetas de crédito/débito de todo el mundo.
Credenciales: https://app.lemonsqueezy.com/settings/api
"""
import hmac
import hashlib
import requests
from flask import current_app


class LemonSqueezyService:

    BASE_URL = 'https://api.lemonsqueezy.com/v1'

    def _headers(self) -> dict:
        api_key = current_app.config.get('LEMONSQUEEZY_API_KEY', '')
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/vnd.api+json',
            'Accept': 'application/vnd.api+json',
        }

    def is_configured(self) -> bool:
        return bool(current_app.config.get('LEMONSQUEEZY_API_KEY'))

    def create_checkout(self, variant_id: str, amount_override: float,
                        description: str, success_url: str,
                        custom_data: dict = None) -> dict:
        """
        Crea un checkout de Lemon Squeezy y devuelve la URL de pago.
        variant_id: ID del producto/variante en Lemon Squeezy
        amount_override: precio en USD (para productos con precio variable)
        """
        store_id = current_app.config.get('LEMONSQUEEZY_STORE_ID', '')
        payload = {
            'data': {
                'type': 'checkouts',
                'attributes': {
                    'checkout_data': {
                        'custom': custom_data or {},
                    },
                    'product_options': {
                        'name': description,
                        'redirect_url': success_url,
                    },
                    'checkout_options': {
                        'button_color': '#6366f1',
                    },
                },
                'relationships': {
                    'store': {
                        'data': {'type': 'stores', 'id': str(store_id)}
                    },
                    'variant': {
                        'data': {'type': 'variants', 'id': str(variant_id)}
                    },
                },
            }
        }

        resp = requests.post(
            f'{self.BASE_URL}/checkouts',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get('data', {})
        attrs = data.get('attributes', {})
        return {
            'checkout_id': data.get('id', ''),
            'checkout_url': attrs.get('url', ''),
        }

    def get_order(self, order_id: str) -> dict:
        resp = requests.get(
            f'{self.BASE_URL}/orders/{order_id}',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get('data', {}).get('attributes', {})

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        secret = current_app.config.get('LEMONSQUEEZY_WEBHOOK_SECRET', '')
        if not secret:
            current_app.logger.warning('[LemonSqueezy] Sin webhook secret — aceptado sin verificar')
            return True
        try:
            expected = hmac.new(
                secret.encode('utf-8'), payload, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(expected, signature.strip())
        except Exception as e:
            current_app.logger.error(f'[LemonSqueezy] Error verificando firma: {e}')
            return False


lemonsqueezy = LemonSqueezyService()
