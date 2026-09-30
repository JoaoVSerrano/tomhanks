from __future__ import annotations

import json
import os
import time

import redis
from flask import Flask, jsonify, request

app = Flask(__name__)

REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
INTERNAL_TOKEN = os.getenv('INTERNAL_TOKEN', '')
LOG_STREAM_KEY = 'audit:logs'

# Quantidade máxima de entradas no stream (trim automático)
MAX_LOG_ENTRIES = int(os.getenv('MAX_LOG_ENTRIES', '10000'))


def get_redis() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def json_error(message: str, status: int = 400):
    return jsonify({'error': message}), status


def require_internal_token():
    """Verifica se a requisição vem de um serviço interno."""
    token = request.headers.get('X-Internal-Token', '')
    if not INTERNAL_TOKEN or token != INTERNAL_TOKEN:
        return json_error('Acesso não autorizado.', 403)
    return None


from prometheus_flask_exporter import PrometheusMetrics

metrics = PrometheusMetrics(app)


# ---------------------------------------------------------------------------
# Health & Readiness
# ---------------------------------------------------------------------------

@app.get('/health')
def health():
    try:
        r = get_redis()
        r.ping()
        return jsonify({'status': 'healthy', 'service': 'log-service', 'redis': 'connected'}), 200
    except Exception as exc:
        app.logger.error('Redis indisponível em healthcheck: %s', exc)
        return jsonify({'status': 'unhealthy', 'service': 'log-service', 'redis': 'disconnected', 'error': str(exc)}), 503


# ---------------------------------------------------------------------------
# Gravar evento de auditoria (uso interno)
# ---------------------------------------------------------------------------

@app.post('/log')
def record_log():
    """Grava um evento de auditoria no Redis Stream.

    Payload esperado (JSON):
        usuario_id  : int | None
        acao        : str          (ex: "login", "logout", "favoritar", "comentar", "403")
        detalhe     : str | None   (informação adicional opcional)
        ip          : str | None   (IP de origem — bônus)

    Requer header X-Internal-Token.
    """
    err = require_internal_token()
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    usuario_id = payload.get('usuario_id')
    acao = str(payload.get('acao', '')).strip()
    detalhe = str(payload.get('detalhe', '')).strip()
    ip = str(payload.get('ip', '')).strip()

    if not acao:
        return json_error('Campo "acao" é obrigatório.')

    try:
        r = get_redis()
        entry = {
            'usuario_id': str(usuario_id) if usuario_id is not None else '',
            'acao': acao,
            'detalhe': detalhe,
            'ip': ip,
            # timestamp em milissegundos (para referência humana além do ID do stream)
            'ts_ms': str(int(time.time() * 1000)),
        }
        # XADD com trim automático para não crescer indefinidamente
        event_id = r.xadd(LOG_STREAM_KEY, entry, maxlen=MAX_LOG_ENTRIES, approximate=True)
        return jsonify({'ok': True, 'event_id': event_id}), 201
    except Exception as exc:
        app.logger.error('Erro ao gravar log no Redis: %s', exc)
        return json_error(f'Erro interno ao gravar log: {exc}', 500)


# ---------------------------------------------------------------------------
# Consultar eventos (uso interno — só admin pode chamar via catálogo)
# ---------------------------------------------------------------------------

@app.get('/logs')
def list_logs():
    """Retorna os últimos N eventos do stream de auditoria.

    Query params:
        n   : int (padrão 50, máx 500) — quantos eventos retornar
        start : str (padrão '-') — ID de início do range (XRANGE notation)
        end   : str (padrão '+') — ID de fim do range

    Requer header X-Internal-Token.
    """
    err = require_internal_token()
    if err:
        return err

    try:
        n = int(request.args.get('n', 50))
        n = max(1, min(n, 500))
    except (TypeError, ValueError):
        n = 50

    start = request.args.get('start', '-')
    end = request.args.get('end', '+')

    try:
        r = get_redis()
        # XREVRANGE retorna do mais recente para o mais antigo
        raw_entries = r.xrevrange(LOG_STREAM_KEY, max=end, min=start, count=n)
        logs = []
        for event_id, fields in raw_entries:
            logs.append({
                'event_id': event_id,
                'usuario_id': fields.get('usuario_id') or None,
                'acao': fields.get('acao', ''),
                'detalhe': fields.get('detalhe', '') or None,
                'ip': fields.get('ip', '') or None,
                'ts_ms': int(fields.get('ts_ms', 0)),
            })
        return jsonify({'logs': logs, 'count': len(logs)})
    except Exception as exc:
        app.logger.error('Erro ao consultar logs no Redis: %s', exc)
        return json_error(f'Erro interno ao consultar logs: {exc}', 500)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    port = int(os.getenv('LOG_PORT', '4000'))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('LOG_DEBUG', '0') == '1')
