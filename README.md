# Catálogo de Filmes — Tom Hanks 🎬

> Desenvolvido para a disciplina **ISW055 – Introdução à Computação em Nuvem**
> Professor: [@siriani](https://github.com/siriani)

---

## Atividade 3 — Microsserviço de Login

### O que mudou em relação à Atividade 2

Na atividade anterior, autenticação, cadastro e controle de acesso viviam no mesmo container do catálogo. Agora, toda a lógica de autenticação foi extraída para um **serviço dedicado** (`auth-service`), seguindo o conceito de microsserviços desacoplados.

```
Atividade 2: 1 container — catálogo + login + favoritos + comentários
Atividade 3: 2 containers — catálogo público | auth-service (só rede interna)
```

### Arquitetura

```
Internet
    │
    ▼
┌──────────────────────────┐
│  tomhanks-app :8080      │  ← único ponto de entrada público
│  (catálogo + frontend)   │
│                          │
│  /api/auth/* → proxy ───────────────────────────────────────────┐
│  /api/catalog            │                                       │
│  /api/favorites          │                                       │
│  /api/comments           │                                       │
└──────────────────────────┘                                       │
           ▲ rede: tomhanks-net                                    │
           │                                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  auth-service :3000                                              │
│  (login · cadastro · roles · esqueci minha senha · Mailtrap)    │
│  ⚠  SEM ports publicados — invisível para o host                 │
└──────────────────────────────────────────────────────────────────┘
           │
           ▼
    MySQL (cloud)
```

### Novidades

| Recurso | Descrição |
|---|---|
| `auth-service` | Container Flask separado, sem porta pública |
| Papéis de usuário | `usuario` via cadastro público e `admin` via `AUTH_ADMIN_*` |
| Esqueci minha senha | Envia e-mail real com link que expira em **30 minutos** |
| Tabela `reset_tokens` | `token`, `usuario_id`, `criado_em`, `expira_em`, `usado` |
| Mailtrap (dev) | E-mails de reset interceptados no sandbox — nunca saem de verdade |
| Rede interna Docker | `tomhanks-net` — catálogo e auth conversam por nome de serviço |
| `INTERNAL_TOKEN` | Segurança extra nas rotas `/internal/*` do auth-service |

### Tabela reset_tokens

```sql
CREATE TABLE reset_tokens (
    id         INT PRIMARY KEY AUTO_INCREMENT,
    token      VARCHAR(128) NOT NULL UNIQUE,
    usuario_id INT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criado_em  TIMESTAMP NOT NULL,
    expira_em  TIMESTAMP NOT NULL,   -- criado_em + 30 minutos
    usado      BOOLEAN NOT NULL DEFAULT FALSE
);
```

### Rotas do auth-service (rede interna)

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/health` | Status do serviço |
| `POST` | `/register` | Cadastro público (`nome`, `email`, `senha`) com role `usuario` |
| `POST` | `/login` | Login |
| `POST` | `/logout` | Logout |
| `GET` | `/me` | Usuário autenticado (via cookie de sessão) |
| `POST` | `/forgot-password` | Solicita link de reset por e-mail |
| `POST` | `/reset-password` | Redefine senha via token |
| `GET` | `/reset-password/check` | Verifica se o token ainda é válido |
| `GET` | `/internal/users/<id>` | Consulta interna (requer `X-Internal-Token`) |

O catálogo expõe os mesmos endpoints via `/api/auth/*` e faz proxy para o auth-service.

---

## Como executar

### Pré-requisitos

- Docker + Docker Compose
- Conta Mailtrap → [mailtrap.io](https://mailtrap.io) (sandbox gratuito)

### Configuração

```bash
cp .env.example .env
# Edite .env com suas credenciais:
#   TMDB_API_KEY, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
#   SMTP_USER e SMTP_PASS (Mailtrap → Email Testing → Inbox → SMTP)
#   AUTH_ADMIN_EMAIL e AUTH_ADMIN_PASSWORD para criar o usuário admin inicial
```

### Subir

```bash
docker compose up --build
```

O catálogo estará em `http://localhost:8080`.
O auth-service **não tem porta pública** — só acessível internamente.

### Fluxo de recuperação de senha

1. Usuário acessa `/forgot-password` e informa o e-mail
2. Auth-service gera token aleatório, grava `expira_em = agora + 30 min`, envia e-mail via Mailtrap
3. Usuário clica no link → frontend chama `GET /api/auth/reset-password/check?token=...`
4. Se válido, usuário informa nova senha → `POST /api/auth/reset-password`
5. Auth-service verifica: token existe? não expirou? não foi usado? → troca senha e marca `usado = true`
6. Link após 30 min ou após uso → retorna `400 Token expirado ou já utilizado`

Para a entrega, configure `SMTP_USER` e `SMTP_PASS` do Mailtrap e tire print do e-mail recebido.
Sem SMTP, a rota não quebra; em desenvolvimento, `PASSWORD_RESET_EXPOSE_LINK=1` mostra o link de teste.

---

## Estrutura do repositório

```
tomhanks/
├── backend/               # Catálogo Flask (favoritos, comentários, TMDB)
│   ├── app.py             # Proxy para auth-service + lógica de catálogo
│   ├── models.py          # Favorite, Comment (sem User — agora no auth-service)
│   └── database.py
├── auth_service/          # Microsserviço de autenticação ← NOVO
│   ├── app.py             # Login, cadastro, roles, esqueci-senha
│   ├── models.py          # User (com role), ResetToken
│   ├── database.py
│   └── migrations/
├── frontend/              # Angular build
├── Dockerfile             # Container do catálogo
├── Dockerfile.auth        # Container do auth-service ← NOVO
├── docker-compose.yml     # 2 serviços + rede tomhanks-net
├── alembic.ini            # Migrations do catálogo
└── alembic-auth.ini       # Migrations do auth-service ← NOVO
```

---

Professor: [@siriani](https://github.com/siriani)
