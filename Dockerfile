# ── Estágio 1: build do Angular ──────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend

# Instala dependências primeiro (melhor cache de camadas)
COPY frontend/front-tom-hanks/package*.json ./
RUN npm ci

# Copia o código-fonte e faz o build
COPY frontend/front-tom-hanks/ ./
RUN npm run build

# ── Estágio 2: runtime Python/Flask ──────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copia o backend
COPY alembic.ini ./
COPY backend ./backend

# Copia os arquivos estáticos gerados pelo Angular para onde o Flask os serve
COPY --from=frontend-builder /build/frontend/dist/front-tom-hanks/browser ./backend/static

# Copia o script de inicialização
COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 8080

CMD ["./start.sh"]
