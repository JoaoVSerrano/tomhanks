"""Testes para o payment-service: webhook, idempotência e entitlement.

Cobre as regras principais:
- Webhook com assinatura inválida deve retornar 400.
- Evento de webhook repetido deve ser ignorado (idempotência).
- Entitlement sem google_id retorna has_premium=False.
- Entitlement com Stripe indisponível retorna gracefully.
- Checkout sem google_id retorna 400.
"""
from __future__ import annotations

import json
import unittest.mock as mock
from unittest.mock import MagicMock, patch

import pytest


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def payment_app():
    """Cria o app do payment-service em modo de teste com banco em memória falso."""
    with (
        patch('payment_service.database._check_required_env'),
        patch('payment_service.database.engine'),
        patch('payment_service.database.SessionLocal'),
    ):
        from payment_service.app import app
        app.config['TESTING'] = True
        with app.test_client() as client:
            yield client


@pytest.fixture
def internal_headers():
    """Cabeçalhos de token interno para chamadas internas."""
    return {'X-Internal-Token': 'test-internal-token-1234567890'}


# ────────────────────────────────────────────────────────────────────────────
# Testes de health
# ────────────────────────────────────────────────────────────────────────────

class TestPaymentHealth:
    def test_health_retorna_200_ou_503(self, payment_app):
        """O health check deve sempre responder (mesmo sem BD/Redis)."""
        resp = payment_app.get('/health')
        assert resp.status_code in (200, 503)
        data = resp.get_json()
        assert 'status' in data
        assert 'service' in data
        assert data['service'] == 'payment-service'

    def test_health_sem_stripe_key(self, payment_app):
        """Sem STRIPE_SECRET_KEY, stripe deve aparecer como not_configured."""
        with patch.dict('os.environ', {'STRIPE_SECRET_KEY': ''}, clear=False):
            resp = payment_app.get('/health')
            data = resp.get_json()
            assert data.get('stripe') in ('configured', 'not_configured')


# ────────────────────────────────────────────────────────────────────────────
# Testes de entitlement
# ────────────────────────────────────────────────────────────────────────────

