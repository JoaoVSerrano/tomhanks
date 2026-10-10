from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from backend.app import app
from backend.swagger_spec import OPENAPI_SPEC


def healthy_database_context():
    return nullcontext(Mock(execute=Mock()))


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client, monkeypatch):
    """Readiness retorna 200 quando banco e dependências estão disponíveis."""
    monkeypatch.setattr('backend.app.session_scope', healthy_database_context)
    monkeypatch.setattr('backend.app.minio_is_ready', lambda: True)
    monkeypatch.setattr(
        'backend.app.requests.get',
        lambda *args, **kwargs: Mock(status_code=200),
    )

    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'healthy'
    assert data['dependencies'] == {
        'database': 'connected',
        'auth_service': 'reachable',
        'log_service': 'reachable',
        'payment_service': 'reachable',
        'minio': 'connected',
    }


def test_health_endpoint_returns_503_when_dependency_is_down(client, monkeypatch):
    """Readiness falha fechando o tráfego quando uma dependência cai."""
    monkeypatch.setattr('backend.app.session_scope', healthy_database_context)
    monkeypatch.setattr('backend.app.minio_is_ready', lambda: False)
    monkeypatch.setattr(
        'backend.app.requests.get',
        lambda *args, **kwargs: Mock(status_code=200),
    )

    response = client.get('/health')

    assert response.status_code == 503
    assert response.get_json()['status'] == 'unhealthy'
    assert response.get_json()['dependencies']['minio'] == 'disconnected'


def test_metrics_endpoint_exposes_request_count_and_latency(client, monkeypatch):
    """O exporter publica contagem e duração no formato Prometheus."""
    monkeypatch.setattr('backend.app.session_scope', healthy_database_context)
    monkeypatch.setattr('backend.app.minio_is_ready', lambda: True)
    monkeypatch.setattr(
        'backend.app.requests.get',
        lambda *args, **kwargs: Mock(status_code=200),
    )

    client.get('/api/health')
    response = client.get('/metrics')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'flask_http_request_total' in body
    assert 'flask_http_request_duration_seconds' in body


def test_swagger_json_endpoint(client):
    """Testa se a rota /api/docs/openapi.json retorna a especificação OpenAPI 3.0 válida."""
    response = client.get('/api/docs/openapi.json')
    assert response.status_code == 200
    data = response.get_json()
    assert data['openapi'] == '3.0.3'
    assert 'info' in data
    assert 'paths' in data
    assert '/api/health' in data['paths']
    assert '/api/profile/{user_id}' in data['paths']


def test_swagger_ui_endpoint(client):
    """Testa se a rota /apidocs renderiza a página HTML do Swagger UI."""
    response = client.get('/apidocs')
    assert response.status_code == 200
    assert b'SwaggerUIBundle' in response.data
    assert b'swagger-ui' in response.data


def test_openapi_spec_structure():
    """Valida que a especificação OpenAPI 3.0 contém todas as tags e rotas necessárias."""
    assert OPENAPI_SPEC['openapi'] == '3.0.3'
    assert len(OPENAPI_SPEC['paths']) >= 15
    tags = [tag['name'] for tag in OPENAPI_SPEC['tags']]
    assert 'Health' in tags
    assert 'Autenticação' in tags
    assert 'Perfil & Upload' in tags
    assert 'Administração & Auditoria' in tags
