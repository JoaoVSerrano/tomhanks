"""Testes de segurança: garante que database.py falha explicitamente
quando variáveis obrigatórias não estão definidas.

Esses testes NÃO precisam de banco real — verificam apenas o comportamento
de inicialização do módulo.
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import patch

import pytest


# Variáveis mínimas para os módulos de banco inicializarem sem erro
_DB_VARS = {
    'DB_HOST': 'test-host',
    'DB_USER': 'test-user',
    'DB_PASSWORD': 'test-pass',
    'DB_NAME': 'test-db',
}

_AUTH_APP_VARS = {
    'AUTH_SECRET_KEY': 'test-auth-secret-aleatoria',
    'FLASK_SECRET_KEY': 'test-flask-secret-aleatoria',
    **_DB_VARS,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_module(module_name: str, env: dict[str, str]):
    """Recarrega um módulo Python com um ambiente limpo."""
    # Remove caches para forçar re-execução do código de nível de módulo
    for key in list(sys.modules.keys()):
        if key == module_name or key.startswith(module_name + '.'):
            del sys.modules[key]

    with patch.dict(os.environ, env, clear=False):
        # Limpa variáveis de banco do ambiente para isolar o teste
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ('DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME',
                                  'AUTH_DB_HOST', 'AUTH_DB_USER', 'AUTH_DB_PASSWORD', 'AUTH_DB_NAME',
                                  'FLASK_SECRET_KEY', 'AUTH_SECRET_KEY')}
        clean_env.update(env)
        with patch.dict(os.environ, clean_env, clear=True):
            return importlib.import_module(module_name)


# ---------------------------------------------------------------------------
# backend/database.py
# ---------------------------------------------------------------------------

class TestBackendDatabaseRequiredEnv:
    """backend/database.py deve falhar com SystemExit se vars obrigatórias ausentes."""

    @pytest.mark.parametrize('missing_var', ['DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'])
    def test_exits_when_required_var_missing(self, missing_var: str, monkeypatch):
        """Cada variável obrigatória ausente deve causar SystemExit."""
        env = {k: v for k, v in _DB_VARS.items() if k != missing_var}
        # Garante que a variável faltante não está no ambiente
        monkeypatch.delenv(missing_var, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        # Remove módulo do cache para forçar re-importação
        for key in list(sys.modules.keys()):
            if 'backend.database' in key or key == 'backend.database':
                del sys.modules[key]

        with pytest.raises(SystemExit):
            import backend.database  # noqa: F401

    def test_succeeds_with_all_required_vars(self, monkeypatch):
        """Com todas as variáveis definidas, o módulo deve importar sem erro."""
        for k, v in _DB_VARS.items():
            monkeypatch.setenv(k, v)

        for key in list(sys.modules.keys()):
            if 'backend.database' in key:
                del sys.modules[key]

        # Substituímos create_engine para não tentar conectar ao banco
        with patch('sqlalchemy.create_engine') as mock_engine:
            mock_engine.return_value = mock_engine
            mock_engine.connect.side_effect = Exception('sem banco real')
            try:
                import backend.database  # noqa: F401
                # Se chegou aqui sem SystemExit, o teste passou
            except SystemExit:
                pytest.fail('database.py levantou SystemExit com todas as variáveis definidas')
            except Exception:
                # Outros erros (conexão, etc.) são aceitáveis — o que não pode é sys.exit()
                pass


# ---------------------------------------------------------------------------
# auth_service/database.py
# ---------------------------------------------------------------------------

class TestAuthServiceDatabaseRequiredEnv:
    """auth_service/database.py deve falhar com SystemExit se vars obrigatórias ausentes."""

    @pytest.mark.parametrize('missing_var', ['DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'])
    def test_exits_when_required_var_missing(self, missing_var: str, monkeypatch):
        """Cada variável obrigatória ausente deve causar SystemExit."""
        env = {k: v for k, v in _DB_VARS.items() if k != missing_var}
        monkeypatch.delenv(missing_var, raising=False)
        # Também limpa aliases AUTH_DB_*
        monkeypatch.delenv(f'AUTH_{missing_var}', raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        for key in list(sys.modules.keys()):
            if 'auth_service.database' in key or key == 'auth_service.database':
                del sys.modules[key]

        with pytest.raises(SystemExit):
            import auth_service.database  # noqa: F401

    def test_succeeds_with_all_required_vars(self, monkeypatch):
        """Com todas as variáveis definidas, o módulo deve importar sem erro."""
        for k, v in _DB_VARS.items():
            monkeypatch.setenv(k, v)

        for key in list(sys.modules.keys()):
            if 'auth_service.database' in key:
                del sys.modules[key]

        with patch('sqlalchemy.create_engine') as mock_engine:
            mock_engine.return_value = mock_engine
            mock_engine.connect.side_effect = Exception('sem banco real')
            try:
                import auth_service.database  # noqa: F401
            except SystemExit:
                pytest.fail('auth_service/database.py levantou SystemExit com todas as variáveis definidas')
            except Exception:
                pass


# ---------------------------------------------------------------------------
# backend/app.py — FLASK_SECRET_KEY obrigatória
# ---------------------------------------------------------------------------

class TestBackendAppRequiredSecrets:
    """backend/app.py deve falhar se FLASK_SECRET_KEY não estiver definida."""

    def test_exits_when_flask_secret_key_missing(self, monkeypatch):
        """FLASK_SECRET_KEY ausente deve causar SystemExit."""
        # Define vars de banco para não falhar aí
        for k, v in _DB_VARS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)

        for key in list(sys.modules.keys()):
            if 'backend.app' in key or key == 'backend.app':
                del sys.modules[key]

        with pytest.raises(SystemExit):
            import backend.app  # noqa: F401


# ---------------------------------------------------------------------------
# auth_service/app.py — AUTH_SECRET_KEY obrigatória
# ---------------------------------------------------------------------------

class TestAuthServiceAppRequiredSecrets:
    """auth_service/app.py deve falhar se AUTH_SECRET_KEY não estiver definida."""

    def test_exits_when_auth_secret_key_missing(self, monkeypatch):
        """AUTH_SECRET_KEY ausente deve causar SystemExit."""
        for k, v in _DB_VARS.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv('AUTH_SECRET_KEY', raising=False)

        for key in list(sys.modules.keys()):
            if 'auth_service.app' in key or key == 'auth_service.app':
                del sys.modules[key]

        with pytest.raises(SystemExit):
            import auth_service.app  # noqa: F401
