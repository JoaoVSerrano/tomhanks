"""Especificação OpenAPI 3.0 do auth-service.

Mantida junto ao código para minimizar dessincronização.
As rotas aqui devem corresponder exatamente às rotas em app.py.
"""
from __future__ import annotations

import json
from typing import Any

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {
        "title": "auth-service — API",
        "description": (
            "Documentação OpenAPI 3.0 do microsserviço de autenticação do Catálogo Tom Hanks.\n\n"
            "Rotas internas (prefixo `/internal/`) requerem o header `X-Internal-Token`.\n"
            "Disciplina ISW055 — Introdução à Computação em Nuvem · Professor: [@siriani](https://github.com/siriani)"
        ),
        "version": "1.0.0",
        "contact": {
            "name": "Allan Siriani (Professor)",
            "url": "https://github.com/siriani",
        },
    },
    "servers": [{"url": "/", "description": "auth-service (rede interna Docker)"}],
    "components": {
        "securitySchemes": {
            "InternalToken": {
                "type": "apiKey",
                "in": "header",
                "name": "X-Internal-Token",
                "description": "Token secreto compartilhado entre serviços internos (não exposto ao cliente).",
            }
        }
    },
    "tags": [
        {"name": "Health", "description": "Status de saúde do auth-service"},
        {"name": "Autenticação", "description": "Registro, login, logout e sessão"},
        {"name": "Recuperação de Senha", "description": "Fluxo de esqueci/redefinir senha"},
        {"name": "Perfil & Upload", "description": "Dados de perfil e avatar no MinIO"},
        {"name": "Administração", "description": "Gerenciamento de usuários e papéis (admin only)"},
        {"name": "Interno", "description": "Rotas consumidas apenas por outros serviços (requer X-Internal-Token)"},
    ],
    "paths": {
        "/health": {
            "get": {
                "tags": ["Health"],
                "summary": "Healthcheck do auth-service",
                "description": "Verifica conectividade com MariaDB e MinIO.",
                "responses": {
                    "200": {
                        "description": "Serviço saudável",
                        "content": {
                            "application/json": {
                                "example": {
                                    "status": "healthy",
                                    "service": "auth-service",
                                    "database": "connected",
                                    "minio": "connected",
                                }
                            }
                        },
                    },
                    "503": {
                        "description": "Serviço degradado (banco ou MinIO indisponível)",
                        "content": {
                            "application/json": {
                                "example": {
                                    "status": "unhealthy",
                                    "service": "auth-service",
                                    "database": "disconnected",
                                    "minio": "disconnected",
                                }
                            }
                        },
                    },
                },
            }
        },
        "/register": {
            "post": {
                "tags": ["Autenticação"],
                "summary": "Registrar novo usuário",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["nome", "email", "senha"],
                                "properties": {
                                    "nome": {"type": "string", "example": "Alice Santos"},
                                    "email": {"type": "string", "example": "alice@exemplo.com"},
                                    "senha": {"type": "string", "example": "senhaSegura123"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {"description": "Usuário criado"},
                    "400": {"description": "Dados inválidos"},
                    "409": {"description": "E-mail já cadastrado"},
                },
            }
        },
        "/login": {
            "post": {
                "tags": ["Autenticação"],
                "summary": "Realizar login",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "senha"],
                                "properties": {
                                    "email": {"type": "string", "example": "alice@exemplo.com"},
                                    "senha": {"type": "string", "example": "senhaSegura123"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Login realizado, cookie de sessão definido"},
                    "401": {"description": "Credenciais inválidas"},
                },
            }
        },
        "/logout": {
            "post": {
                "tags": ["Autenticação"],
                "summary": "Encerrar sessão",
                "responses": {"200": {"description": "Sessão encerrada"}},
            }
        },
        "/me": {
            "get": {
                "tags": ["Autenticação"],
                "summary": "Dados do usuário autenticado",
                "responses": {
                    "200": {"description": "Usuário autenticado"},
                    "401": {"description": "Não autenticado"},
                },
            }
        },
        "/forgot-password": {
            "post": {
                "tags": ["Recuperação de Senha"],
                "summary": "Solicitar link de recuperação de senha",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email"],
                                "properties": {"email": {"type": "string", "example": "alice@exemplo.com"}},
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Link enviado (ou silenciado se e-mail não existir)"}},
            }
        },
        "/reset-password": {
            "post": {
                "tags": ["Recuperação de Senha"],
                "summary": "Redefinir senha com token",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["token", "nova_senha"],
                                "properties": {
                                    "token": {"type": "string"},
                                    "nova_senha": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Senha redefinida"},
                    "400": {"description": "Token inválido ou expirado"},
                },
            }
        },
        "/reset-password/check": {
            "get": {
                "tags": ["Recuperação de Senha"],
                "summary": "Verificar validade do token de reset",
                "parameters": [
                    {
                        "name": "token",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {
                    "200": {"description": "Token válido"},
                    "400": {"description": "Token inválido ou expirado"},
                },
            }
        },
        "/users/{target_id}": {
            "get": {
                "tags": ["Perfil & Upload"],
                "summary": "Consultar perfil de usuário",
                "parameters": [
                    {
                        "name": "target_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {"description": "Perfil retornado"},
                    "404": {"description": "Usuário não encontrado"},
                },
            },
            "put": {
                "tags": ["Perfil & Upload"],
                "summary": "Atualizar nome e bio do perfil",
                "parameters": [
                    {
                        "name": "target_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "nome": {"type": "string"},
                                    "bio": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Perfil atualizado"},
                    "401": {"description": "Não autenticado"},
                    "403": {"description": "Acesso negado"},
                },
            },
        },
        "/users/{target_id}/avatar": {
            "post": {
                "tags": ["Perfil & Upload"],
                "summary": "Upload de avatar no MinIO",
                "parameters": [
                    {
                        "name": "target_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "avatar": {
                                        "type": "string",
                                        "format": "binary",
                                        "description": "Imagem (PNG/JPG/WEBP/GIF, máx 5MB)",
                                    }
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Avatar salvo"},
                    "400": {"description": "Arquivo inválido"},
                    "403": {"description": "Acesso negado"},
                },
            }
        },
        "/admin/users": {
            "get": {
                "tags": ["Administração"],
                "summary": "Listar todos os usuários (admin only)",
                "responses": {
                    "200": {"description": "Lista de usuários"},
                    "401": {"description": "Não autenticado"},
                    "403": {"description": "Acesso negado"},
                },
            }
        },
        "/admin/users/{target_id}/role": {
            "post": {
                "tags": ["Administração"],
                "summary": "Alterar papel do usuário (admin only)",
                "parameters": [
                    {
                        "name": "target_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["role"],
                                "properties": {
                                    "role": {"type": "string", "enum": ["usuario", "admin"]}
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Papel alterado"},
                    "403": {"description": "Acesso negado"},
                    "404": {"description": "Usuário não encontrado"},
                },
            }
        },
        "/internal/users/{user_id}": {
            "get": {
                "tags": ["Interno"],
                "summary": "Buscar usuário por ID (chamada interna)",
                "security": [{"InternalToken": []}],
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {"description": "Usuário encontrado"},
                    "403": {"description": "Token interno ausente ou inválido"},
                    "404": {"description": "Usuário não encontrado"},
                },
            }
        },
        "/auth/google/url": {
            "get": {
                "tags": ["Autenticação"],
                "summary": "Obter URL de autorização Google OAuth2",
                "description": "Retorna a URL para redirecionar o usuário ao fluxo de autenticação Google.",
                "responses": {
                    "200": {
                        "description": "URL de autorização",
                        "content": {"application/json": {"example": {"url": "https://accounts.google.com/..."}}},
                    },
                    "503": {"description": "Google OAuth não configurado"},
                },
            }
        },
        "/auth/google/callback": {
            "get": {
                "tags": ["Autenticação"],
                "summary": "Callback do Google OAuth2",
                "description": "Recebe o code do Google, autentica o usuário e redireciona para o frontend.",
                "parameters": [
                    {"name": "code", "in": "query", "required": False, "schema": {"type": "string"}},
                    {"name": "state", "in": "query", "required": False, "schema": {"type": "string"}},
                    {"name": "error", "in": "query", "required": False, "schema": {"type": "string"}},
                ],
                "responses": {
                    "302": {"description": "Redirecionamento para o frontend após autenticação"},
                    "400": {"description": "Código ou estado inválido"},
                    "502": {"description": "Falha na comunicação com o Google"},
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
            "  title: auth-service — API\n"
            "  version: 1.0.0\n"
        )
