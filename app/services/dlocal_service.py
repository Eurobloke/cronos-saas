# -*- coding: utf-8 -*-
"""
Integración con dLocal Go — pasarela de pago internacional.
Acepta tarjetas, transferencias y métodos locales de toda LATAM y el mundo.
Credenciales: https://dashboard.dlocalgo.com/ → Desarrolladores → API Keys
"""
import hashlib
import hmac
import requests
from flask import current_app


class DLocalService:

    BASE_URL = 'https://api.dlocalgo.com/v1'

    def _headers(self) -> dict:
        api_key = current_app.config.get('DLOCAL_API_KEY', '')
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

    def _secret(self) -> str:
        return current_app.config.get('DLOCAL_SECRET_KEY', '')

    def is_configured(self) -> bool:
        return bool(
            current_app.config.get('DLOCAL_API_KEY') and
            current_app.config.get('DLOCAL_SECRET_KEY')
        )

    # ─── Crear pago ───────────────────────────────────────────────────────────

    def create_payment(self, amount: float, currency: str, description: str,
                       success_url: str, back_url: str,
                       notification_url: str, order_id: str = '') -> dict:
        """
        Crea un pago en dLocal Go y devuelve {payment_id, redirect_url}.
        El cliente es redirigido a redirect_url para completar el pago.
        """
        payload = {
            'amount': round(amount, 2),
            'currency': currency.upper(),
            'description': description,
            'success_url': success_url,
            'back_url': back_url,
            'notification_url': notification_url,
        }
        if order_id:
            payload['external_id'] = str(order_id)

        resp = requests.post(
            f'{self.BASE_URL}/payments',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        return {
            'payment_id': data.get('id') or data.get('payment_id', ''),
            'redirect_url': data.get('url') or data.get('redirect_url', ''),
            'status': data.get('status', 'PENDING'),
        }

    # ─── Consultar estado ─────────────────────────────────────────────────────

    def get_payment(self, payment_id: str) -> dict:
        """Consulta el estado de un pago por su ID."""
        resp = requests.get(
            f'{self.BASE_URL}/payments/{payment_id}',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ─── Verificar firma del webhook ──────────────────────────────────────────

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verifica que el webhook viene de dLocal Go.
        Firma = HMAC-SHA256(secret_key, payload) — hex o con prefijo 'sha256='.
        Si no hay secret configurado, acepta todo (modo dev).
        """
        secret = self._secret()
        if not secret:
            current_app.logger.warning('[dLocal] Sin DLOCAL_SECRET_KEY — webhook aceptado sin verificar')
            return True
        try:
            # Quitar prefijo 'sha256=' si lo trae dLocal
            sig = signature.removeprefix('sha256=').strip()

            expected = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256,
            ).hexdigest()

            ok = hmac.compare_digest(expected, sig)
            if not ok:
                current_app.logger.warning(
                    f'[dLocal] Firma inválida. recibida={sig[:20]}... esperada={expected[:20]}...'
                )
            return ok
        except Exception as e:
            current_app.logger.error(f'[dLocal] Error verificando firma: {e}')
            return False

    # ─── Reembolso ────────────────────────────────────────────────────────────

    def refund(self, payment_id: str, amount: float | None = None) -> dict:
        payload = {}
        if amount:
            payload['amount'] = round(amount, 2)
        resp = requests.post(
            f'{self.BASE_URL}/payments/{payment_id}/refund',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


dlocal = DLocalService()
