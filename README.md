# Catálogo de Filmes - Tom Hanks

Aplicação full-stack para buscar filmes com Tom Hanks na TMDB, permitir login/cadastro próprios e salvar favoritos e comentários no MariaDB sem misturar os dados entre usuários.

Professor da disciplina: `@siriani`

## O que a aplicação faz

- Busca o catálogo de Tom Hanks ao vivo na TMDB.
- Mostra pôster, título e sinopse vindos da API externa.
- Autentica usuários com conta própria da aplicação.
- Salva favoritos e comentários no MariaDB do aluno.
- Filtra tudo por sessão, usando o `usuario_id` do usuário logado.

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha os valores no seu ambiente ou no Portainer.

- `FLASK_SECRET_KEY`
- `TMDB_API_KEY`
- `DB_HOST`
- `DB_PORT`
- `DB_USER`
- `DB_PASSWORD`
- `DB_NAME`
- `CORS_ORIGINS`
- `SESSION_COOKIE_SAMESITE`
- `SESSION_COOKIE_SECURE`
- `PORT`

## Como executar com Docker

```bash
docker build -t tom-hanks-catalogo .
docker run --rm -p 5000:5000 --env-file .env tom-hanks-catalogo
```

## Estrutura

- `backend/` contém a API Flask, sessão, integração com TMDB e persistência no MariaDB.
- `frontend/front-tom-hanks/` contém o cliente Angular.
- `Dockerfile` faz o build do frontend e publica a aplicação final no mesmo container.

## Observações de segurança

- Nenhuma credencial deve ir para o frontend.
- A chave da TMDB e a senha do banco ficam apenas em variáveis de ambiente.
- O repositório não deve conter `.env`.

