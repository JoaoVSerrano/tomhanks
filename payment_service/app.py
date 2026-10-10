from __future__ import annotations
import hashlib
import hmac
import json
import os
import time
from typing import Any

import redis
import requests as _requests
import stripe
from flask import Flask, Response, jsonify, request
from prometheus_flask_exporter import PrometheusMetrics
from sqlalchemy import select

from payment_service.database import session_scope, upgrade_database
from payment_service.models import ProcessedWebhookEvent, StripeCustomer

app = Flask(__name__)
metrics = PrometheusMetrics(app)

INTERNAL_TOKEN = os.getenv('INTERNAL_TOKEN', '')
PAYMENT_PORT = int(os.getenv('PAYMENT_PORT', '5000'))

stripe.api_key = os.getenv('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID', '')
STRIPE_SUCCESS_URL = os.getenv('STRIPE_SUCCESS_URL', 'http://localhost:8080/?payment=success')
STRIPE_CANCEL_URL = os.getenv('STRIPE_CANCEL_URL', 'http://localhost:8080/?payment=cancel')

LOG_SERVICE_URL = os.getenv('LOG_SERVICE_URL', 'http://log-service:4000')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CACHE_TTL = int(os.getenv('ENTITLEMENT_CACHE_TTL', '300'))  # 5 minutos

def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status

def require_internal_token():
    token = request.headers.get('X-Internal-Token', '')
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        return json_error('Acesso não autorizado.', 403)
    return None

def get_redis():
    return redis.from_url(REDIS_URL, decode_responses=True)

def log_event(acao: str, google_id: str | None = None, detalhe: str = '') -> None:
    try:
        _requests.post(
            f'{LOG_SERVICE_URL}/log',
            json={'usuario_id': None, 'acao': f'payment:{acao}', 'detalhe': detalhe, 'ip': ''},
            headers={'X-Internal-Token': INTERNAL_TOKEN},
            timeout=3,
        )
    except Exception as exc:
        app.logger.warning('log-service indisponível (acao=%s): %s', acao, exc)

import threading
_init_lock = threading.Lock()
_schema_ready = False

@app.before_request
def initialize():
    global _schema_ready
    if request.path == '/health' or request.method == 'OPTIONS':
        return None
    if _schema_ready:
        return None
    with _init_lock:
        if _schema_ready:
            return None
        try:
            upgrade_database()
            _schema_ready = True
        except Exception:
            app.logger.exception('Falha ao inicializar schema do payment-service.')
    return None

@app.get('/health')
def health():
    db_ok = False
    redis_ok = False
    stripe_ok = bool(stripe.api_key)
    try:
        with session_scope() as db:
            db.execute(select(1))
        db_ok = True
    except Exception as exc:
        app.logger.error('BD indisponível em health: %s', exc)
    try:
        r = get_redis()
        r.ping()
        redis_ok = True
    except Exception as exc:
        app.logger.warning('Redis indisponível em health: %s', exc)
    
    healthy = db_ok
    return jsonify({
        'status': 'healthy' if healthy else 'unhealthy',
        'service': 'payment-service',
        'database': 'connected' if db_ok else 'disconnected',
        'redis': 'connected' if redis_ok else 'disconnected',
        'stripe': 'configured' if stripe_ok else 'not_configured',
    }), 200 if healthy else 503

def _get_stripe_customer_id(google_id: str) -> str | None:
    with session_scope() as db:
        record = db.scalar(select(StripeCustomer).where(StripeCustomer.google_id == google_id))
        return record.stripe_customer_id if record else None

