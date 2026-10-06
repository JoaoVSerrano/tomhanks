"""Especificação OpenAPI 3.0 do log-service.

Mantida junto ao código para minimizar dessincronização.
"""
from __future__ import annotations

import json
from typing import Any

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "log-service — API de Auditoria",
        "description": (
            "Documentação OpenAPI 3.0 do microsserviço de auditoria do Catálogo Tom Hanks.\n\n"
            "Todas as rotas requerem o header `X-Internal-Token` — este serviço é **interno**, "
            "não exposto à internet.\n\n"
            "Disciplina ISW055 — Introdução à Computação em Nuvem · Professor: [@siriani](https://github.com/siriani)"
        ),
        "version": "1.0.0",
        "contact": {
            "name": "Allan Siriani (Professor)",
            "url": "https://github.com/siriani",
        },
    },
    "servers": [{"url": "/", "description": "log-service (rede interna Docker — porta 4000)"}],
    "components": {
        "securitySchemes": {
            "InternalToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Internal-Token",
                "description": "Token secreto compartilhado entre serviços internos.",
            }
        }
    },
    "tags": [
        {"name": "Health", "description": "Status de saúde do log-service"},
        {"name": "Auditoria", "description": "Gravação e consulta de eventos de auditoria no Redis Streams"},
    ],
    "paths": {
        "/health": {
            "get": {
                "tags": ["Health"],
                "summary": "Healthcheck do log-service",
                "description": "Verifica conectividade com o Redis via `redis.ping()`.",
                "responses": {
                    "200": {
                        "description": "Serviço saudável",
                        "content": {
                            "application/json": {
                                "example": {
                                    "status": "healthy",
                                    "service": "log-service",
                                    "redis": "connected",
                                }
                            }
                        },
                    },
                    "503": {
                        "description": "Redis indisponível",
                        "content": {
                            "application/json": {
                                "example": {
                                    "status": "unhealthy",
                                    "service": "log-service",
                                    "redis": "disconnected",
                                    "error": "Connection refused",
                                }
                            }
                        },
                    },
                },
            }
        },
        "/log": {
            "post": {
                "tags": ["Auditoria"],
                "summary": "Gravar evento de auditoria no Redis Stream",
                "description": (
                    "Grava um evento no stream `audit:logs` via `XADD`. "
                    "Requer o header `X-Internal-Token`."
                ),
                "security": [{"InternalToken": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["acao"],
                                "properties": {
                                    "usuario_id": {
                                        "type": "integer",
                                        "nullable": True,
                                        "example": 7,
                                    },
                                    "acao": {
                                        "type": "string",
                                        "example": "login",
                                        "description": "Identificador do evento (ex: login, logout, favoritar, 403_acesso_logs)",
                                    },
                                    "detalhe": {
                                        "type": "string",
                                        "nullable": True,
                                        "example": "email=alice@exemplo.com",
                                    },
                                    "ip": {
                                        "type": "string",
                                        "nullable": True,
                                        "example": "172.20.0.1",
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Evento gravado no stream",
                        "content": {
                            "application/json": {
                                "example": {"ok": True, "event_id": "1790809193000-0"}
                            }
                        },
                    },
                    "400": {"description": "Campo obrigatório ausente"},
                    "403": {"description": "X-Internal-Token ausente ou inválido"},
                    "500": {"description": "Erro ao gravar no Redis"},
                },
            }
        },
        "/logs": {
            "get": {
                "tags": ["Auditoria"],
                "summary": "Consultar eventos de auditoria (uso interno)",
                "description": (
                    "Retorna os últimos N eventos do Redis Stream via `XREVRANGE`. "
                    "Requer o header `X-Internal-Token`. "
                    "Usuários comuns não acessam esta rota — o gateway verifica a role 'admin' antes de repassar."
                ),
                "security": [{"InternalToken": []}],
                "parameters": [
                    {
                        "name": "n",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 50, "maximum": 500},
                        "description": "Quantos eventos retornar (padrão 50, máx 500)",
                    },
                    {
                        "name": "start",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "-"},
                        "description": "ID de início do range (XRANGE notation)",
                    },
                    {
                        "name": "end",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "default": "+"},
                        "description": "ID de fim do range",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Lista de eventos de auditoria",
                        "content": {
                            "application/json": {
                                "example": {
                                    "count": 2,
                                    "logs": [
                                        {
                                            "event_id": "1790809193000-0",
                                            "usuario_id": 7,
                                            "acao": "login",
                                            "detalhe": "email=alice@exemplo.com",
                                            "ip": "172.20.0.1",
                                            "ts_ms": 1790809193000,
                                        }
                                    ],
                                }
                            }
                        },
                    },
                    "403": {"description": "X-Internal-Token ausente ou inválido"},
                    "500": {"description": "Erro ao consultar o Redis"},
                },
            }
        },
    },
}


def get_openapi_json() -> str:
    return json.dumps(OPENAPI_SPEC, indent=2, ensure_ascii=False)


def get_openapi_yaml() -> str:
    try:
        import yaml
        return yaml.dump(OPENAPI_SPEC, allow_unicode=True, sort_keys=False)
    except ImportError:
        return (
            "openapi: 3.0.3\n"
            "info:\n"
            "  title: log-service — API de Auditoria\n"
            "  version: 1.0.0\n"
        )
