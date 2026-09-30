from __future__ import annotations

import pytest
from backend.app import app
from backend.swagger_spec import OPENAPI_SPEC


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """Testa se a rota /api/health responde 200 OK com {'ok': True}."""
    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data == {'ok': True}


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
