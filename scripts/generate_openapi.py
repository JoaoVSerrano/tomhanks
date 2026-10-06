#!/usr/bin/env python3
"""Script para regenerar openapi.json e openapi.yaml na raiz do repositório
de forma reproduzível a partir da especificação backend/swagger_spec.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Adiciona a raiz do projeto ao sys.path para permitir importações
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Configura variáveis mínimas para carregar o módulo
os.environ.setdefault('DB_HOST', 'localhost')
os.environ.setdefault('DB_USER', 'test')
os.environ.setdefault('DB_PASSWORD', 'test')
os.environ.setdefault('DB_NAME', 'test')
os.environ.setdefault('FLASK_SECRET_KEY', 'test')
os.environ.setdefault('AUTH_SECRET_KEY', 'test')
os.environ.setdefault('INTERNAL_TOKEN', 'test')

from backend.swagger_spec import get_openapi_json, get_openapi_yaml


def main() -> None:
    json_path = ROOT_DIR / 'openapi.json'
    yaml_path = ROOT_DIR / 'openapi.yaml'

    print(f"Gerando {json_path}...")
    json_path.write_text(get_openapi_json() + '\n', encoding='utf-8')

    print(f"Gerando {yaml_path}...")
    yaml_path.write_text(get_openapi_yaml() + '\n', encoding='utf-8')

    print("✅ Especificações OpenAPI geradas com sucesso!")


if __name__ == '__main__':
    main()
