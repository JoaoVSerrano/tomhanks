# Catálogo de Filmes — Tom Hanks 🎬

> Desenvolvido para a disciplina **ISW055 – Introdução à Computação em Nuvem**
> Professor: [@siriani](https://github.com/siriani)

---

## Atividade Extra — Documentação Swagger/OpenAPI

> Atividade Extra (ISW055) · Professor: [@siriani](https://github.com/siriani)

### Visão Geral

Todos os contratos de API de todos os microsserviços desenvolvidos na disciplina foram consolidados e padronizados no formato **OpenAPI 3.0**, permitindo a visualização interativa e testes diretos ("Try it out") pelo navegador via **Swagger UI**.

---

### Links de Acesso

| Recurso | URL / Rota | Descrição |
|---|---|---|
| **Swagger UI Interativo** | `http://localhost:8080/apidocs` | Interface web gráfica para explorar e testar cada endpoint |
| **OpenAPI Spec (JSON)** | `http://localhost:8080/api/docs/openapi.json` | Especificação completa em JSON (`openapi.json`) |
| **OpenAPI Spec (YAML)** | `http://localhost:8080/api/docs/openapi.yaml` | Especificação completa em YAML (`openapi.yaml`) |

---

### Cobertura de Endpoints Documentados (17 Endpoints)

1. **Health**:
   - `GET /api/health`: Status de saúde da aplicação
2. **Catálogo TMDB**:
   - `GET /api/catalog`: Listar filmes do Tom Hanks com contadores e estado da conta
3. **Autenticação & Contas (`auth-service`)**:
   - `POST /api/auth/register`: Registro de novos usuários
   - `POST /api/auth/login`: Autenticação e criação de sessão
   - `POST /api/auth/logout`: Encerramento de sessão
   - `GET /api/auth/me`: Obter dados da sessão do usuário logado
   - `POST /api/auth/forgot-password`: Solicitação de e-mail de redefinição de senha
4. **Perfil & Object Storage (`MinIO`)**:
   - `GET /api/profile/<user_id>`: Dados do perfil (nome, bio, avatar) e lista de favoritos
   - `PUT /api/profile/<user_id>`: Atualizar nome e bio (com validação 403 para terceiros)
   - `POST /api/profile/<user_id>/avatar`: Upload de foto de perfil no MinIO (PNG/JPG até 5MB)
   - `GET /api/profile/avatar/<key>`: Stream direto do avatar armazenado no MinIO
5. **Favoritos & Comentários**:
   - `POST /api/favorites`: Favoritar filme
   - `DELETE /api/favorites/<tmdb_movie_id>`: Desfavoritar filme
   - `POST /api/comments`: Criar comentário em um filme
   - `DELETE /api/comments/<comment_id>`: Apagar comentário (próprio usuário ou admin)
6. **Administração & Auditoria (`log-service` / Redis Streams)**:
   - `GET /api/admin/users`: Listar todos os usuários (exclusivo admin)
   - `POST /api/admin/users/<target_id>/role`: Promover/rebaixar papel do usuário (exclusivo admin)
   - `GET /api/admin/logs`: Consultar eventos no Redis Streams (exclusivo admin - 403 gravado no log)

---

### Como Testar a Documentação

Para executar o script de teste e verificação automatizada da documentação Swagger/OpenAPI:

```bash
bash demo_swagger.sh
```

---

## Atividade 6 — Upload e Perfil de Usuário (Object Storage)

> Atividade 6 (ISW055) · Professor: [@siriani](https://github.com/siriani)

### Por que a imagem de perfil não mora no banco de dados

Arquivos binários como imagens (JPEGs, PNGs) não pertencem ao banco de dados relacional (MariaDB/MySQL). Salvar imagens em colunas `BLOB` desnecessariamente infla o banco, torna os backups mais pesados e lentos, e degrada a performance de consultas estruturadas.

A solução de arquitetura de mercado adotada é guardar o arquivo binário em um **Object Storage dedicado (MinIO/S3)** e persistir no banco de dados relacional MariaDB apenas a referência metadata (`avatar_key`, ex: `avatar_7_1790809193.png`).

---

### Decisão de Arquitetura: Bucket Público vs URL Pré-assinada (Trade-offs)

Para a exibição da foto de perfil, foi escolhida a abordagem de **Bucket com Leitura Pública com Gateway Proxy na API**:

- **Por que Bucket Público?**
  - **Performance & Caching**: Fotos de perfil em redes sociais são mídias públicas por natureza. O acesso via bucket público com política de leitura (`s3:GetObject`) permite que navegadores e CDNs façam cache eficiente das imagens sem overhead de CPU para gerar assinaturas a cada renderização.
  - **Simplicidade & Escala**: Evita o processamento repetitivo de URLs com expiração (presigned URLs) no servidor para cada item de lista ou perfil exibido.
- **Trade-off com URLs Pré-assinadas**:
  - URLs pré-assinadas com tempo de expiração seriam a escolha correta para dados privados (ex: exames médicos, documentos financeiros, comprovantes). Para avatares de rede social, adicionar expiração geraria complexidade desnecessária e quebraria o cache do navegador a cada expiração.

---

### Controle de Acesso — Cada usuário só edita o próprio perfil (Regra 403)

O controle de identidade é estritamente aplicado no backend (servidor), reaproveitando a sessão autenticada da Atividade 4:
- Ao receber `PUT /api/profile/<user_id>` ou `POST /api/profile/<user_id>/avatar`, o backend valida se `session['user_id'] == user_id`.
- Se o usuário `Bob` (ID 8) tentar alterar o nome, bio ou enviar uma foto para o perfil da `Alice` (ID 7), a requisição é **recusada imediatamente com HTTP 403 Forbidden**:
  ```json
  {
    "error": "Você não tem permissão para editar este perfil."
  }
  ```
- Todas as tentativas de violação de perfil são gravadas no log de auditoria (`403_editar_perfil`, `403_upload_avatar`).

---

### Mapeamento de Endpoints do Perfil e Upload

| Método | Rota | Descrição | Permissão |
|---|---|---|---|
| `GET` | `/api/profile/<user_id>` | Retorna dados do usuário (nome, bio, avatar) e lista de filmes favoritados | Público / Autenticado |
| `PUT` | `/api/profile/<user_id>` | Atualiza nome e bio do perfil | Apenas o próprio usuário (403 se diferente) |
| `POST` | `/api/profile/<user_id>/avatar` | Upload de imagem de perfil para o MinIO (máx 5MB, PNG/JPG/WEBP/GIF) | Apenas o próprio usuário (403 se diferente) |
| `GET` | `/api/profile/avatar/<key>` | Proxy/Stream da imagem do MinIO diretamente ao cliente | Leitura pública |

---

### Estrutura dos Containers com MinIO

```yaml
services:
  # Object Storage MinIO para fotos de perfil (Atividade 6)
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data
    networks:
      - tomhanks-net

  # Microsserviço de Autenticação & Usuários
  auth-service:
    environment:
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
      MINIO_BUCKET_NAME: tomhanks-avatars
```

---

### Como Testar a Atividade 6

Para executar o script automatizado de teste e demonstração da Atividade 6:

```bash
bash demo_profile.sh
```

---

## Atividade 5 — Logs e Auditoria

### Por que um microsserviço próprio, e por que Redis Streams

Toda ação relevante do sistema — login, logout, favoritar, comentar, moderar — deixa agora um rastro num microsserviço dedicado (`log-service`), separado do catálogo e do auth-service. Log de auditoria tem padrão de uso distinto de dado de negócio: **escreve muito, lê pouco, nunca precisa de transação complexa**. Por isso vira um serviço à parte, e por isso o banco relacional (MariaDB) não é a ferramenta certa aqui.

**Redis Streams** (comandos `XADD` para gravar, `XREVRANGE` para consultar) foi escolhido por:
- Escrita em alto volume com latência mínima
- Ordenação nativa por timestamp no próprio ID do stream
- Trim automático (`MAXLEN ~`) para não crescer indefinidamente
- Persistência via `--appendonly yes` (AOF) no container Redis

### Arquitetura

```
Internet
    │
    ▼
┌──────────────────────────┐
│  tomhanks-app :8080      │  ← único ponto de entrada público
│  (catálogo + frontend)   │
│                          │
│  /api/auth/*  → proxy ─────────────────────────────┐
│  /api/admin/logs → proxy ──────────────────────┐   │
│  /api/catalog            │                     │   │
│  /api/favorites          │                     │   │
│  /api/comments           │                     │   │
└──────────────────────────┘                     │   │
           ▲ rede: tomhanks-net                  │   │
           │                                     ▼   ▼
           │                     ┌────────────────────────────────┐
           │                     │  log-service :4000             │
           │                     │  (auditoria — Redis Streams)   │
           │                     │  ⚠  SEM ports publicados       │
           │                     └────────────────────────────────┘
           │                                     │
           │                                     ▼
           │                     ┌────────────────────────────────┐
           │                     │  redis :6379                   │
           │                     │  (Stream: audit:logs)          │
           │                     │  ⚠  SEM ports publicados       │
           │                     └────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  auth-service :3000                                              │
│  (login · cadastro · roles · esqueci minha senha · Mailtrap)    │
│  ⚠  SEM ports publicados — invisível para o host                 │
└──────────────────────────────────────────────────────────────────┘
           │
           ▼
     MySQL (cloud)
```

### Eventos auditados

| Evento | Ação gravada |
|---|---|
| Login bem-sucedido | `login` |
| Login com credenciais erradas | `login_falhou` |
| Logout | `logout` |
| Favoritar filme | `favoritar` |
| Desfavoritar filme | `desfavoritar` |
| Criar comentário | `comentar` |
| Apagar próprio comentário | `apagar_comentario` |
| Admin apaga comentário de outro usuário | `moderacao_apagar_comentario` |
| Usuário comum tenta apagar comentário alheio | `403_apagar_comentario` |
| Usuário comum tenta acessar `GET /api/admin/logs` | `403_acesso_logs` |

### Estrutura mínima de cada log

```json
{
  "event_id": "1727746800000-0",
  "usuario_id": "42",
  "acao": "login",
  "detalhe": "email=joao@example.com",
  "ip": "172.20.0.5",
  "ts_ms": 1727746800000
}
```

### Endpoint de consulta — só admin

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/api/admin/logs?n=50` | Lista os últimos N eventos de auditoria (máx 500) |

Usuário comum tentando acessar recebe **HTTP 403**, e a tentativa fica registrada no próprio log.

### Novos serviços no docker-compose

```yaml
redis:          # Redis 7 Alpine — persistência AOF — sem porta pública
log-service:    # Flask + redis-py — API interna de auditoria — sem porta pública
```

---


## Atividade 4 — Controle de Acesso por Papel (RBAC)

### Permissões por papel

| Ação | `usuario` | `admin` |
|---|:---:|:---:|
| Cadastrar-se | ✅ | ✅ |
| Fazer login / logout | ✅ | ✅ |
| Solicitar redefinição de senha | ✅ | ✅ |
| Ver o catálogo de filmes | ✅ | ✅ |
| Favoritar / desfavoritar filmes | ✅ | ✅ |
| Criar comentários | ✅ | ✅ |
| Apagar **próprios** comentários | ✅ | ✅ |
| **Apagar comentários de qualquer usuário (moderação)** | ❌ | ✅ |
| **Listar todos os usuários** | ❌ | ✅ |
| **Promover / rebaixar role de um usuário** | ❌ | ✅ |

### Ação exclusiva de admin implementada

**Moderação de comentários** — um `admin` pode apagar o comentário de qualquer usuário chamando `DELETE /api/comments/<id>`. Um `usuario` comum tentando apagar um comentário que não é seu recebe **HTTP 403**.

O enforcement ocorre no servidor, em duas camadas:
1. **`backend/app.py`** — `require_role('admin')` consulta `/me` no auth-service e verifica o campo `role`.
2. **`auth_service/app.py`** — os endpoints `/admin/*` têm `require_admin()` que rejeita com 403 qualquer sessão sem `role == 'admin'`.

Esconder botões no frontend **não é** segurança; chamar o endpoint direto pelo Postman/curl com um token de `usuario` retorna 403.

### Novos endpoints admin

| Método | Rota (catálogo) | Rota (auth-service) | Descrição |
|---|---|---|---|
| `GET` | `/api/admin/users` | `/admin/users` | Lista todos os usuários |
| `POST` | `/api/admin/users/<id>/role` | `/admin/users/<id>/role` | Altera role (`usuario` ↔ `admin`) |
| `DELETE` | `/api/comments/<id>` | — | Admin apaga qualquer comentário; usuário só o próprio |

### Resposta: Padrão A ou Padrão B?

O `auth-service` usa **Padrão A — enforcement centralizado**.

A cada ação que exige verificação de permissão (`/api/admin/users`, `DELETE /api/comments/<id>`, etc.), o catálogo faz uma chamada de rede ao auth-service (`GET /me`) para obter o usuário atual e o seu `role`. A decisão "pode ou não pode" é tomada no servidor — auth-service para rotas `/admin/*` e catálogo para as rotas de comentários.

**O que mudaria no Padrão B (claims no token JWT)?**
O `role` seria embutido no JWT assinado no momento do login. Cada serviço decidiria sozinho, sem chamada extra, apenas decodificando o token. O catálogo não precisaria chamar `/me` — bastaria validar a assinatura do JWT localmente. A desvantagem: se um `usuario` for promovido a `admin`, ele só enxerga a mudança quando o token expirar e fizer login novamente. No Padrão A, o efeito é imediato porque cada request busca o `role` em tempo real no banco via auth-service.

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
