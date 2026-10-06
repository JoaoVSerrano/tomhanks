"""Testes automatizados de validação de paridade da documentação Swagger/OpenAPI 3.0.

Garante que as especificações OpenAPI de cada microsserviço (Gateway/Backend,
auth-service e log-service) permaneçam estritamente sincronizadas com as rotas
reais registradas no `app.url_map`.

O teste falha se:
  1. Uma rota existe no código mas não está documentada na spec OpenAPI.
  2. Uma rota está documentada na spec OpenAPI mas não existe no código.
"""
from __future__ import annotations

import re
from typing import Any

import pytest
from flask import Flask


def _extract_app_routes(app: Flask) -> set[tuple[str, str]]:
    """Extrai todas as rotas e métodos HTTP da aplicação Flask.

    Ignora rotas internas, estáticas, métricas, preflights e rotas da própria documentação.
    Normaliza parâmetros no padrão OpenAPI `{param_name}`.
    """
    routes = set()
    for rule in app.url_map.iter_rules():
        rule_str = rule.rule
        # Ignora rotas estáticas e de telemetria
        if rule_str.startswith('/static') or rule_str == '/metrics':
            continue
        # Ignora rotas da própria UI e spec do Swagger
        if rule_str in ('/apidocs', '/docs') or rule_str.startswith('/api/docs'):
            continue
        # Ignora handlers de preflight e SPA fallback
        if rule.endpoint in ('preflight', 'api_preflight', 'serve_frontend'):
            continue

        methods = rule.methods - {'HEAD', 'OPTIONS'}
        if not methods:
            continue

        # Converte parâmetros Flask <converter:name> ou <name> para {name}
        norm_path = re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', rule_str)
        for method in methods:
            routes.add((norm_path, method.lower()))

    return routes


def _extract_spec_routes(spec: dict[str, Any]) -> set[tuple[str, str]]:
    """Extrai todas as rotas e métodos definidos na especificação OpenAPI."""
    routes = set()
    for path, path_item in spec.get('paths', {}).items():
        for method in ('get', 'post', 'put', 'delete', 'patch'):
            if method in path_item:
                routes.add((path, method))
    return routes


class TestSwaggerParity:
    """Testes de paridade entre rotas reais e especificações OpenAPI."""

    def test_gateway_swagger_parity(self):
        """O gateway backend deve ter 100% de paridade com sua spec OpenAPI."""
        from backend.app import app
        from backend.swagger_spec import OPENAPI_SPEC

        app_routes = _extract_app_routes(app)
        spec_routes = _extract_spec_routes(OPENAPI_SPEC)

        missing_in_spec = app_routes - spec_routes
        missing_in_app = spec_routes - app_routes

        assert not missing_in_spec, f'Rotas no Gateway ausentes na documentação OpenAPI: {sorted(missing_in_spec)}'
        assert not missing_in_app, f'Rotas na documentação OpenAPI inexistentes no Gateway: {sorted(missing_in_app)}'
        assert len(app_routes) == 23

    def test_auth_service_swagger_parity(self):
        """O auth-service deve ter 100% de paridade com sua spec OpenAPI."""
        from auth_service.app import app
        from auth_service.swagger_spec import OPENAPI_SPEC

        app_routes = _extract_app_routes(app)
        spec_routes = _extract_spec_routes(OPENAPI_SPEC)

        missing_in_spec = app_routes - spec_routes
        missing_in_app = spec_routes - app_routes

        assert not missing_in_spec, f'Rotas no auth-service ausentes na documentação OpenAPI: {sorted(missing_in_spec)}'
        assert not missing_in_app, f'Rotas na documentação OpenAPI inexistentes no auth-service: {sorted(missing_in_app)}'
        assert len(app_routes) == 14

    def test_log_service_swagger_parity(self):
        """O log-service deve ter 100% de paridade com sua spec OpenAPI."""
        from log_service.app import app
        from log_service.swagger_spec import OPENAPI_SPEC

        app_routes = _extract_app_routes(app)
        spec_routes = _extract_spec_routes(OPENAPI_SPEC)

        missing_in_spec = app_routes - spec_routes
        missing_in_app = spec_routes - app_routes

        assert not missing_in_spec, f'Rotas no log-service ausentes na documentação OpenAPI: {sorted(missing_in_spec)}'
        assert not missing_in_app, f'Rotas na documentação OpenAPI inexistentes no log-service: {sorted(missing_in_app)}'
        assert len(app_routes) == 3

    def test_gateway_swagger_ui_multi_spec(self, client):
        """A interface Swagger UI do gateway deve conter seletor com as 3 especificações."""
        resp = client.get('/apidocs')
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'Catálogo (Gateway)' in html
        assert 'auth-service' in html
        assert 'log-service' in html
        assert 'urls.primaryName' in html

    def test_no_secrets_in_swagger_specs(self):
        """Nenhum token ou senha real ou default pode aparecer nas specs."""
        from backend.swagger_spec import OPENAPI_SPEC as gateway_spec
        from auth_service.swagger_spec import OPENAPI_SPEC as auth_spec
        from log_service.swagger_spec import OPENAPI_SPEC as log_spec

        import json
        for name, spec in [('gateway', gateway_spec), ('auth', auth_spec), ('log', log_spec)]:
            serialized = json.dumps(spec)
            assert 'internal-change-me' not in serialized, f'Default inseguro encontrado em {name}'
            assert 'minioadmin' not in serialized, f'Credencial do MinIO encontrada em {name}'
            assert 'http://localhost:8080' not in serialized, f'URL absoluta localhost encontrada em {name}'
