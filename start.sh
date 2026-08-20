#!/bin/sh
set -e

# Garante a criação do schema no banco de dados antes de iniciar o servidor Web
python -c "from backend.app import app, ensure_schema; app.app_context().push(); ensure_schema()" || echo "Aviso: Nao foi possivel rodar ensure_schema antecipadamente, o app tentara na primeira requisicao."

# Inicia o servidor Gunicorn
exec gunicorn -b 0.0.0.0:${PORT:-5000} backend.app:app