def _check_entitlement_from_stripe(stripe_customer_id: str) -> dict[str, Any]:
    try:
        subscriptions = stripe.Subscription.list(
            customer=stripe_customer_id,
            status='all',
            limit=1,
        )
        if not subscriptions.data:
            return {'has_premium': False, 'status': 'no_subscription', 'plan': None, 'period_end': None}
        
        sub = subscriptions.data[0]
        active = sub.status in ('active', 'trialing')
        plan_name = None
        if sub.items.data:
            price = sub.items.data[0].price
            plan_name = price.get('nickname') or price.id
        
        period_end = None
        if sub.current_period_end:
            import datetime
            period_end = datetime.datetime.fromtimestamp(
                sub.current_period_end, tz=datetime.timezone.utc
            ).isoformat()
        
        return {
            'has_premium': active,
            'status': sub.status,
            'plan': plan_name,
            'period_end': period_end,
        }
    except stripe.StripeError as exc:
        app.logger.error('Erro Stripe ao verificar entitlement: %s', exc)
        return {'has_premium': False, 'status': 'stripe_error', 'plan': None, 'period_end': None}

@app.get('/entitlement')
def entitlement():
    err = require_internal_token()
    if err:
        return err
    
    google_id = request.args.get('google_id', '').strip()
    if not google_id:
        return json_error('Parâmetro google_id obrigatório.')
    
    if not stripe.api_key:
        return jsonify({'has_premium': False, 'status': 'stripe_not_configured', 'plan': None, 'period_end': None})
    
    cache_key = f'entitlement:{google_id}'
    try:
        r = get_redis()
        cached = r.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except Exception as exc:
        app.logger.warning('Falha no cache Redis (continuando sem cache): %s', exc)
    
    customer_id = _get_stripe_customer_id(google_id)
    if not customer_id:
        result = {'has_premium': False, 'status': 'no_customer', 'plan': None, 'period_end': None}
        return jsonify(result)
    
    result = _check_entitlement_from_stripe(customer_id)
    
    try:
        r = get_redis()
        r.setex(cache_key, CACHE_TTL, json.dumps(result))
    except Exception as exc:
        app.logger.warning('Falha ao gravar cache Redis: %s', exc)
    
    return jsonify(result)

@app.post('/checkout')
def create_checkout():
    err = require_internal_token()
    if err:
        return err
    
    stripe_secret = os.getenv('STRIPE_SECRET_KEY') or stripe.api_key
    if not stripe_secret:
        return json_error('Pagamentos não configurados neste servidor.', 503)
    stripe.api_key = stripe_secret

    price_id = os.getenv('STRIPE_PRICE_ID', '')
    if not price_id:
        return json_error('Plano de assinatura não configurado.', 503)
    
    payload = request.get_json(silent=True) or {}
    google_id = str(payload.get('google_id', '')).strip()
    email = str(payload.get('email', '')).strip()
    
    if not google_id:
        return json_error('google_id obrigatório.')
    
    customer_id = _get_stripe_customer_id(google_id)
    
    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=email or None,
                metadata={'google_id': google_id},
            )
            customer_id = customer.id
        except stripe.StripeError as exc:
            app.logger.error('Erro ao criar customer Stripe: %s', exc)
            return json_error('Falha ao iniciar assinatura.', 502)
        
        with session_scope() as db:
            db.add(StripeCustomer(google_id=google_id, stripe_customer_id=customer_id))
    
    try:
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='subscription',
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
            metadata={'google_id': google_id},
        )
    except stripe.StripeError as exc:
        app.logger.error('Erro ao criar checkout session: %s', exc)
        return json_error('Falha ao criar sessão de pagamento.', 502)
    
    log_event('checkout_iniciado', google_id=google_id, detalhe=f'session_id={checkout_session.id}')
    return jsonify({'checkout_url': checkout_session.url}), 201

@app.post('/portal')
def create_portal():
    err = require_internal_token()
    if err:
        return err
    
    stripe_secret = os.getenv('STRIPE_SECRET_KEY') or stripe.api_key
    if not stripe_secret:
        return json_error('Pagamentos não configurados neste servidor.', 503)
    stripe.api_key = stripe_secret
    
    payload = request.get_json(silent=True) or {}
    google_id = str(payload.get('google_id', '')).strip()
    
    if not google_id:
        return json_error('google_id obrigatório.')
    
    customer_id = _get_stripe_customer_id(google_id)
    if not customer_id:
        return json_error('Usuário não possui assinatura ativa.', 404)
    
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:8080')
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=frontend_url,
        )
    except stripe.StripeError as exc:
        app.logger.error('Erro ao criar portal session: %s', exc)
        return json_error('Falha ao abrir portal de assinatura.', 502)
    
    log_event('portal_aberto', google_id=google_id)
    return jsonify({'portal_url': portal_session.url})

