"""Configuração global de fixtures e ambiente para execução de testes pytest.

Define variáveis de ambiente mínimas fictícias para permitir a importação e
execução de testes unitários sem dependência de serviços externos reais
(banco de dados MariaDB, MinIO, Redis, etc.).
"""
from __future__ import annotations

import os

_DEFAULT_TEST_ENV = {
    'DB_HOST': 'localhost',
    'DB_PORT': '3306',
    'DB_USER': 'test_user',
    'DB_PASSWORD': 'test_password',
    'DB_NAME': 'test_db',
    'FLASK_SECRET_KEY': 'test-flask-secret-key-1234567890',
    'AUTH_SECRET_KEY': 'test-auth-secret-key-1234567890',
    'INTERNAL_TOKEN': 'test-internal-token-1234567890',
    'MINIO_ACCESS_KEY': 'test-minio-key',
    'MINIO_SECRET_KEY': 'test-minio-secret',
    'REDIS_URL': 'redis://localhost:6379/0',
}

for _key, _value in _DEFAULT_TEST_ENV.items():
    os.environ.setdefault(_key, _value)