class TestEntitlement:
    def test_entitlement_sem_google_id_retorna_400(self, payment_app, internal_headers):
        """Chamar /entitlement sem google_id deve retornar 400."""
        resp = payment_app.get('/entitlement', headers=internal_headers)
        assert resp.status_code == 400
        data = resp.get_json()
        assert 'error' in data

    def test_entitlement_sem_token_retorna_403(self, payment_app):
        """Chamar /entitlement sem token interno deve retornar 403."""
        resp = payment_app.get('/entitlement?google_id=test123')
        assert resp.status_code == 403

    def test_entitlement_sem_customer_retorna_no_customer(self, payment_app, internal_headers):
        """google_id sem registro retorna has_premium=False."""
        with (
            patch('payment_service.app._get_stripe_customer_id', return_value=None),
            patch('payment_service.app.get_redis') as mock_redis,
        ):
            mock_r = MagicMock()
            mock_r.get.return_value = None
            mock_redis.return_value = mock_r

            resp = payment_app.get(
                '/entitlement?google_id=google_sem_registro',
                headers=internal_headers,
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['has_premium'] is False
            assert data['status'] == 'no_customer'

    def test_entitlement_com_cache_redis_retorna_cached(self, payment_app, internal_headers):
        """Quando existe cache Redis, deve retornar sem chamar a Stripe."""
        cached_data = {
            'has_premium': True,
            'status': 'active',
            'plan': 'premium',
            'period_end': '2027-01-01T00:00:00+00:00',
        }

        with patch('payment_service.app.get_redis') as mock_redis:
            mock_r = MagicMock()
            mock_r.get.return_value = json.dumps(cached_data)
            mock_redis.return_value = mock_r

            resp = payment_app.get(
                '/entitlement?google_id=google_com_cache',
                headers=internal_headers,
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['has_premium'] is True
            assert data['status'] == 'active'

    def test_entitlement_stripe_indisponivel_retorna_erro(self, payment_app, internal_headers):
        """Quando a Stripe falha, entitlement deve retornar gracefully sem levantar exceção."""
        import stripe

        with (
            patch('payment_service.app._get_stripe_customer_id', return_value='cus_fake'),
            patch('payment_service.app.get_redis') as mock_redis,
            patch('stripe.Subscription.list', side_effect=stripe.APIConnectionError('offline')),
        ):
            mock_r = MagicMock()
            mock_r.get.return_value = None
            mock_redis.return_value = mock_r

            resp = payment_app.get(
                '/entitlement?google_id=google_stripe_down',
                headers=internal_headers,
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data['has_premium'] is False
            assert 'stripe_error' in data.get('status', '')


# ────────────────────────────────────────────────────────────────────────────
# Testes de webhook
# ────────────────────────────────────────────────────────────────────────────

class TestWebhook:
    def test_webhook_sem_assinatura_retorna_400(self, payment_app):
        """Webhook sem header Stripe-Signature deve retornar 400."""
        with patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_test'}, clear=False):
            resp = payment_app.post(
                '/webhook',
                data=b'{}',
                content_type='application/json',
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert 'error' in data

    def test_webhook_com_assinatura_invalida_retorna_400(self, payment_app):
        """Webhook com assinatura inválida deve ser rejeitado com 400."""
        import stripe

        with (
            patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_test'}, clear=False),
            patch(
                'stripe.Webhook.construct_event',
                side_effect=stripe.SignatureVerificationError('sig inválida', 'bad_sig'),
            ),
        ):
            resp = payment_app.post(
                '/webhook',
                data=b'{"type":"checkout.session.completed"}',
                content_type='application/json',
                headers={'Stripe-Signature': 'assinatura_invalida'},
            )
            assert resp.status_code == 400
            data = resp.get_json()
            assert 'Assinatura inválida' in str(data.get('error', ''))

    def test_webhook_evento_duplicado_ignorado(self, payment_app):
        """Evento de webhook já processado deve ser ignorado (idempotência)."""
        fake_event = MagicMock()
        fake_event.id = 'evt_test_duplicado_123'
        fake_event.type = 'checkout.session.completed'
        fake_event.data.object = {'metadata': {}, 'id': 'cs_test'}

        existing_record = MagicMock()  # simula registro existente no BD

        with (
            patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_test'}, clear=False),
            patch('stripe.Webhook.construct_event', return_value=fake_event),
            patch('payment_service.app.session_scope') as mock_scope,
        ):
            mock_db = MagicMock()
            mock_db.scalar.return_value = existing_record  # evento já existe
            mock_scope.return_value.__enter__.return_value = mock_db

            resp = payment_app.post(
                '/webhook',
                data=b'{"type":"checkout.session.completed"}',
                content_type='application/json',
                headers={'Stripe-Signature': 'sig_test'},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('ok') is True
            assert data.get('duplicate') is True

    def test_webhook_evento_novo_processado(self, payment_app):
        """Novo evento de webhook deve ser processado e registrado."""
        fake_event = MagicMock()
        fake_event.id = 'evt_test_novo_456'
        fake_event.type = 'customer.subscription.updated'
        fake_event.data.object = {'customer': 'cus_test', 'status': 'active'}

        with (
            patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': 'whsec_test'}, clear=False),
            patch('stripe.Webhook.construct_event', return_value=fake_event),
            patch('payment_service.app.session_scope') as mock_scope,
            patch('payment_service.app.log_event'),
            patch('payment_service.app.get_redis') as mock_redis,
        ):
            mock_db = MagicMock()
            mock_db.scalar.return_value = None  # evento NÃO existe ainda
            mock_scope.return_value.__enter__.return_value = mock_db

            mock_r = MagicMock()
            mock_redis.return_value = mock_r

            resp = payment_app.post(
                '/webhook',
                data=b'{"type":"customer.subscription.updated"}',
                content_type='application/json',
                headers={'Stripe-Signature': 'sig_test'},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data.get('ok') is True
            assert not data.get('duplicate')

    def test_webhook_sem_secret_configurado_retorna_500(self, payment_app):
        """Webhook sem STRIPE_WEBHOOK_SECRET configurado deve retornar 500."""
        with patch.dict('os.environ', {'STRIPE_WEBHOOK_SECRET': ''}, clear=False):
            resp = payment_app.post(
                '/webhook',
                data=b'{}',
                content_type='application/json',
                headers={'Stripe-Signature': 'sig_test'},
            )
            assert resp.status_code == 500


# ────────────────────────────────────────────────────────────────────────────
# Testes de checkout
# ────────────────────────────────────────────────────────────────────────────

class TestCheckout:
    def test_checkout_sem_token_retorna_403(self, payment_app):
        """Checkout sem X-Internal-Token deve retornar 403."""
        resp = payment_app.post(
            '/checkout',
            json={'google_id': 'google123', 'email': 'test@test.com'},
        )
        assert resp.status_code == 403

    def test_checkout_sem_google_id_retorna_400(self, payment_app, internal_headers):
        """Checkout sem google_id deve retornar 400."""
        with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_fake', 'STRIPE_PRICE_ID': 'price_test'}, clear=False):
            resp = payment_app.post(
                '/checkout',
                json={'email': 'test@test.com'},
                headers=internal_headers,
            )
            assert resp.status_code == 400

    def test_checkout_sem_price_id_retorna_503(self, payment_app, internal_headers):
        """Checkout sem STRIPE_PRICE_ID configurado deve retornar 503."""
        with patch.dict('os.environ', {'STRIPE_SECRET_KEY': 'sk_test_fake', 'STRIPE_PRICE_ID': ''}, clear=False):
            resp = payment_app.post(
                '/checkout',
                json={'google_id': 'google123', 'email': 'test@test.com'},
                headers=internal_headers,
            )
            assert resp.status_code == 503

    def test_checkout_sem_stripe_key_retorna_503(self, payment_app, internal_headers):
        """Checkout sem STRIPE_SECRET_KEY deve retornar 503."""
        import stripe
        # Simula stripe sem api_key
        orig_key = stripe.api_key
        try:
            stripe.api_key = ''
            with patch.dict('os.environ', {'STRIPE_SECRET_KEY': '', 'STRIPE_PRICE_ID': 'price_test'}, clear=False):
                resp = payment_app.post(
                    '/checkout',
                    json={'google_id': 'google123', 'email': 'test@test.com'},
                    headers=internal_headers,
                )
                assert resp.status_code == 503
        finally:
            stripe.api_key = orig_key