@app.post('/webhook')
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')
    
    webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET', STRIPE_WEBHOOK_SECRET)
    if not webhook_secret:
        return json_error('Webhook secret não configurado.', 500)
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (stripe.SignatureVerificationError, getattr(stripe, 'error', None) and getattr(stripe.error, 'SignatureVerificationError', Exception)):
        app.logger.warning('Assinatura de webhook Stripe inválida — requisição rejeitada.')
        return json_error('Assinatura inválida.', 400)
    except Exception as exc:
        if type(exc).__name__ == 'SignatureVerificationError':
            app.logger.warning('Assinatura de webhook Stripe inválida — requisição rejeitada.')
            return json_error('Assinatura inválida.', 400)
        app.logger.error('Erro ao construir evento webhook: %s', exc)
        return json_error('Payload inválido.', 400)
    
    event_id = event.id
    event_type = event.type
    
    with session_scope() as db:
        existing = db.scalar(
            select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.stripe_event_id == event_id)
        )
        if existing:
            app.logger.info('Evento webhook %s já processado — ignorado.', event_id)
            return jsonify({'ok': True, 'duplicate': True})
        
        db.add(ProcessedWebhookEvent(stripe_event_id=event_id, event_type=event_type))
    
    _handle_webhook_event(event_type, event.data.object)
    
    log_event('webhook_processado', detalhe=f'event_type={event_type} event_id={event_id}')
    return jsonify({'ok': True})

def _handle_webhook_event(event_type: str, obj: Any) -> None:
    if event_type == 'checkout.session.completed':
        google_id = obj.get('metadata', {}).get('google_id', '')
        if google_id:
            try:
                r = get_redis()
                r.delete(f'entitlement:{google_id}')
            except Exception:
                pass
            log_event('assinatura_ativada', google_id=google_id, detalhe=f'session_id={obj.get("id", "")}')
    
    elif event_type in ('customer.subscription.updated', 'customer.subscription.deleted'):
        customer_id = obj.get('customer', '')
        if customer_id:
            try:
                with session_scope() as db:
                    record = db.scalar(
                        select(StripeCustomer).where(StripeCustomer.stripe_customer_id == customer_id)
                    )
                    if record:
                        r = get_redis()
                        r.delete(f'entitlement:{record.google_id}')
            except Exception as exc:
                app.logger.warning('Falha ao invalidar cache após evento %s: %s', event_type, exc)
        log_event('assinatura_atualizada', detalhe=f'event_type={event_type} customer_id={customer_id}')
    
    elif event_type == 'invoice.payment_failed':
        customer_id = obj.get('customer', '')
        log_event('pagamento_falhou', detalhe=f'customer_id={customer_id}')
    
    else:
        app.logger.info('Evento webhook não tratado: %s', event_type)

@app.get('/api/docs/openapi.json')
def get_openapi_json():
    from payment_service.swagger_spec import get_openapi_json as _json_fn
    return Response(_json_fn(), content_type='application/json; charset=utf-8')

@app.get('/apidocs')
@app.get('/docs')
def apidocs():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>payment-service — Documentação OpenAPI</title>
  <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui.min.css" />
  <style>
    body { margin:0; background: #0f172a; color: #f8fafc; font-family: sans-serif; }
    .swagger-ui .topbar { background-color: #1e293b; border-bottom: 2px solid #e94560; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/swagger-ui/5.11.0/swagger-ui-bundle.min.js"></script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/api/docs/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true
      });
    };
  </script>
</body>
</html>""", 200, {'Content-Type': 'text/html; charset=utf-8'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PAYMENT_PORT, debug=os.getenv('PAYMENT_DEBUG', '0') == '1')
